"""
Turn a live chain's newest segment into what the Current Traffic page
reads: KPI results, vehicle playback and run.json, in
frontend/public/data/<intersection>/live/.

Each update:

1. joins the segments' outputs into one run's worth of files
   (simulation/live/outputs.py): the FCD of the last FCD_INTERVALS
   segments (45 minutes), and the trip information and signal states of
   the whole chain (both small);
2. calculates the KPIs of the previous and the newest interval, the
   newest provisional, and merges them into the day's kpis.json and
   kpis_all.json (backend/analytics/service.py, section 16.5 of
   docs/kpi_engine.md);
3. rebuilds the vehicle files of the same two intervals and the signal
   file (simulation/scene_3d/build_playback.py);
4. writes run.json last.

Rules applied, and why:

- 45 minutes of FCD: the two intervals reported plus one before them,
  so every vehicle that arrives in them is seen from before it enters
  its zone. The results are the same as from the whole chain's FCD:
  1,470 of 1,470 in the A2 check of 19 Nov (docs/live_update_loop.md).
- The previous interval is calculated again: at the last update it was
  the newest, simulated only up to 60 s before its end, with its
  vehicles still driving. Now it is complete and its values are final.
- The planned departures given to the KPIs end where the simulation
  ends: a vehicle planned for later is not "never inserted", it simply
  has not been simulated yet.
- run.json is written last, and every file is written under a temporary
  name and then renamed, so the page never reads a half-written file,
  and a run.json always describes files that are already there.
- The folder holds one run only. A new chain's first update is built in
  .next/ while the previous chain stays on the page; only when its
  run.json is ready does the previous chain move to previous/ (run.json
  first) and the new files move in (run.json last). So the page never
  mixes two runs, and live/run.json is missing only for the moment the
  files are renamed, not for the minute or two the first update takes.
  The run that was in previous/ moves to earlier/<run ID>/, so restarts
  never lose the last 24 hours.
- Only a folder named live, holding a live run or nothing, is written
  to: the loop moves and deletes the .json files it finds there, so a
  wrong --out (such as the intersection's folder with the committed
  baseline files) is refused.
"""

import json
import math
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.service import (
    FRONTEND_DATA_DIR,
    RunFiles,
    calculate_kpis,
    collect_measurements,
    write_kpis,
)
from backend.outputs.playback import build_run_index, pack_signal_changes
from backend.outputs.signals import (
    check_one_indication_per_approach,
    find_signal_links,
    read_signal_changes,
)
from backend.outputs.vehicles import load_vehicle_movements
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.scenario import SimulationRun, SimulationRunStatus
from jaadah.sumo_demand.planner import RunWindow
from simulation.live.chain import INTERVAL, INTERVAL_S, LAG_S, ChainRecord
from simulation.live.outputs import combine_fcd, combine_tls_states, combine_tripinfo
from simulation.live.segments import segment_files

SCENE_DIR = Path(__file__).resolve().parents[1] / "scene_3d"
if str(SCENE_DIR) not in sys.path:
    sys.path.insert(0, str(SCENE_DIR))

from build_playback import UnderpassHeight, build_interval_payloads  # noqa: E402

LIVE_SCENARIO = "live"
FCD_INTERVALS = 3
REPORTED_INTERVALS = 2
UPDATE_DIR = "update"
RUN_FILE = "run.json"
SIGNALS_FILE = "signals.json"
NEXT_DIR = ".next"
# The page shows the last 24 hours: the newest run in live/, the run before
# it in live/previous/, and the runs before that (after restarts) in
# live/earlier/<run ID>/, listed in live/earlier/index.json, each until
# its intervals are 24 hours old.
PREVIOUS_DIR = "previous"
EARLIER_DIR = "earlier"
EARLIER_INDEX = "index.json"
KEEP_PUBLISHED = timedelta(hours=24)


def live_folder(intersection_id: str) -> Path:
    """frontend/public/data/<intersection>/live/"""

    return FRONTEND_DATA_DIR / intersection_id / LIVE_SCENARIO


def write_json_atomic(path: Path, payload: dict, compact: bool = True) -> Path:
    """Write JSON under a temporary name, then rename it into place."""

    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, separators=(",", ":")) if compact else json.dumps(payload, indent=1)
    temporary.write_text(text + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def chain_run(record: ChainRecord, demand_sha256: str, route_file_sha256: str) -> SimulationRun:
    """
    The chain as a SimulationRun for the KPI engine. The engine only
    calculates KPIs of a completed run; every part of a chain that it is
    given has been simulated to its end, so the record says completed.
    """

    return SimulationRun(
        run_id=record.run_id,
        scenario_id=record.scenario_id,
        random_seed=record.seed,
        network_version=record.network_version,
        sumo_version=record.sumo_version,
        step_length_s=record.step_length_s,
        status=SimulationRunStatus.COMPLETED,
        started_at=datetime.fromisoformat(record.started_at),
        mapping_version=record.mapping_version,
        demand_sha256=demand_sha256,
        route_file_sha256=route_file_sha256,
    )


def chain_window(record: ChainRecord, interval_end: datetime) -> RunWindow:
    """The chain so far as a run window: warm-up, then analysis up to the newest interval."""

    epoch = record.epoch_time
    return RunWindow(
        epoch=epoch,
        analysis_start=record.analysis_start_time,
        analysis_end=interval_end,
        run_end=interval_end,
    )


def reported_window(record: ChainRecord, interval_end: datetime) -> AnalysisInterval:
    """The intervals an update reports: the previous and the newest, inside the analysis period."""

    analysis_start = record.analysis_start_time
    start = max(analysis_start, interval_end - REPORTED_INTERVALS * INTERVAL)
    return AnalysisInterval(start, interval_end)


class LivePublisher:
    """
    Publishes a chain's updates. Keeps what is slow to read and the same
    for every update: the network mapping and the underpass model.
    """

    def __init__(
        self,
        mapping: NetworkMappingConfig,
        mapping_path: str | Path,
        network_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> None:
        self.mapping = mapping
        self.mapping_path = Path(mapping_path)
        self.network_path = Path(network_path)
        self.intersection_id = mapping.intersection_mapping.intersection_id
        self.output_dir = Path(output_dir) if output_dir else live_folder(self.intersection_id)
        check_output_folder(self.output_dir)
        self.signal_links = find_signal_links(mapping)
        self._underpass = None

    @property
    def underpass(self) -> UnderpassHeight:
        if self._underpass is None:
            self._underpass = UnderpassHeight(network_path=self.network_path)
        return self._underpass

    # ------------------------------------------------------------
    # files of the chain so far
    # ------------------------------------------------------------

    def join_outputs(self, record: ChainRecord, work_dir: Path, manifest: dict) -> dict:
        """Write the chain's joined outputs into work_dir/update/ and return their paths."""

        folder = work_dir / UPDATE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        segments = [
            segment_files(work_dir / item.folder, item.begin_s, item.end_s)
            for item in record.segments
        ]
        recent = segments[-FCD_INTERVALS:]
        end_s = record.last_end_s

        paths = {
            "fcd": combine_fcd([s.fcd_file for s in recent], folder / "fcd.xml"),
            "tripinfo": combine_tripinfo([s.tripinfo_file for s in segments], folder / "tripinfo.xml"),
            "tls_states": combine_tls_states(
                [s.tls_states_file for s in segments], [s.begin_s for s in segments],
                folder / "tls_states.xml",
            ),
            "manifest": write_json_atomic(folder / "manifest.json", {
                "departures": [item for item in manifest["departures"] if item["depart_s"] <= end_s],
            }),
            "fcd_start_s": recent[0].begin_s if recent[0].begin_s > 0 else None,
        }
        return paths

    # ------------------------------------------------------------
    # one update
    # ------------------------------------------------------------

    def publish(
        self,
        record: ChainRecord,
        work_dir: Path,
        demand_dir: Path,
        generated,
        state: dict,
    ) -> dict:
        """
        Publish the chain's newest interval: KPIs, playback and run.json.
        generated is the update's GeneratedDemand; state is the loop's
        status for run.json (simulation/live/loop.py). Returns run.json.
        """

        interval_end = record.last_interval_end
        manifest = json.loads(generated.manifest_file.read_text(encoding="utf-8"))
        joined = self.join_outputs(record, work_dir, manifest)
        run = chain_run(record, generated.demand_sha256, generated.route_file_sha256)
        window = chain_window(record, interval_end)
        reported = reported_window(record, interval_end)

        # A new chain's first update is built in .next/, so the run on the
        # page stays complete until the new one is ready.
        staging = self.output_dir / NEXT_DIR
        remove_published(staging)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        new_chain = self.published_run_id() != record.run_id
        target = staging if new_chain else self.output_dir
        target.mkdir(exist_ok=True)

        # KPIs
        files = RunFiles(
            run, window, joined["fcd"], joined["tripinfo"], joined["manifest"],
            generated.demand_file, joined["fcd_start_s"],
        )
        measurements = collect_measurements(files, self.mapping_path, self.network_path)
        results = calculate_kpis(
            measurements, self.mapping_path, self.network_path,
            time_window=reported, provisional=True,
            simulated_until=record.epoch_time + timedelta(seconds=record.last_end_s),
        )
        write_kpis(
            results, target, run,
            provisional_interval_start=interval_end - INTERVAL, merge=True,
        )

        # Playback
        run_index = build_run_index(
            run_id=record.run_id,
            intersection_id=self.intersection_id,
            scenario=LIVE_SCENARIO,
            run_start=record.epoch_time,
            duration_s=int((interval_end - record.epoch_time).total_seconds()),
            warm_up_s=int(record.warmup_s),
            clearance_s=0,
        )
        start_s = (reported.start - record.epoch_time).total_seconds()
        newest = [item for item in run_index["intervals"] if item["start_s"] >= start_s]
        payloads = build_interval_payloads(
            fcd_path=joined["fcd"],
            vehicle_movements=load_vehicle_movements(joined["manifest"], generated.demand_file),
            run_id=record.run_id,
            run_start=record.epoch_time,
            intervals=newest,
            underpass=self.underpass,
        )
        for name, payload in payloads.items():
            write_json_atomic(target / name, payload)

        changes = read_signal_changes(
            tls_path=joined["tls_states"],
            tls_id=self.mapping.intersection_mapping.sumo_tls_id,
            run_start=record.epoch_time,
            signal_links=self.signal_links,
        )
        check_one_indication_per_approach(changes=changes, config=self.mapping)
        write_json_atomic(
            target / SIGNALS_FILE,
            pack_signal_changes(run_id=record.run_id, changes=changes),
        )

        # run.json, last
        run_json = live_run_index(run_index, record, state)
        write_json_atomic(target / RUN_FILE, run_json, compact=False)
        if new_chain:
            self._start_folder(record)
            self._move_in(staging)
        self.trim_previous(interval_end)
        return run_json

    def _move_in(self, staging: Path) -> None:
        """Move a new chain's files from .next/ into live/, run.json last."""

        for path in sorted(staging.iterdir(), key=lambda item: item.name == RUN_FILE):
            os.replace(path, self.output_dir / path.name)
        staging.rmdir()

    def published_run_id(self) -> str | None:
        """The run ID of the published run.json, or None when nothing is published."""

        path = self.output_dir / RUN_FILE
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("run_id")

    def publish_state(self, state: dict) -> dict | None:
        """
        Change only the loop status in the published run.json (waiting
        for data, paused, stopped), keeping the files it describes.
        Returns the new run.json, or None when nothing is published yet.
        """

        path = self.output_dir / RUN_FILE
        if not path.is_file():
            return None

        run_json = json.loads(path.read_text(encoding="utf-8"))
        # problems and since_interval_end describe a pause: they go when it ends
        if state["state"] != "paused":
            for key in PAUSE_KEYS:
                run_json["live"].pop(key, None)
        run_json["live"].update(state)
        run_json["status"] = state_status(state["state"])
        write_json_atomic(path, run_json, compact=False)
        return run_json

    def _start_folder(self, record: ChainRecord) -> None:
        """
        Make the folder ready for this chain: created if missing. If it
        holds another run, that run moves to previous/, and the one in
        previous/ moves to earlier/<its run ID>/, so the page can still
        show the last 24 hours after any number of restarts; each folder
        holds one run. run.json leaves live/ first and arrives in
        previous/ last, so the page never reads a run whose files are
        not all there.
        """

        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_path = self.output_dir / RUN_FILE
        current = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else None

        if current is not None and current.get("run_id") == record.run_id:
            return

        # Without a run.json (a first start, or a first publish that failed
        # half way) live/ holds no complete run: previous/ stays as it is.
        previous = self.output_dir / PREVIOUS_DIR
        if current is not None:
            self._move_previous_to_earlier()
            remove_published(previous)
            previous.mkdir()
            run_path.unlink()
        for path in self.output_dir.iterdir():
            if not path.is_file():
                continue
            if current is not None and path.suffix == ".json":
                os.replace(path, previous / path.name)
            elif path.suffix in (".json", ".tmp"):
                path.unlink()
        if current is not None:
            # the moved run gets no more intervals: it is finished, whatever the loop was doing
            current["status"] = SimulationRunStatus.COMPLETED.value
            write_json_atomic(previous / RUN_FILE, current, compact=False)

    def _move_previous_to_earlier(self) -> None:
        """
        Move the run in previous/ to earlier/<run ID>/ in one rename, and
        list it in earlier/index.json. A previous/ without run.json (half
        removed) is left for remove_published.
        """

        previous = self.output_dir / PREVIOUS_DIR
        path = previous / RUN_FILE
        if not path.is_file():
            return
        run_id = json.loads(path.read_text(encoding="utf-8"))["run_id"]
        earlier = self.output_dir / EARLIER_DIR
        earlier.mkdir(exist_ok=True)
        target = earlier / run_id
        remove_published(target)
        os.replace(previous, target)
        self._write_earlier_index()

    def earlier_runs(self) -> list[Path]:
        """The folders in earlier/ that hold a run, oldest first."""

        earlier = self.output_dir / EARLIER_DIR
        if not earlier.is_dir():
            return []
        runs = []
        for folder in earlier.iterdir():
            path = folder / RUN_FILE
            if folder.is_dir() and path.is_file():
                runs.append((json.loads(path.read_text(encoding="utf-8"))["run_start"], folder))
        return [folder for _, folder in sorted(runs)]

    def _write_earlier_index(self) -> None:
        """earlier/index.json: the run IDs (folder names) in earlier/, oldest first."""

        earlier = self.output_dir / EARLIER_DIR
        runs = self.earlier_runs()
        if not runs:
            if earlier.exists():
                shutil.rmtree(earlier)
            return
        write_json_atomic(earlier / EARLIER_INDEX, {"runs": [folder.name for folder in runs]}, compact=False)

    def trim_previous(self, newest_end: datetime) -> None:
        """
        Drop the intervals that are 24 hours older than the newest one,
        from previous/ and every run in earlier/ (a whole folder once
        none is left), then list what is left in earlier/index.json.
        """

        trim_published(self.output_dir / PREVIOUS_DIR, newest_end)
        for folder in self.earlier_runs():
            trim_published(folder, newest_end)
        self._write_earlier_index()


def check_output_folder(folder: Path) -> None:
    """
    Refuse an output folder the loop must not move or delete files in:
    one not named live, or one whose run.json is not a live run's.
    """

    if folder.name != LIVE_SCENARIO:
        raise ValueError(
            f"the live output folder must be named {LIVE_SCENARIO!r} "
            f"(e.g. frontend/public/data/<intersection>/live/), not {str(folder)!r}"
        )
    path = folder / RUN_FILE
    if path.is_file() and json.loads(path.read_text(encoding="utf-8")).get("source") != "live":
        raise ValueError(f"{path} is not a live run's run.json; refusing to publish into {folder}")


def trim_published(folder: Path, newest_end: datetime) -> None:
    """
    Drop a published run's intervals that are 24 hours older than the
    newest interval: run.json first (its analysis period then starts
    later), then their vehicle files; the whole folder once none is left.
    """

    path = folder / RUN_FILE
    if not path.is_file():
        return

    run_json = json.loads(path.read_text(encoding="utf-8"))
    run_start = datetime.fromisoformat(run_json["run_start"])
    step = run_json["interval_s"]
    cutoff_s = (newest_end - KEEP_PUBLISHED - run_start).total_seconds()
    keep_from_s = math.ceil(cutoff_s / step) * step

    if keep_from_s <= run_json["analysis_start_s"]:
        return
    if keep_from_s >= run_json["analysis_end_s"]:
        remove_published(folder)
        return

    gone = [item for item in run_json["intervals"] if item["end_s"] <= keep_from_s]
    run_json["intervals"] = [item for item in run_json["intervals"] if item["end_s"] > keep_from_s]
    run_json["analysis_start_s"] = keep_from_s
    write_json_atomic(path, run_json, compact=False)
    for item in gone:
        (folder / item["file"]).unlink(missing_ok=True)


def interval_summary(folder: Path, interval_start: datetime) -> str:
    """
    One line for the loop's log: an interval's control delay at the
    intersection and on each approach, or why it was not measured, from
    the published kpis.json. So that what the page showed can be
    checked later, after the files are gone.
    """

    path = folder / "kpis.json"
    if not path.is_file():
        return "no KPIs"
    kpis = json.loads(path.read_text(encoding="utf-8"))
    parts = []
    for result in kpis["results"]:
        if result["kpi"] != "control_delay" or datetime.fromisoformat(result["interval_start"]) != interval_start:
            continue
        if result["level"] == "intersection":
            name = "intersection"
        elif result["level"] == "approach":
            name = result["approach_id"]
        else:
            continue
        value = f"{result['value']:.0f} s" if result["value"] is not None else f"none ({result['reason']})"
        parts.append((name != "intersection", name, f"{name} {value}"))
    if not parts:
        return "no delay results"
    return "; ".join(text for *_, text in sorted(parts))


def remove_published(folder: Path) -> None:
    """Remove a published run's folder, run.json first, so the page never reads half of it."""

    if not folder.exists():
        return
    (folder / RUN_FILE).unlink(missing_ok=True)
    shutil.rmtree(folder)


PAUSE_KEYS = ("problems", "since_interval_end")

LOOP_STATUSES = {
    "running": SimulationRunStatus.RUNNING.value,
    "starting": SimulationRunStatus.RUNNING.value,
    "waiting": SimulationRunStatus.RUNNING.value,
    "paused": SimulationRunStatus.RUNNING.value,
    "stopped": SimulationRunStatus.COMPLETED.value,
}


def state_status(loop_state: str) -> str:
    """run.json's status for a loop state: the run is running until the loop stops."""

    return LOOP_STATUSES[loop_state]


def live_run_index(run_index: dict, record: ChainRecord, state: dict) -> dict:
    """
    run.json of a live run: the playback index plus a "live" part with
    what the page needs to show the run as live (docs/live_update_loop.md,
    section "run.json").
    """

    epoch = record.epoch_time
    interval_end = record.last_interval_end

    def seconds(iso: str) -> float:
        return (datetime.fromisoformat(iso) - epoch).total_seconds()

    analysis_start_s = run_index["analysis_start_s"]

    return {
        **run_index,
        "status": state_status(state["state"]),
        "source": "live",
        "live": {
            **state,
            "data_until": interval_end.isoformat(),
            "simulated_until_s": record.last_end_s,
            "lag_s": LAG_S,
            "update_interval_s": INTERVAL_S,
            "provisional_interval_start_s": run_index["analysis_end_s"] - INTERVAL_S,
            "estimated_intervals": [
                {
                    "start_s": seconds(item.interval_start),
                    "end_s": seconds(item.interval_end),
                    "approach_ids": item.approach_ids,
                    "methods": item.methods,
                }
                for item in record.estimated_intervals
                if seconds(item.interval_start) >= analysis_start_s
            ],
        },
    }

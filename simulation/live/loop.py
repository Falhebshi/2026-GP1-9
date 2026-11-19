"""
The live update loop (Issue #48, option A2): keeps the Current Traffic
page up to date by simulating each 15-minute interval as soon as the
traffic source delivers it.

Each pass of the loop asks the source how far its data goes, then runs
every update that is due, in order (simulation/live/update.py), and
publishes each one (simulation/live/publish.py). The page reads
frontend/public/data/<intersection>/live/. docs/live_update_loop.md
describes the whole design.

What the loop does, and why:

- Next interval: the chain's next interval is simulated once the source
  has delivered it. Missed intervals (the loop was stopped for a while)
  are caught up one by one, up to MAX_CATCH_UP intervals; after a longer
  stop the loop starts a new chain at the newest data instead, because
  catching up a whole day would take most of an hour and the page would
  wait for it.
- New day: an interval that starts at or after 03:00 of a new day starts
  a new chain, with its warm-up from 02:45 (simulation/live/chain.py).
- Sensor outages: a silent detector is estimated for up to 8 intervals
  (backend/demand/imputation.py), and the interval is marked as
  estimated, so the page shows "No sensor data" for it (team decision,
  option 3). When an interval cannot be built (a gap longer than 8
  intervals, or any other demand problem), the loop pauses: run.json
  says so and why, and the last results stay on the page. As soon as an
  interval can be built again, a new chain starts with that interval as
  its warm-up, because the old chain cannot continue across intervals
  that have no demand.
- New chain at the newest data: a chain started in the middle of a day
  (first start, after a pause or a long stop) begins with the newest
  interval as its warm-up, so the page shows results one interval later,
  rather than after simulating the whole day so far.
- Cleaning up: the FCD of a segment is deleted once it is older than the
  45 minutes the KPIs and playback read; the last KEEP_STATES saved
  states are kept, so a segment can be rerun; trip information and
  signal states are small and kept for the chain. A chain's folder is
  deleted 24 hours after its last update.
"""

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx2

from jaadah.mapping.loader import load_network_mappings
from jaadah.sumo_demand.planner import compute_free_flow_times
from simulation.live.chain import (
    INTERVAL,
    RIYADH,
    WARMUP_S,
    ChainError,
    ChainRecord,
    chain_day,
    check_lag,
    day_epoch,
    load_record,
    run_id_of,
    save_record,
)
from simulation.live.demand import (
    HISTORY_DAYS,
    build_interval_demand,
    estimated_interval,
    load_demand,
)
from simulation.live.publish import FCD_INTERVALS, LivePublisher
from simulation.live.segments import FCD_FILE, RAW_DIR, STATE_FILE
from simulation.live.update import run_update

log = logging.getLogger("jaadah.live")

ACTIVE_FILE = "active.json"
MAX_CATCH_UP = 8
MAX_FAILURES = 3
MAX_STEPS_PER_PASS = 2 * MAX_CATCH_UP + 4
KEEP_STATES = 4
KEEP_CHAIN = timedelta(hours=24)
POLL_S = 10


@dataclass
class LoopSettings:
    """What the loop runs with; the defaults are those of the baseline runner."""

    source: str
    work_root: Path
    mapping_path: Path
    network_path: Path
    seed: int = 42
    step_length_s: float = 0.4
    sumo_bin: str = "sumo"
    sumo_version: str = "unknown"
    output_dir: Path | None = None
    history_days: int = HISTORY_DAYS


class LiveLoop:
    """One live loop: its chain, its source and where it publishes."""

    def __init__(self, client, settings: LoopSettings, now=None) -> None:
        self.client = client
        self.settings = settings
        self.now = now or (lambda: datetime.now(RIYADH))
        self.work_root = Path(settings.work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.mapping = load_network_mappings(settings.mapping_path, network_path=settings.network_path)
        self.free_flow_s = compute_free_flow_times(self.mapping, settings.network_path)
        check_lag(self.free_flow_s)
        self.publisher = LivePublisher(
            self.mapping, settings.mapping_path, settings.network_path, settings.output_dir,
        )
        self.record: ChainRecord | None = self._load_active()
        self.paused: dict | None = None
        self.failures = 0

    # ------------------------------------------------------------
    # chains
    # ------------------------------------------------------------

    def chain_dir(self, record: ChainRecord) -> Path:
        return self.work_root / record.run_id

    def _load_active(self) -> ChainRecord | None:
        """The chain the loop was running when it stopped, if it can be continued."""

        path = self.work_root / ACTIVE_FILE
        if not path.is_file():
            return None

        run_id = json.loads(path.read_text(encoding="utf-8"))["run_id"]
        try:
            record = load_record(self.work_root / run_id)
        except (ChainError, ValueError, KeyError, TypeError) as exc:
            log.warning("chain %s cannot be continued (%s); a new chain will start", run_id, exc)
            return None

        if record is None or not record.segments:
            return None
        last_state = self.work_root / run_id / record.segments[-1].folder / STATE_FILE
        if not last_state.is_file():
            log.warning("chain %s has no saved state; a new chain will start", run_id)
            return None
        return record

    def _new_chain(self, epoch: datetime) -> ChainRecord:
        record = ChainRecord(
            run_id=run_id_of(epoch, self.settings.seed),
            scenario_id=f"SCN_LIVE_{epoch.astimezone(RIYADH):%Y%m%dT%H%M}",
            epoch=epoch.isoformat(),
            seed=self.settings.seed,
            step_length_s=self.settings.step_length_s,
            sumo_version=self.settings.sumo_version,
            network_version=self.mapping.network.version,
            mapping_version=self.mapping.mapping_version,
            started_at=self.now().isoformat(),
        )
        folder = self.chain_dir(record)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        save_record(record, folder)
        (self.work_root / ACTIVE_FILE).write_text(
            json.dumps({"run_id": record.run_id}) + "\n", encoding="utf-8"
        )
        self.record = record
        log.info("new chain %s from %s", record.run_id, epoch.isoformat())
        return record

    @staticmethod
    def chain_day_of(record: ChainRecord):
        return chain_day(record.epoch_time + timedelta(seconds=WARMUP_S))

    # ------------------------------------------------------------
    # one pass
    # ------------------------------------------------------------

    def step(self) -> dict:
        """
        Run every update that is due and return the loop's state, as
        published in run.json.
        """

        latest = self.client.fetch_latest_available_timestamp()
        if latest is None:
            return self._publish_state("waiting", "The traffic source has no data yet.")

        record = self.record
        if record is not None and not self.paused:
            behind = (latest - record.next_interval_end()) // INTERVAL + 1
            if behind > MAX_CATCH_UP:
                log.info("chain %s is %d intervals behind; starting at the newest data", record.run_id, behind)
                self.record = None

        for _ in range(MAX_STEPS_PER_PASS):
            record = self.record

            if record is None or self.paused:
                started = self._start_at_newest(latest)
                if not started:
                    return self._current_state()
                continue

            interval_end = record.next_interval_end()
            interval_day = chain_day(interval_end - INTERVAL)

            # A new day's interval starts the new day's chain. A chain's own
            # warm-up (its first segment) is always simulated: for the daily
            # chain it is 02:45-03:00, which belongs to the day before.
            if record.segments and interval_day != self.chain_day_of(record):
                self._new_chain(day_epoch(interval_day))
                continue

            if interval_end > latest:
                return self._publish_state("running", "Up to date; the next interval is due at "
                                           f"{(interval_end).strftime('%H:%M')} (data time).")

            demand = self._build(interval_end, latest)
            if not demand.complete:
                self._pause(interval_end, demand.problems)
                continue

            self._update(record, demand)

        # Never reached in normal operation: a pass runs at most MAX_CATCH_UP
        # updates, a new chain and its warm-up. The bound keeps a logic error
        # from turning one pass into an endless loop.
        log.error("a pass did not finish within %d steps; the next pass goes on", MAX_STEPS_PER_PASS)
        return self._state("running", "Catching up.")

    def _build(self, interval_end: datetime, latest: datetime):
        return build_interval_demand(
            self.client, interval_end,
            source=self.settings.source,
            mapping_path=self.settings.mapping_path,
            available_until=latest,
            history_days=self.settings.history_days,
        )

    def _start_at_newest(self, latest: datetime) -> bool:
        """
        Start a chain whose warm-up is the newest interval, if its demand
        can be built. Returns False when it cannot (the loop stays paused
        or waiting).
        """

        if self.paused and latest <= datetime.fromisoformat(self.paused["since_interval_end"]):
            return False

        demand = self._build(latest, latest)
        if not demand.complete:
            if self.paused is None:
                self._pause(latest, demand.problems)
            return False

        record = self._new_chain(latest - INTERVAL)
        self.paused = None
        self._update(record, demand)
        return True

    def _update(self, record: ChainRecord, demand) -> None:
        folder = self.chain_dir(record)
        started = time.monotonic()
        result = run_update(
            record, folder, load_demand(folder), demand.demands,
            estimated_interval(demand.demands, self.mapping),
            mapping=self.mapping,
            network_path=self.settings.network_path,
            free_flow_s=self.free_flow_s,
            sumo_bin=self.settings.sumo_bin,
        )
        interval_end = record.last_interval_end
        if interval_end - record.epoch_time > timedelta(seconds=WARMUP_S):
            self.publisher.publish(
                record, folder, folder / "demand", result.generated,
                self._state("running", "Updated."),
            )
        self._clean(record)
        log.info(
            "%s: interval ending %s done in %.0f s%s", record.run_id, interval_end.strftime("%H:%M"),
            time.monotonic() - started, " (estimated)" if record.estimated_intervals
            and record.estimated_intervals[-1].interval_end == interval_end.isoformat() else "",
        )

    def _pause(self, interval_end: datetime, problems: list[str]) -> None:
        self.paused = {"since_interval_end": interval_end.isoformat(), "problems": problems[:10]}
        message = (
            f"Paused: the traffic for the interval ending {interval_end.strftime('%H:%M')} "
            "cannot be built. Detectors sent no data and could not be estimated (silent for "
            "more than 2 hours, or too few earlier days to estimate from). Updates restart "
            "with the first interval that can be built."
        )
        log.warning("%s %s", message, "; ".join(problems[:3]))
        self._publish_state("paused", message, problems=problems[:10])

    # ------------------------------------------------------------
    # state and cleaning up
    # ------------------------------------------------------------

    def _state(self, state: str, message: str, **extra) -> dict:
        return {"state": state, "message": message, "updated_at": self.now().isoformat(), **extra}

    def _publish_state(self, state: str, message: str, **extra) -> dict:
        """
        Report the loop's state in the published run.json. While a new
        chain warms up, run.json still describes the previous chain: the
        state is then "starting", so the page does not show the previous
        chain's results as live.
        """

        payload = self._state(state, message, **extra)
        published = self.publisher.published_run_id()

        if (
            state == "running" and self.record is not None
            and published is not None and published != self.record.run_id
        ):
            payload = self._state(
                "starting",
                "A new run has started; its first results are due at "
                f"{self.record.next_interval_end().strftime('%H:%M')} (data time).",
            )

        self.publisher.publish_state(payload)
        return payload

    def _current_state(self) -> dict:
        if self.paused:
            return self._state("paused", "Paused until the traffic data returns.", **self.paused)
        return self._state("waiting", "Waiting for traffic data.")

    def stop(self, reason: str = "The live loop was stopped.") -> None:
        self._publish_state("stopped", reason)

    def _clean(self, record: ChainRecord) -> None:
        folder = self.chain_dir(record)
        segments = record.segments
        for item in segments[:-FCD_INTERVALS]:
            (folder / item.folder / RAW_DIR / FCD_FILE).unlink(missing_ok=True)
        for item in segments[:-KEEP_STATES]:
            (folder / item.folder / STATE_FILE).unlink(missing_ok=True)

        now = time.time()
        for path in self.work_root.iterdir():
            if not path.is_dir() or path.name == record.run_id:
                continue
            marker = path / "chain.json"
            age = now - (marker.stat().st_mtime if marker.exists() else path.stat().st_mtime)
            if age > KEEP_CHAIN.total_seconds():
                shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------
    # running
    # ------------------------------------------------------------

    def run(self, poll_s: float = POLL_S) -> None:
        """Run passes until stopped (Ctrl+C), POLL_S seconds apart."""

        try:
            while True:
                self.pass_once()
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.stop()

    def pass_once(self) -> dict | None:
        """
        One pass that never stops the twin: a failed update is logged and
        tried again at the next pass. After MAX_FAILURES in a row, or at
        once when the chain itself is inconsistent (ChainError), the loop
        starts a new chain at the newest data instead of retrying forever.
        A source that cannot be reached is not a failed update: the loop
        reports it and waits, keeping its chain.
        """

        try:
            state = self.step()
            self.failures = 0
            log.debug("state: %s", state["state"])
            return state
        except httpx2.HTTPError as exc:
            # The source is down or restarting: nothing was simulated, so
            # the chain is fine. It is not a failed update; the loop waits
            # and catches up when the source answers again.
            log.warning("the traffic source cannot be reached: %s", exc)
            self._publish_state("waiting", "The traffic source cannot be reached; the loop keeps trying.")
            return None
        except Exception as exc:  # one failed pass must not stop the twin
            self.failures += 1
            log.exception("the update failed (%d in a row)", self.failures)
            if isinstance(exc, ChainError) or self.failures >= MAX_FAILURES:
                log.warning("starting a new chain at the newest data")
                self.record = None
                self.paused = None
                self.failures = 0
            self._publish_state("running", "The last update failed and is being retried.")
            return None

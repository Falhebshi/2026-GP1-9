"""
The live update loop on an invented site 1444 report (constant counts,
no RCRC values): the demand of each new interval, and whole passes of
the loop with SUMO (simulation/live/). The SUMO tests are skipped when
SUMO is not installed.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.demand.imputation import MAX_GAP_INTERVALS
from backend.ingestion.client import RcrcBatch
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.traffic import ImputationMethod
from simulation.live.demand import build_interval_demand, estimated_interval
from simulation.live.loop import MAX_CATCH_UP, MAX_FAILURES, LiveLoop, LoopSettings
from traffic_source.rcrc_replay.config import RIYADH
from traffic_source.rcrc_replay.report import RCRC_COLUMNS, read_rcrc_report
from traffic_source.rcrc_replay.storage import RcrcReplayStorage

ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "data" / "processed" / "road_network" / "jaadah_study_area.net.xml"
MAPPING = ROOT / "data" / "processed" / "road_network" / "network_mappings.json"
needs_sumo = pytest.mark.skipif(shutil.which("sumo") is None, reason="SUMO is not installed")

STEP = timedelta(minutes=15)
FIRST_DAY = datetime(2026, 7, 13, tzinfo=RIYADH)  # a Monday
DAYS = 28
NOON = datetime(2026, 8, 6, 12, 0, tzinfo=RIYADH)  # a Thursday
FRIDAY_NOON = datetime(2026, 8, 7, 12, 0, tzinfo=RIYADH)  # Fridays are a day type of their own

# The 12 stop-bar detectors of site 1444, with a constant artificial count.
DETECTORS = {
    "144409: P2-NB-L1-L-STB-RP2": 10, "144410: P2-NB-L2-L-STB-RP2": 10,
    "144411: P4-EB-L1-L-STB-RP4": 20, "144412: P4-EB-L2-TL-STB-RP4": 20,
    "144413: P4-EB-L3-T-STB-RP4": 20,
    "144414: P6-SB-L1-L-STB-RP6": 30, "144415: P6-SB-L2-L-STB-RP6": 30,
    "144416: P6-SB-L3-L-STB-RP6": 30,
    "144417: P8-WB-L1-L-STB-RP8": 40, "144418: P8-WB-L2-TL-STB-RP8": 40,
    "144419: P8-WB-L3-T-STB-RP8": 40, "144420: P8-WB-L4-T-STB-RP8": 40,
}
TITLE = (
    '"Intersection historical data report for : 1444  (test)\n'
    'From Jul 13, 2026 00:00 to Aug 10, 2026 00:00 ; Aggregation Interval: 15  (minutes)",,,,'
)


class StoredSource:
    """The replay's stored rows, with a source clock the test sets."""

    base_url = "test"

    def __init__(self, storage: RcrcReplayStorage, latest: datetime):
        self.storage = storage
        self.latest = latest
        self.history_starts = []

    def fetch_latest_available_timestamp(self):
        return self.latest

    def fetch_observations(self, start, end):
        self.history_starts.append(start)
        return RcrcBatch(site_id="1444", records=self.storage.get_rows(after=start, through=min(end, self.latest)))


@pytest.fixture
def source(tmp_path):
    """source(missing=set of interval ends) -> a StoredSource."""

    def make(missing=(), latest=NOON):
        header = ",".join(RCRC_COLUMNS)
        lines = [TITLE, header]
        for index, (detector, count) in enumerate(DETECTORS.items()):
            if index:
                lines.append(header)
            for step in range(1, DAYS * 96 + 1):
                moment = FIRST_DAY + step * STEP
                if moment not in missing:
                    lines.append(f'{detector},"{moment:%b %d, %Y %H:%M:%S}",{count},30,3')
        path = tmp_path / f"report{len(list(tmp_path.glob('report*')))}.csv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        storage = RcrcReplayStorage(path.with_suffix(".db"))
        storage.initialize()
        storage.load_report(read_rcrc_report(path))
        return StoredSource(storage, latest)

    return make


def demand_at(client, interval_end):
    return build_interval_demand(
        client, interval_end, source="rcrc", mapping_path=MAPPING, available_until=interval_end,
    )


# ============================================================
# THE DEMAND OF A NEW INTERVAL
# ============================================================

def test_a_reported_interval_becomes_demand_for_every_movement(source):
    demand = demand_at(source(), NOON)

    assert demand.complete
    assert len(demand.demands) == 9  # 6 counted movements + 2 slips and the bypass
    assert estimated_interval(demand.demands, load_network_mappings(MAPPING)) is None


def test_the_history_is_whole_days(source):
    """35 days before the interval's day, from midnight."""
    client = source()

    demand_at(client, NOON)

    assert client.history_starts[-1] == datetime(2026, 7, 2, 0, 0, tzinfo=RIYADH)


def test_a_silent_interval_is_estimated_including_the_slips(source):
    """
    The whole site is silent and the interval's batch is empty: the history
    still says the run is RCRC, so neither the synthetic detectors are
    reported missing nor are the slip and bypass estimates left out.
    """
    demand = demand_at(source(missing={NOON}), NOON)

    assert demand.complete, demand.problems
    assert len(demand.demands) == 9
    assert all(item.is_imputed for item in demand.demands)
    assert {d.method for item in demand.demands for d in item.imputed_detectors} == {
        ImputationMethod.LEVEL_ADJUSTED_AVERAGE}
    estimated = estimated_interval(demand.demands, load_network_mappings(MAPPING))
    assert estimated.approach_ids == ["APP_E", "APP_N", "APP_S", "APP_W"]
    assert estimated.methods == ["level_adjusted_average"]


def test_after_the_gap_limit_the_live_loop_uses_the_plain_average(source):
    silent = {NOON - k * STEP for k in range(MAX_GAP_INTERVALS + 1)}

    demand = demand_at(source(missing=silent), NOON)

    assert demand.complete, demand.problems
    assert {d.method for item in demand.demands for d in item.imputed_detectors} == {
        ImputationMethod.HISTORICAL_AVERAGE}


def test_a_long_outage_is_still_estimated(source):
    silent = {NOON - k * STEP for k in range(12)}  # 3 hours

    demand = demand_at(source(missing=silent), NOON)

    assert demand.complete, demand.problems
    assert {d.method for item in demand.demands for d in item.imputed_detectors} == {
        ImputationMethod.HISTORICAL_AVERAGE}


def test_an_interval_whose_time_slot_has_no_earlier_values_cannot_be_built(source):
    silent = {FRIDAY_NOON - timedelta(weeks=k) for k in range(4)}  # every Friday at 11:45

    demand = demand_at(source(missing=silent, latest=FRIDAY_NOON), FRIDAY_NOON)

    assert not demand.complete
    assert demand.problems


# ============================================================
# WHOLE PASSES OF THE LOOP, WITH SUMO
# ============================================================

def make_loop(client, tmp_path) -> LiveLoop:
    return LiveLoop(client, LoopSettings(
        source="rcrc", work_root=tmp_path / "work", mapping_path=MAPPING, network_path=NETWORK,
        sumo_version="1.27.1", output_dir=tmp_path / "live",
        restart_warmup_intervals=4,  # an hour, so the tests stay quick; the loop uses 3 hours
    ))


def published(tmp_path, name="run.json"):
    return json.loads((tmp_path / "live" / name).read_text(encoding="utf-8"))


def run_until(loop, client, last):
    states = []
    while client.latest <= last:
        states.append(loop.step())
        client.latest += STEP
    client.latest -= STEP
    return states


@needs_sumo
def test_the_loop_publishes_each_interval(source, tmp_path):
    client = source(latest=NOON)
    loop = make_loop(client, tmp_path)

    # A new chain warms up on the hour before the newest interval (10:45-11:45)
    # and shows the newest interval, 11:45-12:00, at once
    loop.step()
    run = published(tmp_path)
    assert run["run_id"] == "RUN_LIVE_20260806T1045_R1145_S42"
    assert run["analysis_start_s"] == 4 * 900
    assert run["live"]["data_until"] == NOON.isoformat()

    client.latest = NOON + 4 * STEP
    state = loop.step()  # catches up four intervals

    assert state["state"] == "running"
    run = published(tmp_path)
    assert run["run_id"] == "RUN_LIVE_20260806T1045_R1145_S42"
    assert (run["source"], run["status"]) == ("live", "running")
    assert run["analysis_end_s"] == 9 * 900
    assert run["live"]["data_until"] == (NOON + 4 * STEP).isoformat()
    assert run["live"]["simulated_until_s"] == 9 * 900 - 60
    assert run["live"]["estimated_intervals"] == []
    assert run["live"]["clock_offset_s"] == 0  # this test source has no replay clock

    kpis = published(tmp_path, "kpis.json")
    assert kpis["run_id"] == run["run_id"]
    assert kpis["provisional_interval_start"] == (NOON + 3 * STEP).isoformat()
    starts = {result["interval_start"] for result in kpis["results"]}
    assert starts == {(NOON + k * STEP).isoformat() for k in range(-1, 4)}

    for item in run["intervals"][4:]:
        assert (tmp_path / "live" / item["file"]).is_file()
    assert published(tmp_path, "signals.json")["run_id"] == run["run_id"]

    # Only the last 3 segments keep their FCD, the last 4 their state
    segments = sorted((tmp_path / "work" / run["run_id"] / "segments").iterdir())
    assert [(s / "raw" / "fcd.xml").exists() for s in segments] == [False] * 6 + [True] * 3
    assert [(s / "state.xml.gz").exists() for s in segments] == [False] * 5 + [True] * 4


@needs_sumo
def test_a_restarted_loop_continues_its_chain(source, tmp_path):
    client = source(latest=NOON)
    run_until(make_loop(client, tmp_path), client, NOON + STEP)

    client.latest = NOON + 3 * STEP
    loop = make_loop(client, tmp_path)  # a new process
    loop.step()

    assert loop.record.run_id == "RUN_LIVE_20260806T1045_R1145_S42"
    assert len(loop.record.segments) == 8
    assert published(tmp_path)["live"]["data_until"] == (NOON + 3 * STEP).isoformat()


@needs_sumo
def test_a_loop_far_behind_starts_again_at_the_newest_data(source, tmp_path):
    client = source(latest=NOON)
    run_until(make_loop(client, tmp_path), client, NOON + STEP)

    client.latest = NOON + (MAX_CATCH_UP + 3) * STEP
    loop = make_loop(client, tmp_path)
    loop.step()

    # the hour before the newest interval is its warm-up, and the newest is shown
    assert loop.record.epoch_time == client.latest - 5 * STEP
    assert loop.record.warmup_s == 4 * 900
    assert len(loop.record.segments) == 5
    assert published(tmp_path)["run_id"] == loop.record.run_id


@needs_sumo
def test_a_long_outage_is_estimated_and_marked_and_the_chain_goes_on(source, tmp_path):
    """Silent from 12:30 for 3 hours: every interval is estimated and marked, in one chain."""
    outage = [NOON + (2 + k) * STEP for k in range(12)]
    client = source(missing=set(outage), latest=NOON)
    loop = make_loop(client, tmp_path)

    states = run_until(loop, client, outage[-1] + STEP)

    assert {state["state"] for state in states} == {"running"}
    run = published(tmp_path)
    assert run["run_id"] == "RUN_LIVE_20260806T1045_R1145_S42"  # still the first chain
    marked = [(item["start_s"], item["end_s"]) for item in run["live"]["estimated_intervals"]]
    epoch = datetime.fromisoformat(run["run_start"])
    assert marked == [
        ((end - STEP - epoch).total_seconds(), (end - epoch).total_seconds()) for end in outage
    ]


@needs_sumo
def test_an_interval_that_cannot_be_estimated_pauses_the_loop_and_it_restarts(source, tmp_path):
    """
    Friday 12:15-12:30 is silent, and so was that slot on every earlier Friday, so
    it cannot be estimated: the loop pauses. Data returns with the interval ending
    12:45; the interval before it cannot be built, so it is the new chain's warm-up.
    """
    gap = FRIDAY_NOON + 2 * STEP
    client = source(missing={gap - timedelta(weeks=k) for k in range(4)}, latest=FRIDAY_NOON)
    loop = make_loop(client, tmp_path)
    run_until(loop, client, FRIDAY_NOON + STEP)
    run = published(tmp_path)

    client.latest = gap
    assert loop.step()["state"] == "paused"
    assert published(tmp_path)["live"]["state"] == "paused"
    assert "cannot be built" in published(tmp_path)["live"]["message"]

    client.latest = gap + STEP  # data again: a new chain warms up on it
    loop.step()
    assert loop.record.epoch_time == gap
    assert loop.record.warmup_s == 900
    assert published(tmp_path)["run_id"] == run["run_id"]  # nothing new to show yet
    assert published(tmp_path)["live"]["state"] == "starting"  # so the old results are not "live"

    client.latest += STEP
    loop.step()
    run = published(tmp_path)
    assert run["run_id"] == "RUN_LIVE_20260807T1230_R1245_S42"
    assert run["live"]["state"] == "running"
    assert not (tmp_path / "live" / "vehicles_1215.json").exists()  # the old chain's files moved
    assert (tmp_path / "live" / "previous" / "vehicles_1215.json").is_file()


@needs_sumo
def test_by_default_a_restart_warms_up_from_the_start_of_the_day(source, tmp_path):
    client = source(latest=NOON)
    loop = LiveLoop(client, LoopSettings(
        source="rcrc", work_root=tmp_path / "work", mapping_path=MAPPING, network_path=NETWORK,
        sumo_version="1.27.1", output_dir=tmp_path / "live",
    ))
    loop.step()

    assert loop.record.run_id == "RUN_LIVE_20260806T0245_R1145_S42"
    assert loop.record.warmup_s == 36 * 900  # 02:45 to 11:45
    assert len(loop.record.segments) == 37
    assert published(tmp_path)["live"]["data_until"] == NOON.isoformat()


@needs_sumo
def test_a_new_day_starts_a_new_chain_at_02_45(source, tmp_path):
    client = source(latest=datetime(2026, 8, 7, 2, 30, tzinfo=RIYADH))
    loop = make_loop(client, tmp_path)

    run_until(loop, client, datetime(2026, 8, 7, 3, 15, tzinfo=RIYADH))

    assert loop.record.run_id == "RUN_LIVE_20260807T0245_S42"
    assert published(tmp_path)["run_id"] == "RUN_LIVE_20260807T0245_S42"
    assert (tmp_path / "work" / "RUN_LIVE_20260807T0115_R0215_S42").is_dir()  # kept for 24 hours


@needs_sumo
def test_a_restart_just_after_03_00_warms_up_across_it(source, tmp_path):
    """A chain whose warm-up crosses 03:00 belongs to the day its results start in."""

    client = source(latest=datetime(2026, 8, 7, 3, 30, tzinfo=RIYADH))
    loop = make_loop(client, tmp_path)
    loop.step()

    assert loop.record.run_id == "RUN_LIVE_20260807T0215_R0315_S42"
    assert published(tmp_path)["run_id"] == "RUN_LIVE_20260807T0215_R0315_S42"
    assert not (tmp_path / "work" / "RUN_LIVE_20260807T0245_S42").exists()


# ============================================================
# FAILED UPDATES
# ============================================================

def some_chain():
    from simulation.live.chain import ChainRecord

    return ChainRecord(
        run_id="RUN_LIVE_20260806T1145_S42", scenario_id="SCN_LIVE_20260806T1145",
        epoch=(NOON - STEP).isoformat(), seed=42, step_length_s=0.4, sumo_version="1.27.1",
        network_version="test", mapping_version="test", started_at=NOON.isoformat(),
    )


def write_published(folder, run_id, run_start, analysis_start_s, analysis_end_s):
    folder.mkdir(parents=True, exist_ok=True)
    intervals = [
        {"start_s": s, "end_s": s + 900, "file": f"vehicles_{k}.json"}
        for k, s in enumerate(range(0, analysis_end_s, 900))
    ]
    for item in intervals:
        (folder / item["file"]).write_text("{}", encoding="utf-8")
    (folder / "kpis.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    run = {"run_id": run_id, "run_start": run_start.isoformat(), "analysis_start_s": analysis_start_s,
           "analysis_end_s": analysis_end_s, "interval_s": 900, "intervals": intervals}
    (folder / "run.json").write_text(json.dumps(run), encoding="utf-8")


def test_a_new_run_moves_the_published_one_to_previous(source, tmp_path):
    loop = make_loop(source(), tmp_path)
    live = tmp_path / "live"
    write_published(live / "previous", "RUN_OLDER", NOON - timedelta(days=2), 900, 3600)
    write_published(live, "RUN_LIVE_20260805T0245_S42", NOON - timedelta(days=1), 900, 3600)

    loop.publisher._start_folder(some_chain())

    assert not list(live.glob("*.json"))
    previous = json.loads((live / "previous" / "run.json").read_text(encoding="utf-8"))
    assert previous["run_id"] == "RUN_LIVE_20260805T0245_S42"  # the older one is gone
    assert {p.name for p in (live / "previous").iterdir()} == {
        "run.json", "kpis.json", "vehicles_0.json", "vehicles_1.json", "vehicles_2.json", "vehicles_3.json",
    }

    loop.publisher._start_folder(some_chain())  # the same run again: nothing moves
    assert (live / "previous" / "run.json").is_file()


def test_the_previous_run_keeps_only_the_last_24_hours(source, tmp_path):
    loop = make_loop(source(), tmp_path)
    previous = tmp_path / "live" / "previous"
    run_start = NOON - timedelta(days=1)
    write_published(previous, "RUN_PREVIOUS", run_start, 900, 4500)  # analysis 12:15-13:15

    loop.publisher.trim_previous(run_start + timedelta(days=1, seconds=1800))
    run = json.loads((previous / "run.json").read_text(encoding="utf-8"))
    assert run["analysis_start_s"] == 1800
    assert [item["file"] for item in run["intervals"]] == ["vehicles_2.json", "vehicles_3.json", "vehicles_4.json"]
    assert not (previous / "vehicles_1.json").exists() and (previous / "vehicles_2.json").exists()

    loop.publisher.trim_previous(run_start + timedelta(days=1, seconds=4500))
    assert not previous.exists()  # nothing left within 24 hours


def test_a_failed_update_is_retried_and_after_three_the_chain_starts_again(source, tmp_path, monkeypatch):
    loop = make_loop(source(), tmp_path)
    chain = loop.record = some_chain()

    def fail():
        raise RuntimeError("SUMO crashed")

    monkeypatch.setattr(loop, "step", fail)

    assert loop.pass_once() is None and loop.record is chain
    assert loop.pass_once() is None and loop.record is chain
    assert loop.pass_once() is None and loop.record is None


def test_the_loop_reports_how_far_the_source_clock_is_behind(source, tmp_path):
    loop = make_loop(source(), tmp_path)
    loop.now = lambda: NOON + timedelta(weeks=13)

    assert loop._clock_offset_s() == 0  # no replay clock: real time

    loop.client.fetch_source_clock = lambda: NOON
    assert loop._clock_offset_s() == 13 * 7 * 24 * 3600

    loop.clock_offset_s = loop._clock_offset_s()
    assert loop._state("running", "Updated.")["clock_offset_s"] == 13 * 7 * 24 * 3600


def test_a_restart_has_no_warm_up_limit_by_default():
    from simulation.live.loop import RESTART_WARMUP_INTERVALS

    assert RESTART_WARMUP_INTERVALS is None
    assert LoopSettings(
        source="rcrc", work_root=Path("w"), mapping_path=MAPPING, network_path=NETWORK,
    ).restart_warmup_intervals is None


def test_a_source_that_cannot_be_reached_keeps_the_chain(source, tmp_path, monkeypatch):
    import httpx2

    loop = make_loop(source(), tmp_path)
    chain = loop.record = some_chain()

    def unreachable():
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr(loop, "step", unreachable)
    published_states = []
    monkeypatch.setattr(loop.publisher, "publish_state", published_states.append)

    for _ in range(MAX_FAILURES + 2):
        assert loop.pass_once() is None

    assert loop.record is chain and loop.failures == 0
    assert {state["state"] for state in published_states} == {"waiting"}
    assert "cannot be reached" in published_states[-1]["message"]


def test_an_inconsistent_chain_starts_again_at_once(source, tmp_path, monkeypatch):
    from simulation.live.chain import ChainError

    loop = make_loop(source(), tmp_path)
    loop.record = some_chain()

    def inconsistent():
        raise ChainError("the departures already simulated would change")

    monkeypatch.setattr(loop, "step", inconsistent)

    assert loop.pass_once() is None
    assert loop.record is None


def test_a_pass_has_a_bounded_number_of_steps(source, tmp_path, monkeypatch):
    """A logic error that never reaches a stopping point cannot make one pass endless."""
    from simulation.live.loop import MAX_STEPS_PER_PASS

    loop = make_loop(source(), tmp_path)
    starts = []
    monkeypatch.setattr(loop, "_start_at_newest", lambda latest: starts.append(latest) or True)

    assert loop.step()["message"] == "Catching up."
    assert len(starts) == MAX_STEPS_PER_PASS

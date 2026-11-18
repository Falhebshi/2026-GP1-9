"""
The baseline runner with the RCRC replay source, up to the point where
SUMO would start (SUMO is replaced by a stub that captures the demand).
"""

from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

import simulation.scripts.run_baseline as baseline
from backend.ingestion.client import RcrcReplayClient
from jaadah.models.traffic import ImputationMethod
from simulation.scripts.run_baseline import BaselineNotStarted, run_baseline
from traffic_source.rcrc_replay.config import RIYADH, ReplayConfig
from traffic_source.rcrc_replay.report import RCRC_COLUMNS, read_rcrc_report
from traffic_source.rcrc_replay.server import create_app
from traffic_source.rcrc_replay.storage import RcrcReplayStorage


STEP = timedelta(minutes=15)
FIRST_DAY = datetime(2026, 7, 13, tzinfo=RIYADH)  # a Monday
DAYS = 28
ANALYSIS_START = datetime(2026, 8, 6, 8, 0, tzinfo=RIYADH)  # a Thursday
ANALYSIS_END = ANALYSIS_START + timedelta(minutes=30)
RUN_START = ANALYSIS_START - STEP
RUN_END = ANALYSIS_END + STEP

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


def write_report(path, missing=()):
    header = ",".join(RCRC_COLUMNS)
    lines = [TITLE, header]

    for index, (detector, count) in enumerate(DETECTORS.items()):
        if index:
            lines.append(header)
        for step in range(1, DAYS * 96 + 1):
            moment = FIRST_DAY + step * STEP
            if moment not in missing:
                lines.append(f'{detector},"{moment:%b %d, %Y %H:%M:%S}",{count},30,3')

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def rcrc_source(tmp_path, monkeypatch):
    """Connect the runner to a replay source; return (client, captured demand)."""

    apis = []
    captured = {}

    def connect(missing=(), released_through=RUN_END):
        storage = RcrcReplayStorage(tmp_path / f"replay{len(apis)}.db")
        storage.initialize()
        storage.load_report(read_rcrc_report(write_report(tmp_path / f"r{len(apis)}.csv", missing)))
        # The real time at which the replay has released through `released_through`.
        config = ReplayConfig(offset_weeks=16)
        real_now = released_through + timedelta(weeks=16)
        api = TestClient(create_app(storage=storage, config=config, now=lambda: real_now))
        api.__enter__()
        apis.append(api)

        def get(url, params=None, timeout=None):
            response = api.get(url.removeprefix("http://rcrc-source"), params=params)
            return httpx2.Response(
                response.status_code, json=response.json(), request=httpx2.Request("GET", url)
            )

        monkeypatch.setattr("backend.ingestion.client.httpx2.get", get)
        return RcrcReplayClient("http://rcrc-source")

    def capture(scenario, config, run, demands, **kwargs):
        captured["demands"] = demands
        raise ValueError("SUMO stub: stop after capturing the demand")

    monkeypatch.setattr(baseline, "sumo_version", lambda sumo_bin="sumo": "1.27.1")
    monkeypatch.setattr(baseline, "generate_and_execute_scenario", capture)

    yield connect, captured

    for api in apis:
        api.__exit__(None, None, None)


def run(client, tmp_path, history_days=35):
    with pytest.raises(BaselineNotStarted) as stopped:
        run_baseline(
            ANALYSIS_START, ANALYSIS_END,
            client=client, output_dir=tmp_path / "out", run_id="RUN_TEST",
            source="rcrc", history_days=history_days,
        )
    return stopped.value.problems


def test_rcrc_window_becomes_demand_for_every_movement(rcrc_source, tmp_path):
    connect, captured = rcrc_source

    problems = run(connect(), tmp_path)

    assert problems[0] == "SUMO stub: stop after capturing the demand"
    demands = captured["demands"]
    # 6 counted movements + 3 slips estimated from the lane rule, 4 intervals.
    assert len(demands) == 9 * 4
    first = {d.movement_id: d for d in demands if d.interval_start == RUN_START}
    assert first["MOV_N_E"].vehicle_count == 90
    assert first["MOV_N_W_SLIP"].vehicle_count == 30  # 1/3 of 90
    assert first["MOV_S_E_BYPASS"].vehicle_count == 20  # 1 x (10 + 10)
    assert first["MOV_N_W_SLIP"].is_share_estimated


def test_short_outage_inside_the_window_is_estimated(rcrc_source, tmp_path):
    connect, captured = rcrc_source
    outage = {ANALYSIS_START + STEP, ANALYSIS_START + 2 * STEP}

    run(connect(missing=outage), tmp_path)

    estimated = [
        d for d in captured["demands"]
        if d.interval_end in outage and d.movement_id == "MOV_E_W"
    ]
    assert len(estimated) == 2
    assert all(
        {i.method for i in d.imputed_detectors} == {ImputationMethod.LEVEL_ADJUSTED_AVERAGE}
        for d in estimated
    )


def test_outage_at_the_newest_interval_is_estimated_live(rcrc_source, tmp_path):
    """The source has delivered through RUN_END, but the last interval is silent."""

    connect, captured = rcrc_source

    run(connect(missing={RUN_END}), tmp_path)

    newest = [d for d in captured["demands"] if d.interval_end == RUN_END]
    assert len(newest) == 9
    assert all(d.is_imputed for d in newest)


def test_long_outage_stops_the_run(rcrc_source, tmp_path):
    connect, _ = rcrc_source
    outage = {RUN_START + k * STEP for k in range(-2, 5)}  # 7 intervals

    problems = run(connect(missing=outage), tmp_path)

    assert problems[0] == "Movement demand could not be built:"


def test_without_history_an_outage_stops_the_run(rcrc_source, tmp_path):
    connect, _ = rcrc_source

    problems = run(connect(missing={ANALYSIS_START + STEP}), tmp_path, history_days=0)

    assert problems[0] == "Movement demand could not be built:"

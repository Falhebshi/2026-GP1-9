"""Run the baseline from a real synthetic source, in-process, to the raw SUMO outputs."""

import json
import shutil
from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from backend.ingestion.client import SyntheticTrafficClient
from simulation.scripts.run_baseline import BaselineNotStarted, run_baseline
from test_demand_ingestion_integration import TIMEZONE, artificial_profiles
from traffic_source.synthetic.config import SyntheticSourceConfig
from traffic_source.synthetic.generator import SyntheticTrafficGenerator
from traffic_source.synthetic.producer import SyntheticTrafficProducer
from traffic_source.synthetic.server import create_app
from traffic_source.synthetic.storage import SyntheticTrafficStorage


# A Sunday morning, so a workday. With 15 minutes of warm-up and clearance
# the run window of an 08:00-09:00 analysis is 07:45-09:15.
ANALYSIS_START = datetime(2026, 10, 18, 8, 0, tzinfo=TIMEZONE)
ANALYSIS_END = ANALYSIS_START + timedelta(hours=1)
RUN_END = ANALYSIS_END + timedelta(minutes=15)


@pytest.fixture
def source(tmp_path, monkeypatch):
    """
    Return a function that fills a real synthetic source up to a given
    time, optionally without some detectors, and returns an ingestion
    client connected to it.
    """

    profiles = artificial_profiles()
    config = SyntheticSourceConfig()
    apis = []

    def connect(stored_through: datetime, without_detectors=()) -> SyntheticTrafficClient:
        storage = SyntheticTrafficStorage(tmp_path / "synthetic.db")
        storage.initialize()
        producer = SyntheticTrafficProducer(
            SyntheticTrafficGenerator(profiles, config), storage, config
        )
        storage.insert_observations([
            observation
            for observation in producer._generate_window(
                stored_through - timedelta(days=1), stored_through
            )
            if observation.detector_id not in without_detectors
        ])

        api = TestClient(create_app(profiles=profiles, storage=storage, run_producer=False))
        api.__enter__()
        apis.append(api)

        def get_from_source(url, params=None, timeout=None):
            path = url.removeprefix("http://synthetic-source")
            response = api.get(path, params=params)
            return httpx2.Response(
                response.status_code,
                json=response.json(),
                request=httpx2.Request("GET", url),
            )

        monkeypatch.setattr("backend.ingestion.client.httpx2.get", get_from_source)
        return SyntheticTrafficClient("http://synthetic-source")

    yield connect

    for api in apis:
        api.__exit__(None, None, None)


def test_run_does_not_start_before_the_source_holds_the_whole_window(source, tmp_path) -> None:
    client = source(stored_through=ANALYSIS_END)
    output_dir = tmp_path / "baseline"

    with pytest.raises(BaselineNotStarted) as stopped:
        run_baseline(
            ANALYSIS_START, ANALYSIS_END,
            client=client, output_dir=output_dir, run_id="RUN_TEST",
        )

    assert stopped.value.problems == [
        "Traffic data are not yet complete for this simulation window.",
        f"Required through: {RUN_END.isoformat()}",
        f"Latest available: {ANALYSIS_END.isoformat()}",
    ]
    assert not output_dir.exists()


def test_run_does_not_start_when_a_detector_is_missing(source, tmp_path) -> None:
    client = source(stored_through=RUN_END, without_detectors={6})
    output_dir = tmp_path / "baseline"

    with pytest.raises(BaselineNotStarted) as stopped:
        run_baseline(
            ANALYSIS_START, ANALYSIS_END,
            client=client, output_dir=output_dir, run_id="RUN_TEST",
        )

    # Detector 6 feeds only MOV_N_E; every interval of the run window is reported.
    interval_ends = [ANALYSIS_START + timedelta(minutes=15 * step) for step in range(6)]
    assert stopped.value.problems == ["Movement demand could not be built:"] + [
        f"movement MOV_N_E, {end.isoformat()}: no observation from detector(s) 6"
        for end in interval_ends
    ]
    assert not output_dir.exists()


@pytest.mark.skipif(shutil.which("sumo") is None, reason="SUMO is not installed")
def test_baseline_runs_from_the_source_to_the_raw_sumo_outputs(source, tmp_path) -> None:
    # A 15-minute analysis keeps the test short: 07:45-08:30, 2,700 s.
    analysis_end = ANALYSIS_START + timedelta(minutes=15)
    client = source(stored_through=analysis_end + timedelta(minutes=15))
    output_dir = tmp_path / "baseline"

    summary = run_baseline(
        ANALYSIS_START, analysis_end,
        client=client, output_dir=output_dir, run_id="RUN_TEST",
    )

    assert summary["status"] == "completed"
    assert summary["run_window"]["duration_s"] == 2700
    # 16 detectors and 9 movements, for 3 intervals
    assert summary["source"]["records_accepted"] == 48
    assert summary["demand"]["records"] == 27
    for raw_output in summary["raw_outputs"].values():
        assert raw_output["exists"]
        assert not raw_output["potentially_partial"]

    saved = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    run = saved["simulation_run"]
    assert run["status"] == "completed"
    assert run["started_at"] is not None
    assert run["mapping_version"] == saved["provenance"]["mapping_version"]
    assert run["demand_sha256"] == saved["demand"]["files"]["demand_file"]["sha256"]
    assert run["route_file_sha256"] == saved["demand"]["files"]["route_file"]["sha256"]

"""Exercise the synthetic source and ingestion together using artificial profiles."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.ingestion.client import SyntheticTrafficClient
from backend.ingestion.service import ingest_synthetic_observations
from traffic_source.synthetic.config import SyntheticSourceConfig
from traffic_source.synthetic.generator import (
    SyntheticTrafficGenerator,
    SyntheticTrafficProfiles,
)
from traffic_source.synthetic.producer import SyntheticTrafficProducer
from traffic_source.synthetic.server import create_app
from traffic_source.synthetic.storage import SyntheticTrafficStorage


def artificial_profiles() -> SyntheticTrafficProfiles:
    """Make 18 reference templates with distinct, deterministic day-type levels."""

    reference_ids = list(range(1001, 1019))
    labels = [f"{(slot + 1) * 15 // 60 % 24:02d}:{(slot + 1) * 15 % 60:02d}"
              for slot in range(96)]
    return SyntheticTrafficProfiles(
        profile_summary={
            "methodology": {"version": 2},
            "overall_volume": {
                "mean_volume_per_detector_per_15_min_interval": 100.0,
            },
            "cross_detector_dependence": {
                "mean_residual_correlation_after_removing_time_of_day_and_day_level": 0.3,
            },
        },
        detector_volume_summary=pd.DataFrame({
            "detector_id": reference_ids, "mean_volume": 100.0,
        }),
        detector_time_of_day_profile=pd.DataFrame([
            {"detector_id": detector, "time_of_day": label,
             "mean_volume": 100.0, "std_volume": 0.0,
             "workday_observation_count": 5}
            for detector in reference_ids for label in labels
        ]),
        overall_time_of_day_profile=pd.DataFrame({
            "time_of_day": labels, "mean_volume": 100.0,
        }),
        day_type_time_profile=pd.DataFrame([
            {"day_type": day_type, "time_of_day": label,
             "day_type_mean_volume": level, "normalized_shape": 1.0,
             "observed_mean_volume": level, "workday_mean_volume": 100.0,
             "smoothing_window_slots": 1 if day_type == "workday" else 5}
            for day_type, level in [("workday", 100.0), ("friday", 200.0), ("saturday", 50.0)]
            for label in labels
        ]),
        temporal_autocorrelation_summary=pd.DataFrame({
            "detector_id": reference_ids, "adjusted_lag1_correlation": 0.5,
        }),
    )


@pytest.mark.parametrize("day,before_level,after_level", [
    (16, 100, 200),  # Thursday -> Friday
    (17, 200, 50),   # Friday -> Saturday
    (18, 50, 100),   # Saturday -> Sunday
])
def test_source_to_ingestion_preserves_midnight_intervals_and_detector_labels(
    tmp_path, monkeypatch, day, before_level, after_level,
):
    profiles = artificial_profiles()
    config = SyntheticSourceConfig()
    midnight = datetime(2026, 10, day, tzinfo=ZoneInfo(config.timezone))
    start = midnight - timedelta(minutes=15)
    end = midnight + timedelta(minutes=15)
    storage = SyntheticTrafficStorage(tmp_path / "synthetic.db")
    storage.initialize()
    producer = SyntheticTrafficProducer(
        SyntheticTrafficGenerator(profiles, config), storage, config,
    )
    generated = producer._generate_window(start, end)
    assert len(generated) == 32
    storage.insert_observations(generated)

    with TestClient(create_app(profiles=profiles, storage=storage, run_producer=False)) as api:
        # Route the real ingestion client's HTTP request into the real ASGI app.
        def get_from_source(url, params, timeout):
            assert url == "http://synthetic-source/observations"
            response = api.get("/observations", params=params)
            return httpx2.Response(
                response.status_code, json=response.json(),
                request=httpx2.Request("GET", url),
            )

        monkeypatch.setattr("backend.ingestion.client.httpx2.get", get_from_source)
        client = SyntheticTrafficClient("http://synthetic-source")
        result = ingest_synthetic_observations(client, start, end)
        repeated = ingest_synthetic_observations(client, start, end)

    assert (result.received_count, result.accepted_count, result.rejected_count) == (32, 32, 0)
    assert len({row.observation_id for row in result.observations}) == 32
    assert result.observations == repeated.observations
    assert storage.get_observation_count() == 32
    expected_labels = {
        "13": "SYN-EB-L4-R-SLP", "14": "SYN-SB-L4-R-SLP",
        "15": "SYN-NB-L3-R-BYP", "16": "SYN-NB-L4-R-BYP",
    }
    for timestamp, expected_level in [(midnight, before_level), (end, after_level)]:
        rows = [row for row in result.observations if row.interval_end == timestamp]
        assert {row.detector_id for row in rows} == {str(i) for i in range(1, 17)}
        assert all(row.interval_start == timestamp - timedelta(minutes=15) for row in rows)
        assert all(row.vehicle_count == expected_level for row in rows)
        assert all(row.description == expected_labels[row.detector_id]
                   for row in rows if row.detector_id in expected_labels)
        assert all(row.average_speed_kmh is None and row.travel_time_s is None for row in rows)

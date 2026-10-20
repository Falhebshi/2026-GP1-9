"""Run the synthetic source, ingestion and demand transformation together."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.demand.service import build_simulation_demand
from backend.ingestion.client import SyntheticTrafficClient
from backend.ingestion.service import ingest_synthetic_observations
from jaadah.models.traffic import ImputationMethod
from traffic_source.synthetic.config import SyntheticSourceConfig
from traffic_source.synthetic.generator import (
    SyntheticTrafficGenerator,
    SyntheticTrafficProfiles,
)
from traffic_source.synthetic.producer import SyntheticTrafficProducer
from traffic_source.synthetic.server import create_app
from traffic_source.synthetic.storage import SyntheticTrafficStorage


TIMEZONE = ZoneInfo(SyntheticSourceConfig().timezone)

# A Sunday morning, so a workday interval
BATCH_START = datetime(2026, 10, 18, 8, 0, tzinfo=TIMEZONE)
BATCH_END = BATCH_START + timedelta(minutes=15)
HISTORY_START = BATCH_START - timedelta(days=7)

# An 08:00-09:00 analysis with 15 minutes of warm-up and clearance
WINDOW_START = BATCH_START - timedelta(minutes=15)
WINDOW_END = BATCH_START + timedelta(minutes=75)


def artificial_profiles() -> SyntheticTrafficProfiles:
    """
    Return artificial reference profiles with flat, deterministic levels:
    100 vehicles per interval on workdays, 200 on Fridays and 50 on
    Saturdays (the same profiles as the ingestion integration tests).
    """

    reference_ids = list(range(1001, 1019))
    labels = [
        f"{(slot + 1) * 15 // 60 % 24:02d}:{(slot + 1) * 15 % 60:02d}"
        for slot in range(96)
    ]

    return SyntheticTrafficProfiles(
        profile_summary={
            "methodology": {"version": 2},
            "overall_volume": {
                "mean_volume_per_detector_per_15_min_interval": 100.0,
            },
            "cross_detector_dependence": {
                "mean_residual_correlation_after_removing_time_of_day"
                "_and_day_level": 0.3,
            },
        },
        detector_volume_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "mean_volume": 100.0,
            }
        ),
        detector_time_of_day_profile=pd.DataFrame(
            [
                {
                    "detector_id": detector,
                    "time_of_day": label,
                    "mean_volume": 100.0,
                    "std_volume": 0.0,
                    "workday_observation_count": 5,
                }
                for detector in reference_ids
                for label in labels
            ]
        ),
        overall_time_of_day_profile=pd.DataFrame(
            {
                "time_of_day": labels,
                "mean_volume": 100.0,
            }
        ),
        day_type_time_profile=pd.DataFrame(
            [
                {
                    "day_type": day_type,
                    "time_of_day": label,
                    "day_type_mean_volume": level,
                    "normalized_shape": 1.0,
                    "observed_mean_volume": level,
                    "workday_mean_volume": 100.0,
                    "smoothing_window_slots": (
                        1 if day_type == "workday" else 5
                    ),
                }
                for day_type, level in [
                    ("workday", 100.0),
                    ("friday", 200.0),
                    ("saturday", 50.0),
                ]
                for label in labels
            ]
        ),
        temporal_autocorrelation_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "adjusted_lag1_correlation": 0.5,
            }
        ),
    )


@pytest.fixture
def client(tmp_path, monkeypatch) -> SyntheticTrafficClient:
    """
    Return an ingestion client connected to a real synthetic source
    holding one week of traffic before the batch, and the batch and the
    08:00-09:00 window with its warm-up and clearance intervals.
    """

    profiles = artificial_profiles()
    config = SyntheticSourceConfig()
    storage = SyntheticTrafficStorage(tmp_path / "synthetic.db")
    storage.initialize()
    producer = SyntheticTrafficProducer(
        SyntheticTrafficGenerator(profiles, config),
        storage,
        config,
    )
    storage.insert_observations(
        producer._generate_window(HISTORY_START, WINDOW_END)
    )

    with TestClient(
        create_app(
            profiles=profiles,
            storage=storage,
            run_producer=False,
        )
    ) as api:

        def get_from_source(url, params, timeout):
            response = api.get("/observations", params=params)

            return httpx2.Response(
                response.status_code,
                json=response.json(),
                request=httpx2.Request("GET", url),
            )

        monkeypatch.setattr(
            "backend.ingestion.client.httpx2.get",
            get_from_source,
        )

        yield SyntheticTrafficClient("http://synthetic-source")


def test_source_batch_becomes_demand_for_every_detected_movement(
    client,
) -> None:
    ingestion = ingest_synthetic_observations(
        client=client,
        start=BATCH_START,
        end=BATCH_END,
    )

    result = build_simulation_demand(
        observations=ingestion.observations,
    )

    assert ingestion.accepted_count == 16
    assert result.errors == []
    assert len(result.demands) == 9
    assert sum(
        demand.vehicle_count
        for demand in result.demands
    ) == sum(
        observation.vehicle_count
        for observation in ingestion.observations
    )
    assert sum(
        demand.is_allocated
        for demand in result.demands
    ) == 4


def test_missing_source_detector_is_estimated_from_ingested_history(
    client,
) -> None:
    batch = ingest_synthetic_observations(
        client=client,
        start=BATCH_START,
        end=BATCH_END,
    )
    history = ingest_synthetic_observations(
        client=client,
        start=HISTORY_START,
        end=BATCH_START,
    )

    result = build_simulation_demand(
        observations=[
            observation
            for observation in batch.observations
            if observation.detector_id != "6"
        ],
        history=history.observations,
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_N_E"
    )

    assert result.errors == []
    assert demand.vehicle_count == 100 + 100 + 100
    assert [
        (detector.detector_id, detector.method)
        for detector in demand.imputed_detectors
    ] == [("6", ImputationMethod.NEIGHBOUR_REGRESSION)]


def test_ingested_window_gets_demand_for_every_movement_and_interval(
    client,
) -> None:
    ingestion = ingest_synthetic_observations(
        client=client,
        start=WINDOW_START,
        end=WINDOW_END,
    )

    result = build_simulation_demand(
        observations=ingestion.observations,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )

    assert ingestion.accepted_count == 6 * 16
    assert result.errors == []
    assert len(result.demands) == 6 * 9
    assert {
        demand.interval_start
        for demand in result.demands
    } == {
        WINDOW_START + step * timedelta(minutes=15)
        for step in range(6)
    }

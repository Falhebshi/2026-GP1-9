from datetime import datetime
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import traffic_source.synthetic.server as server_module
from traffic_source.synthetic.generator import (
    SyntheticDetectorObservation,
)
from traffic_source.synthetic.server import (
    create_app,
)
from traffic_source.synthetic.storage import (
    SyntheticTrafficStorage,
)


RIYADH = ZoneInfo("Asia/Riyadh")


@pytest.fixture
def storage(tmp_path) -> SyntheticTrafficStorage:
    result = SyntheticTrafficStorage(
        database_path=(
            tmp_path
            / "synthetic_traffic.db"
        )
    )

    result.initialize()

    return result


def make_observation(
    detector_id: int = 1,
    timestamp: datetime | None = None,
    volume: int = 50,
    description: str = "SYN-EB-L1",
) -> SyntheticDetectorObservation:
    """Create one stored observation for API tests."""

    if timestamp is None:
        timestamp = datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        )

    return SyntheticDetectorObservation(
        site_id=9,
        detector_id=detector_id,
        timestamp=timestamp,
        volume=volume,
        description=description,
    )


def make_test_app(
    storage: SyntheticTrafficStorage,
):
    return create_app(
        storage=storage,
        run_producer=False,
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def test_startup_initializes_database_and_metadata(
    tmp_path,
):
    database_path = (
        tmp_path
        / "nested"
        / "synthetic_traffic.db"
    )

    source_storage = SyntheticTrafficStorage(
        database_path=database_path,
    )

    assert not database_path.exists()

    app = create_app(
        storage=source_storage,
        run_producer=False,
    )

    with TestClient(app):
        pass

    assert database_path.exists()

    with source_storage._connect() as connection:
        metadata_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM source_metadata
            """
        ).fetchone()[0]

    assert metadata_count == 1


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_ok_for_empty_source(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "source": "synthetic",
        "latest_available_timestamp": None,
    }


def test_health_reports_latest_available_timestamp(
    storage,
):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        30,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        [
            make_observation(
                timestamp=timestamp,
            )
        ]
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    assert (
        response.json()[
            "latest_available_timestamp"
        ]
        == timestamp.isoformat()
    )


# ---------------------------------------------------------------------------
# Observations endpoint
# ---------------------------------------------------------------------------


def test_observations_returns_stored_rows(
    storage,
):
    first_timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    second_timestamp = datetime(
        2026,
        10,
        14,
        8,
        30,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        [
            make_observation(
                detector_id=1,
                timestamp=first_timestamp,
                volume=51,
                description="SYN-EB-L1",
            ),
            make_observation(
                detector_id=2,
                timestamp=first_timestamp,
                volume=52,
                description="SYN-EB-L2",
            ),
            make_observation(
                detector_id=1,
                timestamp=second_timestamp,
                volume=61,
                description="SYN-EB-L1",
            ),
        ]
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:30:00+03:00"
                ),
            },
        )

    assert response.status_code == 200

    body = response.json()

    observations = body["observations"]

    assert len(observations) == 3

    assert observations == [
        {
            "Site ID": 9,
            "detector_id": 1,
            "Date  & Time": (
                "2026-10-14T08:15:00+03:00"
            ),
            "volume": 51,
            "description": "SYN-EB-L1",
        },
        {
            "Site ID": 9,
            "detector_id": 2,
            "Date  & Time": (
                "2026-10-14T08:15:00+03:00"
            ),
            "volume": 52,
            "description": "SYN-EB-L2",
        },
        {
            "Site ID": 9,
            "detector_id": 1,
            "Date  & Time": (
                "2026-10-14T08:30:00+03:00"
            ),
            "volume": 61,
            "description": "SYN-EB-L1",
        },
    ]


def test_observations_get_does_not_generate_data(
    storage,
):
    storage.insert_observations(
        [
            make_observation(
                timestamp=datetime(
                    2026,
                    10,
                    14,
                    8,
                    15,
                    tzinfo=RIYADH,
                )
            )
        ]
    )

    count_before = (
        storage.get_observation_count()
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T09:00:00+03:00"
                ),
            },
        )

    assert response.status_code == 200

    count_after = (
        storage.get_observation_count()
    )

    assert count_after == count_before
    assert count_after == 1


def test_observations_returns_empty_list_when_no_data(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T09:00:00+03:00"
                ),
            },
        )

    assert response.status_code == 200
    assert response.json()["observations"] == []


def test_observations_returns_only_currently_available_data(
    storage,
):
    available_timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        [
            make_observation(
                timestamp=available_timestamp,
            )
        ]
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:45:00+03:00"
                ),
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert len(body["observations"]) == 1

    assert (
        body["latest_available_timestamp"]
        == available_timestamp.isoformat()
    )


def test_observations_can_filter_detector_ids(
    storage,
):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        [
            make_observation(
                detector_id=1,
                timestamp=timestamp,
            ),
            make_observation(
                detector_id=2,
                timestamp=timestamp,
            ),
            make_observation(
                detector_id=3,
                timestamp=timestamp,
            ),
        ]
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params=[
                (
                    "start",
                    "2026-10-14T08:00:00+03:00",
                ),
                (
                    "end",
                    "2026-10-14T08:15:00+03:00",
                ),
                ("detector_id", "1"),
                ("detector_id", "3"),
            ],
        )

    assert response.status_code == 200

    detector_ids = [
        item["detector_id"]
        for item
        in response.json()["observations"]
    ]

    assert detector_ids == [1, 3]


def test_unknown_detector_returns_no_observations(
    storage,
):
    storage.insert_observations(
        [make_observation()]
    )

    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params=[
                (
                    "start",
                    "2026-10-14T08:00:00+03:00",
                ),
                (
                    "end",
                    "2026-10-14T08:15:00+03:00",
                ),
                ("detector_id", "999"),
            ],
        )

    assert response.status_code == 200
    assert response.json()["observations"] == []


# ---------------------------------------------------------------------------
# Time normalization
# ---------------------------------------------------------------------------


def test_naive_api_times_are_interpreted_as_riyadh_time(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00"
                ),
                "end": (
                    "2026-10-14T08:15:00"
                ),
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["start"]
        == "2026-10-14T08:00:00+03:00"
    )

    assert (
        body["end"]
        == "2026-10-14T08:15:00+03:00"
    )


def test_utc_api_times_are_converted_to_riyadh_time(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T05:00:00+00:00"
                ),
                "end": (
                    "2026-10-14T05:15:00+00:00"
                ),
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["start"]
        == "2026-10-14T08:00:00+03:00"
    )

    assert (
        body["end"]
        == "2026-10-14T08:15:00+03:00"
    )


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


def test_observations_rejects_end_equal_to_start(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:00:00+03:00"
                ),
            },
        )

    assert response.status_code == 400

    assert (
        response.json()["detail"]
        == "end must be later than start"
    )


def test_observations_rejects_end_before_start(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T09:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:00:00+03:00"
                ),
            },
        )

    assert response.status_code == 400


def test_observations_rejects_misaligned_start(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:07:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:30:00+03:00"
                ),
            },
        )

    assert response.status_code == 400

    assert (
        "start must be aligned"
        in response.json()["detail"]
    )


def test_observations_rejects_misaligned_end(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:22:00+03:00"
                ),
            },
        )

    assert response.status_code == 400

    assert (
        "end must be aligned"
        in response.json()["detail"]
    )


def test_observations_rejects_nonzero_seconds(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:01+03:00"
                ),
                "end": (
                    "2026-10-14T08:15:00+03:00"
                ),
            },
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Response metadata
# ---------------------------------------------------------------------------


def test_observations_reports_source_configuration(
    storage,
):
    app = make_test_app(storage)

    with TestClient(app) as client:
        response = client.get(
            "/observations",
            params={
                "start": (
                    "2026-10-14T08:00:00+03:00"
                ),
                "end": (
                    "2026-10-14T08:15:00+03:00"
                ),
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["source"] == "synthetic"
    assert body["scenario"] == "normal"
    assert body["seed"] == 42
    assert body["interval_minutes"] == 15
    assert body["timezone"] == "Asia/Riyadh"


# ---------------------------------------------------------------------------
# Detectors endpoint
# ---------------------------------------------------------------------------


def test_detectors_returns_target_detector_ids(
    storage,
):
    app = create_app(
        storage=storage,
        run_producer=False,
    )

    with TestClient(app) as client:
        response = client.get(
            "/detectors"
        )

    assert response.status_code == 200

    assert response.json() == {
        "site_id": 9,
        "count": 16,
        "detector_ids": list(
            range(1, 17)
        ),
    }



# ---------------------------------------------------------------------------
# Background producer lifecycle
# ---------------------------------------------------------------------------


def test_server_starts_and_stops_background_producer(
    storage,
    monkeypatch,
):
    producer_started = Event()
    producer_stopped = Event()

    class FakeGenerator:
        def __init__(
            self,
            profiles,
            config,
        ):
            pass

    class FakeProducer:
        def __init__(
            self,
            generator,
            storage,
            config,
        ):
            pass

        def run_forever(
            self,
            stop_event,
        ):
            producer_started.set()

            stop_event.wait(
                timeout=2.0
            )

            if stop_event.is_set():
                producer_stopped.set()

    monkeypatch.setattr(
        server_module,
        "SyntheticTrafficGenerator",
        FakeGenerator,
    )

    monkeypatch.setattr(
        server_module,
        "SyntheticTrafficProducer",
        FakeProducer,
    )

    app = create_app(
        profiles=object(),
        storage=storage,
        run_producer=True,
    )

    with TestClient(app):
        assert producer_started.wait(
            timeout=1.0
        )

    assert producer_stopped.wait(
        timeout=1.0
    )
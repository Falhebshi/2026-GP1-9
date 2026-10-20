import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from traffic_source.synthetic.config import (
    SyntheticSourceConfig,
)

from traffic_source.synthetic.generator import (
    SyntheticDetectorObservation,
)

from traffic_source.synthetic.storage import (
    SyntheticTrafficStorage,
)

RIYADH = ZoneInfo("Asia/Riyadh")


def make_observation(
    detector_id: int = 1,
    timestamp: datetime | None = None,
    volume: int = 50,
    site_id: int = 9,
    description: str = "SYN-EB-L1",
) -> SyntheticDetectorObservation:
    """Create one valid synthetic observation for storage tests."""

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
        site_id=site_id,
        detector_id=detector_id,
        timestamp=timestamp,
        volume=volume,
        description=description,
    )


@pytest.fixture
def storage(tmp_path) -> SyntheticTrafficStorage:
    """Create an initialized temporary traffic database."""

    database_path = tmp_path / "synthetic_traffic.db"

    result = SyntheticTrafficStorage(
        database_path=database_path,
    )
    result.initialize()

    return result


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------


def test_initialize_creates_parent_directory_and_database(tmp_path):
    database_path = (
        tmp_path
        / "nested"
        / "synthetic_traffic"
        / "synthetic_traffic.db"
    )

    storage = SyntheticTrafficStorage(
        database_path=database_path,
    )

    assert not database_path.exists()

    storage.initialize()

    assert database_path.parent.exists()
    assert database_path.exists()


def test_initialize_creates_required_tables(tmp_path):
    database_path = tmp_path / "traffic.db"

    storage = SyntheticTrafficStorage(
        database_path=database_path,
    )
    storage.initialize()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    table_names = {
        row[0]
        for row in rows
    }

    assert "observations" in table_names
    assert "source_metadata" in table_names


def test_initialize_creates_timestamp_index(tmp_path):
    database_path = tmp_path / "traffic.db"

    storage = SyntheticTrafficStorage(
        database_path=database_path,
    )
    storage.initialize()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
            """
        ).fetchall()

    index_names = {
        row[0]
        for row in rows
    }

    assert "idx_observations_timestamp" in index_names


def test_initialize_is_safe_to_call_more_than_once(storage):
    observation = make_observation()

    storage.insert_observations([observation])

    storage.initialize()
    storage.initialize()

    assert storage.get_observation_count() == 1
    assert storage.get_latest_timestamp() == observation.timestamp


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


def test_new_database_stores_source_metadata(storage):
    config = SyntheticSourceConfig()

    storage.ensure_source_metadata(config)

    with storage._connect() as connection:
        row = connection.execute(
            """
            SELECT
                seed,
                scenario,
                variation_scale,
                interval_minutes,
                timezone
            FROM source_metadata
            WHERE id = 1
            """
        ).fetchone()

    assert row == (
        config.seed,
        config.scenario,
        config.variation_scale,
        config.interval_minutes,
        config.timezone,
    )


def test_matching_source_metadata_is_accepted(storage):
    config = SyntheticSourceConfig()

    storage.ensure_source_metadata(config)

    storage.ensure_source_metadata(config)


def test_source_metadata_is_not_duplicated(storage):
    config = SyntheticSourceConfig()

    storage.ensure_source_metadata(config)
    storage.ensure_source_metadata(config)

    with storage._connect() as connection:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM source_metadata
            """
        ).fetchone()[0]

    assert count == 1


@pytest.mark.parametrize(
    "changed_config",
    [
        replace(
            SyntheticSourceConfig(),
            seed=99,
        ),
        replace(
            SyntheticSourceConfig(),
            scenario="high",
        ),
        replace(
            SyntheticSourceConfig(),
            variation_scale=2.0,
        ),
        replace(
            SyntheticSourceConfig(),
            interval_minutes=30,
        ),
        replace(
            SyntheticSourceConfig(),
            timezone="UTC",
        ),
    ],
)
def test_changed_source_configuration_is_rejected(
    storage,
    changed_config,
):
    original_config = SyntheticSourceConfig()

    storage.ensure_source_metadata(
        original_config,
    )

    with pytest.raises(
        ValueError,
        match="different source configuration",
    ):
        storage.ensure_source_metadata(
            changed_config,
        )


# ---------------------------------------------------------------------------
# Observation insertion
# ---------------------------------------------------------------------------


def test_empty_observation_batch_does_nothing(storage):
    storage.insert_observations([])

    assert storage.get_observation_count() == 0


def test_single_observation_can_be_inserted(storage):
    observation = make_observation()

    storage.insert_observations(
        [observation]
    )

    assert storage.get_observation_count() == 1


def test_full_detector_batch_can_be_inserted(storage):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    observations = [
        make_observation(
            detector_id=detector_id,
            timestamp=timestamp,
            volume=40 + detector_id,
            description=f"SYN-DETECTOR-{detector_id}",
        )
        for detector_id in range(1, 13)
    ]

    storage.insert_observations(
        observations
    )

    assert storage.get_observation_count() == 12


def test_duplicate_observation_identity_is_rejected(storage):
    observation = make_observation()

    storage.insert_observations(
        [observation]
    )

    duplicate = make_observation(
        detector_id=observation.detector_id,
        timestamp=observation.timestamp,
        volume=999,
        site_id=observation.site_id,
        description=observation.description,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
    ):
        storage.insert_observations(
            [duplicate]
        )

    assert storage.get_observation_count() == 1


def test_failed_batch_is_rolled_back(storage):
    existing = make_observation(
        detector_id=2,
    )

    storage.insert_observations(
        [existing]
    )

    new_observation = make_observation(
        detector_id=1,
    )

    duplicate = make_observation(
        detector_id=2,
        volume=999,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
    ):
        storage.insert_observations(
            [
                new_observation,
                duplicate,
            ]
        )

    assert storage.get_observation_count() == 1

    retrieved = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
    )

    assert [
        observation.detector_id
        for observation in retrieved
    ] == [2]


def test_same_detector_at_different_timestamp_is_allowed(storage):
    first = make_observation(
        detector_id=4,
        timestamp=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
    )

    second = make_observation(
        detector_id=4,
        timestamp=datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
    )

    storage.insert_observations(
        [first, second]
    )

    assert storage.get_observation_count() == 2


def test_same_timestamp_for_different_detectors_is_allowed(storage):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    first = make_observation(
        detector_id=1,
        timestamp=timestamp,
    )

    second = make_observation(
        detector_id=2,
        timestamp=timestamp,
    )

    storage.insert_observations(
        [first, second]
    )

    assert storage.get_observation_count() == 2


def test_same_detector_and_clock_time_on_different_dates_is_allowed(
    storage,
):
    first = make_observation(
        detector_id=4,
        timestamp=datetime(
            2026,
            10,
            14,
            6,
            0,
            tzinfo=RIYADH,
        ),
    )

    second = make_observation(
        detector_id=4,
        timestamp=datetime(
            2026,
            10,
            15,
            6,
            0,
            tzinfo=RIYADH,
        ),
    )

    storage.insert_observations(
        [first, second]
    )

    assert storage.get_observation_count() == 2


def test_same_detector_timestamp_for_different_sites_is_allowed(storage):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    first = make_observation(
        site_id=9,
        detector_id=1,
        timestamp=timestamp,
    )

    second = make_observation(
        site_id=10,
        detector_id=1,
        timestamp=timestamp,
    )

    storage.insert_observations(
        [first, second]
    )

    assert storage.get_observation_count() == 2


def test_naive_observation_timestamp_is_rejected(storage):
    observation = make_observation(
        timestamp=datetime(
            2026,
            10,
            14,
            8,
            15,
        ),
    )

    with pytest.raises(
        ValueError,
        match="must include a timezone",
    ):
        storage.insert_observations(
            [observation]
        )

    assert storage.get_observation_count() == 0


# ---------------------------------------------------------------------------
# Latest timestamp
# ---------------------------------------------------------------------------


def test_latest_timestamp_is_none_when_database_is_empty(storage):
    assert storage.get_latest_timestamp() is None


def test_latest_timestamp_returns_newest_stored_time(storage):
    timestamps = [
        datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            45,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
    ]

    observations = [
        make_observation(
            detector_id=index,
            timestamp=timestamp,
        )
        for index, timestamp in enumerate(
            timestamps,
            start=1,
        )
    ]

    storage.insert_observations(
        observations
    )

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        14,
        8,
        45,
        tzinfo=RIYADH,
    )


def test_latest_timestamp_works_across_dates(storage):
    observations = [
        make_observation(
            detector_id=1,
            timestamp=datetime(
                2026,
                10,
                14,
                23,
                45,
                tzinfo=RIYADH,
            ),
        ),
        make_observation(
            detector_id=1,
            timestamp=datetime(
                2026,
                10,
                15,
                0,
                0,
                tzinfo=RIYADH,
            ),
        ),
    ]

    storage.insert_observations(
        observations
    )

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        15,
        0,
        0,
        tzinfo=RIYADH,
    )


# ---------------------------------------------------------------------------
# Observation retrieval
# ---------------------------------------------------------------------------


def test_get_observations_returns_empty_list_when_no_data(storage):
    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
    )

    assert result == []


def test_get_observations_uses_physical_coverage_semantics(storage):
    timestamps = [
        datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            45,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            9,
            15,
            tzinfo=RIYADH,
        ),
    ]

    storage.insert_observations(
        [
            make_observation(
                detector_id=1,
                timestamp=timestamp,
            )
            for timestamp in timestamps
        ]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
    )

    assert [
        observation.timestamp
        for observation in result
    ] == [
        datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            8,
            45,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
    ]


def test_get_observations_returns_complete_fields(storage):
    original = make_observation(
        site_id=9,
        detector_id=4,
        timestamp=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        volume=53,
        description="SYN-SB-L1",
    )

    storage.insert_observations(
        [original]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
    )

    assert result == [original]


def test_get_observations_can_filter_detector_ids(storage):
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

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        detector_ids=[1, 3],
    )

    assert [
        observation.detector_id
        for observation in result
    ] == [1, 3]


def test_detector_filter_removes_duplicate_ids(storage):
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
        ]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        detector_ids=[2, 2, 2],
    )

    assert len(result) == 1
    assert result[0].detector_id == 2


def test_empty_detector_filter_returns_empty_list(storage):
    storage.insert_observations(
        [make_observation()]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        detector_ids=[],
    )

    assert result == []


def test_unknown_detector_filter_returns_empty_list(storage):
    storage.insert_observations(
        [make_observation(detector_id=1)]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            15,
            tzinfo=RIYADH,
        ),
        detector_ids=[999],
    )

    assert result == []


def test_get_observations_orders_by_timestamp_then_detector(storage):
    observations = [
        make_observation(
            detector_id=3,
            timestamp=datetime(
                2026,
                10,
                14,
                8,
                30,
                tzinfo=RIYADH,
            ),
        ),
        make_observation(
            detector_id=2,
            timestamp=datetime(
                2026,
                10,
                14,
                8,
                15,
                tzinfo=RIYADH,
            ),
        ),
        make_observation(
            detector_id=1,
            timestamp=datetime(
                2026,
                10,
                14,
                8,
                30,
                tzinfo=RIYADH,
            ),
        ),
        make_observation(
            detector_id=1,
            timestamp=datetime(
                2026,
                10,
                14,
                8,
                15,
                tzinfo=RIYADH,
            ),
        ),
    ]

    storage.insert_observations(
        observations
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
    )

    assert [
        (
            observation.timestamp,
            observation.detector_id,
        )
        for observation in result
    ] == [
        (
            datetime(
                2026,
                10,
                14,
                8,
                15,
                tzinfo=RIYADH,
            ),
            1,
        ),
        (
            datetime(
                2026,
                10,
                14,
                8,
                15,
                tzinfo=RIYADH,
            ),
            2,
        ),
        (
            datetime(
                2026,
                10,
                14,
                8,
                30,
                tzinfo=RIYADH,
            ),
            1,
        ),
        (
            datetime(
                2026,
                10,
                14,
                8,
                30,
                tzinfo=RIYADH,
            ),
            3,
        ),
    ]


def test_get_observations_handles_midnight_boundary(storage):
    storage.insert_observations(
        [
            make_observation(
                detector_id=1,
                timestamp=datetime(
                    2026,
                    10,
                    14,
                    23,
                    45,
                    tzinfo=RIYADH,
                ),
            ),
            make_observation(
                detector_id=1,
                timestamp=datetime(
                    2026,
                    10,
                    15,
                    0,
                    0,
                    tzinfo=RIYADH,
                ),
            ),
            make_observation(
                detector_id=1,
                timestamp=datetime(
                    2026,
                    10,
                    15,
                    0,
                    15,
                    tzinfo=RIYADH,
                ),
            ),
        ]
    )

    result = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            23,
            45,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            15,
            0,
            15,
            tzinfo=RIYADH,
        ),
    )

    assert [
        observation.timestamp
        for observation in result
    ] == [
        datetime(
            2026,
            10,
            15,
            0,
            0,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            15,
            0,
            15,
            tzinfo=RIYADH,
        ),
    ]


def test_get_observations_rejects_end_equal_to_start(storage):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        0,
        tzinfo=RIYADH,
    )

    with pytest.raises(
        ValueError,
        match="end must be later than start",
    ):
        storage.get_observations(
            start=timestamp,
            end=timestamp,
        )


def test_get_observations_rejects_end_before_start(storage):
    with pytest.raises(
        ValueError,
        match="end must be later than start",
    ):
        storage.get_observations(
            start=datetime(
                2026,
                10,
                14,
                9,
                0,
                tzinfo=RIYADH,
            ),
            end=datetime(
                2026,
                10,
                14,
                8,
                0,
                tzinfo=RIYADH,
            ),
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (
            datetime(
                2026,
                10,
                14,
                8,
                0,
            ),
            datetime(
                2026,
                10,
                14,
                9,
                0,
                tzinfo=RIYADH,
            ),
        ),
        (
            datetime(
                2026,
                10,
                14,
                8,
                0,
                tzinfo=RIYADH,
            ),
            datetime(
                2026,
                10,
                14,
                9,
                0,
            ),
        ),
    ],
)
def test_get_observations_rejects_naive_query_timestamps(
    storage,
    start,
    end,
):
    with pytest.raises(
        ValueError,
        match="must include a timezone",
    ):
        storage.get_observations(
            start=start,
            end=end,
        )


# ---------------------------------------------------------------------------
# Observation count
# ---------------------------------------------------------------------------


def test_observation_count_is_zero_for_empty_database(storage):
    assert storage.get_observation_count() == 0


def test_observation_count_matches_stored_rows(storage):
    timestamp = datetime(
        2026,
        10,
        14,
        8,
        15,
        tzinfo=RIYADH,
    )

    observations = [
        make_observation(
            detector_id=detector_id,
            timestamp=timestamp,
        )
        for detector_id in range(1, 13)
    ]

    storage.insert_observations(
        observations
    )

    assert storage.get_observation_count() == 12
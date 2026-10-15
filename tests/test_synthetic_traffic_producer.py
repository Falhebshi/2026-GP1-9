from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from threading import Event
import pytest

from traffic_source.synthetic.config import (
    INITIAL_HISTORY_DAYS,
    SyntheticSourceConfig,
)
from traffic_source.synthetic.generator import (
    SyntheticDetectorObservation,
)
from traffic_source.synthetic.producer import (
    SyntheticTrafficProducer,
    latest_completed_interval,
    next_interval_boundary,

)
from traffic_source.synthetic.storage import (
    SyntheticTrafficStorage,
)


RIYADH = ZoneInfo("Asia/Riyadh")


class FakeStatefulGenerator:
    """
    Small deterministic generator used to test producer behavior.

    Its values depend on previous timestamps, so the tests can verify that
    rebuilding a day from midnight preserves reproducible later values.
    """

    def __init__(self) -> None:
        self.state = 0
        self.reset_seeds: list[int | None] = []
        self.generated_timestamps: list[datetime] = []

    def reset(
        self,
        seed: int | None = None,
    ) -> None:
        self.reset_seeds.append(seed)

        if seed is None:
            self.state = 0
        else:
            self.state = seed % 997

    def generate_timestamp(
        self,
        timestamp: datetime,
    ) -> list[SyntheticDetectorObservation]:
        self.generated_timestamps.append(timestamp)

        minutes_since_midnight = (
            timestamp.hour * 60
            + timestamp.minute
        )

        self.state = (
            self.state * 37
            + minutes_since_midnight
            + 17
        ) % 10_000

        return [
            SyntheticDetectorObservation(
                site_id=9,
                detector_id=detector_id,
                timestamp=timestamp,
                volume=self.state + detector_id,
                description=f"SYN-{detector_id}",
            )
            for detector_id in range(1, 13)
        ]


@pytest.fixture
def config() -> SyntheticSourceConfig:
    return SyntheticSourceConfig()


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


def make_batch(
    timestamp: datetime,
) -> list[SyntheticDetectorObservation]:
    return [
        SyntheticDetectorObservation(
            site_id=9,
            detector_id=detector_id,
            timestamp=timestamp,
            volume=40 + detector_id,
            description=f"SYN-{detector_id}",
        )
        for detector_id in range(1, 13)
    ]


def make_producer(
    storage: SyntheticTrafficStorage,
    config: SyntheticSourceConfig,
) -> tuple[
    SyntheticTrafficProducer,
    FakeStatefulGenerator,
]:
    generator = FakeStatefulGenerator()

    producer = SyntheticTrafficProducer(
        generator=generator,
        storage=storage,
        config=config,
    )

    return producer, generator


# ---------------------------------------------------------------------------
# Latest completed interval
# ---------------------------------------------------------------------------


def test_latest_completed_interval_rounds_down(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        7,
        42,
        500000,
        tzinfo=RIYADH,
    )

    result = latest_completed_interval(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )


def test_latest_completed_interval_at_exact_boundary(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        15,
        0,
        tzinfo=RIYADH,
    )

    result = latest_completed_interval(
        now=now,
        config=config,
    )

    assert result == now


@pytest.mark.parametrize(
    ("minute", "expected_minute"),
    [
        (0, 0),
        (1, 0),
        (14, 0),
        (15, 15),
        (16, 15),
        (29, 15),
        (30, 30),
        (44, 30),
        (45, 45),
        (59, 45),
    ],
)
def test_latest_completed_interval_quarter_hour_boundaries(
    config,
    minute,
    expected_minute,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        minute,
        tzinfo=RIYADH,
    )

    result = latest_completed_interval(
        now=now,
        config=config,
    )

    assert result.minute == expected_minute
    assert result.second == 0
    assert result.microsecond == 0


def test_latest_completed_interval_normalizes_other_timezone(
    config,
):
    now_utc = datetime(
        2026,
        10,
        14,
        14,
        7,
        tzinfo=timezone.utc,
    )

    result = latest_completed_interval(
        now=now_utc,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )


def test_latest_completed_interval_treats_naive_time_as_source_timezone(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        7,
    )

    result = latest_completed_interval(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )


# ---------------------------------------------------------------------------
# Initial history
# ---------------------------------------------------------------------------


def test_empty_database_bootstraps_expected_history(
    storage,
    config,
):
    producer, _ = make_producer(
        storage,
        config,
    )

    now = datetime(
        2026,
        10,
        14,
        17,
        7,
        tzinfo=RIYADH,
    )

    inserted = producer.synchronize(
        now=now,
    )

    intervals_per_day = (
        24 * 60
        // config.interval_minutes
    )

    expected_rows = (
        INITIAL_HISTORY_DAYS
        * intervals_per_day
        * 12
    )

    assert inserted == expected_rows
    assert (
        storage.get_observation_count()
        == expected_rows
    )

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )


def test_initial_history_starts_after_coverage_start(
    storage,
    config,
):
    producer, _ = make_producer(
        storage,
        config,
    )

    cutoff = datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )

    producer.synchronize(
        now=cutoff,
    )

    coverage_start = (
        cutoff
        - timedelta(
            days=INITIAL_HISTORY_DAYS
        )
    )

    first_timestamp = (
        coverage_start
        + timedelta(
            minutes=config.interval_minutes
        )
    )

    observations = storage.get_observations(
        start=coverage_start,
        end=first_timestamp,
    )

    assert len(observations) == 12

    assert {
        observation.timestamp
        for observation in observations
    } == {first_timestamp}


# ---------------------------------------------------------------------------
# Gap recovery
# ---------------------------------------------------------------------------


def test_existing_database_fills_only_missing_intervals(
    storage,
    config,
):
    storage.insert_observations(
        make_batch(
            datetime(
                2026,
                10,
                14,
                16,
                30,
                tzinfo=RIYADH,
            )
        )
    )

    producer, _ = make_producer(
        storage,
        config,
    )

    inserted = producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            17,
            7,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 24

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )

    observations = storage.get_observations(
        start=datetime(
            2026,
            10,
            14,
            16,
            30,
            tzinfo=RIYADH,
        ),
        end=datetime(
            2026,
            10,
            14,
            17,
            0,
            tzinfo=RIYADH,
        ),
    )

    assert {
        observation.timestamp
        for observation in observations
    } == {
        datetime(
            2026,
            10,
            14,
            16,
            45,
            tzinfo=RIYADH,
        ),
        datetime(
            2026,
            10,
            14,
            17,
            0,
            tzinfo=RIYADH,
        ),
    }


def test_synchronize_does_nothing_when_already_caught_up(
    storage,
    config,
):
    timestamp = datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        make_batch(timestamp)
    )

    producer, generator = make_producer(
        storage,
        config,
    )

    inserted = producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            17,
            7,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 0
    assert storage.get_observation_count() == 12
    assert generator.generated_timestamps == []


def test_repeated_synchronization_is_idempotent(
    storage,
    config,
):
    producer, _ = make_producer(
        storage,
        config,
    )

    now = datetime(
        2026,
        10,
        14,
        17,
        7,
        tzinfo=RIYADH,
    )

    first_inserted = producer.synchronize(
        now=now,
    )

    count_after_first = (
        storage.get_observation_count()
    )

    second_inserted = producer.synchronize(
        now=now,
    )

    assert first_inserted > 0
    assert second_inserted == 0

    assert (
        storage.get_observation_count()
        == count_after_first
    )


# ---------------------------------------------------------------------------
# Exact boundary behavior
# ---------------------------------------------------------------------------


def test_exact_boundary_generates_newly_completed_interval(
    storage,
    config,
):
    previous = datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        make_batch(previous)
    )

    producer, _ = make_producer(
        storage,
        config,
    )

    inserted = producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            17,
            15,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 12

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        14,
        17,
        15,
        tzinfo=RIYADH,
    )


def test_before_boundary_does_not_generate_future_interval(
    storage,
    config,
):
    previous = datetime(
        2026,
        10,
        14,
        17,
        0,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        make_batch(previous)
    )

    producer, _ = make_producer(
        storage,
        config,
    )

    inserted = producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            17,
            14,
            59,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 0

    assert storage.get_latest_timestamp() == previous


# ---------------------------------------------------------------------------
# Midnight behavior
# ---------------------------------------------------------------------------


def test_gap_recovery_handles_midnight(
    storage,
    config,
):
    previous = datetime(
        2026,
        10,
        14,
        23,
        45,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        make_batch(previous)
    )

    producer, _ = make_producer(
        storage,
        config,
    )

    inserted = producer.synchronize(
        now=datetime(
            2026,
            10,
            15,
            0,
            7,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 12

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        15,
        0,
        0,
        tzinfo=RIYADH,
    )


def test_generation_resets_deterministically_each_calendar_day(
    storage,
    config,
):
    producer, generator = make_producer(
        storage,
        config,
    )

    producer._generate_window(
        start_exclusive=datetime(
            2026,
            10,
            14,
            23,
            30,
            tzinfo=RIYADH,
        ),
        end_inclusive=datetime(
            2026,
            10,
            15,
            0,
            15,
            tzinfo=RIYADH,
        ),
    )

    assert len(generator.reset_seeds) == 2

    assert (
        generator.reset_seeds[0]
        != generator.reset_seeds[1]
    )


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_overlapping_windows_generate_identical_shared_observations(
    tmp_path,
    config,
):
    storage_one = SyntheticTrafficStorage(
        tmp_path / "one.db"
    )
    storage_one.initialize()

    storage_two = SyntheticTrafficStorage(
        tmp_path / "two.db"
    )
    storage_two.initialize()

    producer_one, _ = make_producer(
        storage_one,
        config,
    )

    producer_two, _ = make_producer(
        storage_two,
        config,
    )

    first_result = producer_one._generate_window(
        start_exclusive=datetime(
            2026,
            10,
            14,
            8,
            0,
            tzinfo=RIYADH,
        ),
        end_inclusive=datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
    )

    second_result = producer_two._generate_window(
        start_exclusive=datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        ),
        end_inclusive=datetime(
            2026,
            10,
            14,
            9,
            0,
            tzinfo=RIYADH,
        ),
    )

    shared_from_first = [
        observation
        for observation in first_result
        if observation.timestamp
        > datetime(
            2026,
            10,
            14,
            8,
            30,
            tzinfo=RIYADH,
        )
    ]

    assert shared_from_first == second_result


def test_new_producer_instance_can_recover_existing_gap(
    storage,
    config,
):
    existing_timestamp = datetime(
        2026,
        10,
        14,
        10,
        0,
        tzinfo=RIYADH,
    )

    storage.insert_observations(
        make_batch(existing_timestamp)
    )

    first_producer, _ = make_producer(
        storage,
        config,
    )

    first_producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            10,
            30,
            tzinfo=RIYADH,
        )
    )

    second_producer, _ = make_producer(
        storage,
        config,
    )

    inserted = second_producer.synchronize(
        now=datetime(
            2026,
            10,
            14,
            11,
            0,
            tzinfo=RIYADH,
        )
    )

    assert inserted == 24

    assert storage.get_latest_timestamp() == datetime(
        2026,
        10,
        14,
        11,
        0,
        tzinfo=RIYADH,
    )



# ---------------------------------------------------------------------------
# Automatic interval scheduling
# ---------------------------------------------------------------------------


def test_next_interval_boundary_from_middle_of_interval(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        7,
        tzinfo=RIYADH,
    )

    result = next_interval_boundary(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        15,
        tzinfo=RIYADH,
    )


def test_next_interval_boundary_from_exact_boundary(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        15,
        tzinfo=RIYADH,
    )

    result = next_interval_boundary(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        30,
        tzinfo=RIYADH,
    )


def test_next_interval_boundary_handles_hour_change(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        17,
        59,
        tzinfo=RIYADH,
    )

    result = next_interval_boundary(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        18,
        0,
        tzinfo=RIYADH,
    )


def test_next_interval_boundary_handles_midnight(
    config,
):
    now = datetime(
        2026,
        10,
        14,
        23,
        59,
        tzinfo=RIYADH,
    )

    result = next_interval_boundary(
        now=now,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        15,
        0,
        0,
        tzinfo=RIYADH,
    )


def test_next_interval_boundary_normalizes_timezone(
    config,
):
    now_utc = datetime(
        2026,
        10,
        14,
        14,
        7,
        tzinfo=timezone.utc,
    )

    result = next_interval_boundary(
        now=now_utc,
        config=config,
    )

    assert result == datetime(
        2026,
        10,
        14,
        17,
        15,
        tzinfo=RIYADH,
    )


def test_run_forever_synchronizes_on_start_and_stops_cleanly(
    storage,
    config,
):
    producer, _ = make_producer(
        storage,
        config,
    )

    calls = []

    def fake_synchronize():
        calls.append("synchronize")
        return 0

    producer.synchronize = fake_synchronize

    stop_event = Event()
    stop_event.set()

    producer.run_forever(
        stop_event=stop_event,
    )

    assert calls == ["synchronize"]


def test_run_forever_can_stop_while_waiting(
    storage,
    config,
):
    producer, _ = make_producer(
        storage,
        config,
    )

    calls = []

    def fake_synchronize():
        calls.append("synchronize")
        return 0

    producer.synchronize = fake_synchronize

    class StopDuringWaitEvent:
        def is_set(self):
            return False

        def wait(self, timeout):
            assert timeout >= 0
            return True

    producer.run_forever(
        stop_event=StopDuringWaitEvent(),
    )

    assert calls == ["synchronize"]
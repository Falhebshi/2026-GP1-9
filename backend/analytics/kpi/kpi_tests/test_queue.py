from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi.intervals import analysis_intervals
from backend.analytics.kpi.parameters import QUEUE_PERCENTILE
from backend.analytics.kpi.queue import (
    LaneQueue,
    interval_queues,
    nearest_rank_percentile,
    period_percentile_queues,
    storage_ratio,
)
from jaadah.models.outputs import CycleQueueRecord


RIYADH = timezone(timedelta(hours=3))

LANES = ["LANE_E_1", "LANE_E_2"]


def at(hour, minute, second=0):
    """A Riyadh time on the test day."""

    return datetime(2026, 10, 14, hour, minute, second, tzinfo=RIYADH)


# Two intervals: 08:00–08:15 and 08:15–08:30.
INTERVALS = analysis_intervals(at(8, 0), at(8, 30))
FIRST, SECOND = INTERVALS


def cycle(cycle_start, length_m, vehicles, **overrides):
    """A valid 120 s cycle record on LANE_E_2."""

    data = {
        "run_id": "RUN_1",
        "lane_id": "LANE_E_2",
        "cycle_start": cycle_start,
        "cycle_end": cycle_start + timedelta(seconds=120),
        "max_queue_length_m": length_m,
        "max_queue_vehicles": vehicles,
    }
    data.update(overrides)
    return CycleQueueRecord(**data)


def per_interval(records, run_id="RUN_1"):
    return interval_queues(run_id, LANES, INTERVALS, list(records))


def per_period(records, run_id="RUN_1"):
    return period_percentile_queues(run_id, LANES, INTERVALS, list(records))


# ============================================================
# QUEUE PER INTERVAL
# ============================================================

def test_largest_cycle_queue_in_interval():
    queues = per_interval([
        cycle(at(8, 0), 20.0, 3),
        cycle(at(8, 2), 48.0, 7),
        cycle(at(8, 4), 30.0, 5),
    ])

    assert queues[("LANE_E_2", FIRST)] == LaneQueue(48.0, 7)


def test_metres_and_vehicles_are_each_the_largest():
    """Long cars in one cycle, more short cars in another."""

    queues = per_interval([
        cycle(at(8, 0), 50.0, 6),
        cycle(at(8, 2), 45.0, 8),
    ])

    assert queues[("LANE_E_2", FIRST)] == LaneQueue(50.0, 8)


def test_intervals_are_separate():
    queues = per_interval([
        cycle(at(8, 0), 20.0, 3),
        cycle(at(8, 16), 60.0, 9),
    ])

    assert queues[("LANE_E_2", FIRST)] == LaneQueue(20.0, 3)
    assert queues[("LANE_E_2", SECOND)] == LaneQueue(60.0, 9)


def test_lanes_are_separate():
    queues = per_interval([
        cycle(at(8, 0), 20.0, 3),
        cycle(at(8, 0), 35.0, 5, lane_id="LANE_E_1"),
    ])

    assert queues[("LANE_E_1", FIRST)] == LaneQueue(35.0, 5)
    assert queues[("LANE_E_2", FIRST)] == LaneQueue(20.0, 3)


def test_cycle_spanning_boundary_belongs_to_its_start():
    """08:14–08:16 starts in the first interval."""

    queues = per_interval([cycle(at(8, 14), 60.0, 9)])

    assert queues[("LANE_E_2", FIRST)] == LaneQueue(60.0, 9)
    assert queues[("LANE_E_2", SECOND)] is None


def test_cycle_starting_on_boundary_belongs_to_later_interval():
    queues = per_interval([cycle(at(8, 15), 60.0, 9)])

    assert queues[("LANE_E_2", FIRST)] is None
    assert queues[("LANE_E_2", SECOND)] == LaneQueue(60.0, 9)


@pytest.mark.parametrize("cycle_start", [at(7, 59), at(8, 30), at(8, 32)])
def test_cycle_starting_outside_analysis_period_not_used(cycle_start):
    """07:59 starts in warm-up (ends 08:01); 08:30+ is clearance."""

    queues = per_interval([cycle(cycle_start, 60.0, 9)])

    assert all(value is None for value in queues.values())


# ============================================================
# MEASURED ZERO VS MISSING DATA
# ============================================================

def test_reported_zero_queue_is_zero():
    queues = per_interval([cycle(at(8, 0), 0, 0)])

    assert queues[("LANE_E_2", FIRST)] == LaneQueue(0, 0)


def test_no_records_is_missing_not_zero():
    queues = per_interval([cycle(at(8, 0), 20.0, 3)])

    assert queues[("LANE_E_1", FIRST)] is None
    assert queues[("LANE_E_2", SECOND)] is None


def test_every_lane_and_interval_is_in_result():
    queues = per_interval([])

    assert set(queues) == {
        (lane_id, interval)
        for lane_id in LANES
        for interval in INTERVALS
    }


# ============================================================
# 95TH PERCENTILE OVER THE ANALYSIS PERIOD
# ============================================================

def test_percentile_over_whole_period():
    """
    15 cycles from 08:00, every 2 minutes, with queues 1–15 vehicles.
    Rank = ceil(0.95 x 15) = 15, so the largest: 15 vehicles.
    """

    records = [
        cycle(at(8, 0) + timedelta(minutes=2 * index),
              float(10 * (index + 1)), index + 1)
        for index in range(15)
    ]

    queues = per_period(records)

    assert queues["LANE_E_2"] == LaneQueue(150.0, 15)


def test_percentile_combines_all_intervals():
    """
    20 cycles of 84 s split over both intervals: the 19th smallest
    of all.
    """

    records = [
        cycle(at(8, 0) + timedelta(seconds=84 * index),
              float(index + 1), index + 1,
              cycle_end=at(8, 0) + timedelta(seconds=84 * (index + 1)))
        for index in range(20)
    ]

    queues = per_period(records)

    assert queues["LANE_E_2"] == LaneQueue(19.0, 19)


def test_percentile_ignores_warmup_and_clearance_cycles():
    queues = per_period([
        cycle(at(7, 58), 500.0, 70),
        cycle(at(8, 0), 20.0, 3),
        cycle(at(8, 30), 500.0, 70),
    ])

    assert queues["LANE_E_2"] == LaneQueue(20.0, 3)


def test_percentile_for_lane_without_records_is_missing():
    queues = per_period([cycle(at(8, 0), 20.0, 3)])

    assert queues["LANE_E_1"] is None


def test_queue_percentile_constant():
    assert QUEUE_PERCENTILE == 95


# ============================================================
# NEAREST-RANK PERCENTILE
# ============================================================

@pytest.mark.parametrize(
    "values, percentile, expected",
    [
        (list(range(1, 21)), 95, 19),
        (list(range(1, 21)), 100, 20),
        (list(range(1, 21)), 50, 10),
        (list(range(1, 21)), 5, 1),
        ([7], 95, 7),
        ([3, 1, 2], 95, 3),
    ],
)
def test_nearest_rank_percentile(values, percentile, expected):
    assert nearest_rank_percentile(values, percentile) == expected


def test_percentile_is_always_one_of_the_values():
    values = [12.5, 30.0, 48.0, 7.5]

    assert nearest_rank_percentile(values, 95) in values


def test_percentile_does_not_change_input_order():
    values = [3, 1, 2]

    nearest_rank_percentile(values, 95)

    assert values == [3, 1, 2]


def test_percentile_of_empty_list_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        nearest_rank_percentile([], 95)


@pytest.mark.parametrize("percentile", [0, -5, 100.1])
def test_invalid_percentile_rejected(percentile):
    with pytest.raises(ValueError, match="percentile must be"):
        nearest_rank_percentile([1, 2, 3], percentile)


# ============================================================
# STORAGE RATIO
# ============================================================

@pytest.mark.parametrize(
    "queue, storage, expected",
    [(60.0, 120.0, 0.5), (0, 120.0, 0.0), (150.0, 120.0, 1.25)],
)
def test_storage_ratio(queue, storage, expected):
    assert storage_ratio(queue, storage) == expected


def test_storage_ratio_without_storage_length_is_missing():
    assert storage_ratio(60.0, None) is None


@pytest.mark.parametrize("storage", [0, -10.0])
def test_invalid_storage_length_rejected(storage):
    with pytest.raises(ValueError, match="must be positive"):
        storage_ratio(60.0, storage)


# ============================================================
# INPUT CHECKS
# ============================================================

def test_record_from_another_run_rejected():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        per_interval([cycle(at(8, 0), 20.0, 3, run_id="RUN_2")])


def test_lane_not_analysed_rejected():
    with pytest.raises(ValueError, match="lane LANE_X is not analysed"):
        per_interval([cycle(at(8, 0), 20.0, 3, lane_id="LANE_X")])


def test_duplicate_cycle_rejected():
    with pytest.raises(ValueError, match="two records for the cycle"):
        per_interval([
            cycle(at(8, 0), 20.0, 3),
            cycle(at(8, 0), 25.0, 4),
        ])


def test_same_cycle_start_on_two_lanes_is_allowed():
    queues = per_interval([
        cycle(at(8, 0), 20.0, 3),
        cycle(at(8, 0), 25.0, 4, lane_id="LANE_E_1"),
    ])

    assert queues[("LANE_E_1", FIRST)] == LaneQueue(25.0, 4)


def test_checks_also_apply_to_percentile():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        per_period([cycle(at(8, 0), 20.0, 3, run_id="RUN_2")])
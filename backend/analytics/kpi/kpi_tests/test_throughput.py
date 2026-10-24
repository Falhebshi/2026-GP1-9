from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi.intervals import analysis_intervals
from backend.analytics.kpi.throughput import (
    count_served_vehicles,
    vehicles_per_hour,
)
from jaadah.models.outputs import IncompletePassage, VehicleDelayRecord


RIYADH = timezone(timedelta(hours=3))

MOVEMENTS = ["MOV_E_T", "MOV_E_L"]


def at(hour, minute, second=0):
    """A Riyadh time on the test day."""

    return datetime(2026, 10, 14, hour, minute, second, tzinfo=RIYADH)


# Two intervals: 08:00–08:15 and 08:15–08:30.
INTERVALS = analysis_intervals(at(8, 0), at(8, 30))
FIRST, SECOND = INTERVALS


def delay_record(vehicle_id, stop_line_time, **overrides):
    """
    A valid passage that crosses the stop line at stop_line_time,
    40 s after entering the zone, and leaves 10 s later.
    """

    data = {
        "run_id": "RUN_1",
        "vehicle_id": vehicle_id,
        "movement_id": "MOV_E_T",
        "zone_entry_time": stop_line_time - timedelta(seconds=40),
        "stop_line_time": stop_line_time,
        "zone_exit_time": stop_line_time + timedelta(seconds=10),
        "zone_distance_m": 330.0,
        "free_flow_travel_time_s": 25.0,
        "halted_time_s": 10.0,
    }
    data.update(overrides)
    return VehicleDelayRecord(**data)


def incomplete(vehicle_id, stop_line_time, **overrides):
    """A vehicle still in the zone when the run ended."""

    data = {
        "run_id": "RUN_1",
        "vehicle_id": vehicle_id,
        "movement_id": "MOV_E_L",
        "zone_entry_time": at(8, 28),
        "stop_line_time": stop_line_time,
        "last_seen_time": at(8, 29, 30),
    }
    data.update(overrides)
    return IncompletePassage(**data)


def count(delay_records=(), incomplete_passages=(), run_id="RUN_1"):
    return count_served_vehicles(
        run_id=run_id,
        movement_ids=MOVEMENTS,
        intervals=INTERVALS,
        delay_records=list(delay_records),
        incomplete_passages=list(incomplete_passages),
    )


# ============================================================
# COUNTING
# ============================================================

def test_vehicles_counted_in_their_interval():
    counts = count([
        delay_record("v1", at(8, 1)),
        delay_record("v2", at(8, 5)),
        delay_record("v3", at(8, 20)),
    ])

    assert counts[("MOV_E_T", FIRST)] == 2
    assert counts[("MOV_E_T", SECOND)] == 1


def test_movements_counted_separately():
    counts = count([
        delay_record("v1", at(8, 1)),
        delay_record("v2", at(8, 2), movement_id="MOV_E_L"),
    ])

    assert counts[("MOV_E_T", FIRST)] == 1
    assert counts[("MOV_E_L", FIRST)] == 1


def test_counted_by_stop_line_not_by_entry():
    """Entered the zone in the first interval, crossed in the second."""

    record = delay_record(
        "v1",
        at(8, 16),
        zone_entry_time=at(8, 14),
    )

    counts = count([record])

    assert counts[("MOV_E_T", FIRST)] == 0
    assert counts[("MOV_E_T", SECOND)] == 1


def test_crossing_on_boundary_counts_in_later_interval():
    counts = count([delay_record("v1", at(8, 15))])

    assert counts[("MOV_E_T", FIRST)] == 0
    assert counts[("MOV_E_T", SECOND)] == 1


# ============================================================
# EMPTY INTERVALS ARE MEASURED ZEROS
# ============================================================

def test_every_movement_and_interval_is_reported():
    counts = count()

    assert set(counts) == {
        (movement_id, interval)
        for movement_id in MOVEMENTS
        for interval in INTERVALS
    }


def test_no_traffic_gives_zero():
    counts = count([delay_record("v1", at(8, 1))])

    assert counts[("MOV_E_L", FIRST)] == 0
    assert counts[("MOV_E_L", SECOND)] == 0


# ============================================================
# WARM-UP AND CLEARANCE
# ============================================================

@pytest.mark.parametrize(
    "stop_line_time",
    [at(7, 59, 59), at(8, 30), at(8, 35)],
)
def test_crossing_outside_analysis_period_not_counted(stop_line_time):
    counts = count([delay_record("v1", stop_line_time)])

    assert sum(counts.values()) == 0


def test_arrived_in_warmup_crossed_in_analysis_is_counted():
    record = delay_record(
        "v1",
        at(8, 0, 30),
        zone_entry_time=at(7, 59, 40),
    )

    counts = count([record])

    assert counts[("MOV_E_T", FIRST)] == 1


# ============================================================
# VEHICLES STILL IN THE ZONE AT THE END
# ============================================================

def test_incomplete_passage_that_crossed_is_counted():
    counts = count(incomplete_passages=[incomplete("v9", at(8, 29))])

    assert counts[("MOV_E_L", SECOND)] == 1


def test_incomplete_passage_that_did_not_cross_is_not_counted():
    counts = count(incomplete_passages=[incomplete("v9", None)])

    assert sum(counts.values()) == 0


def test_complete_and_incomplete_are_added_together():
    counts = count(
        [delay_record("v1", at(8, 20), movement_id="MOV_E_L")],
        [incomplete("v9", at(8, 29))],
    )

    assert counts[("MOV_E_L", SECOND)] == 2


# ============================================================
# INPUT CHECKS
# ============================================================

def test_record_from_another_run_rejected():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        count([delay_record("v1", at(8, 1), run_id="RUN_2")])


def test_incomplete_from_another_run_rejected():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        count(incomplete_passages=[
            incomplete("v9", at(8, 29), run_id="RUN_2")
        ])


def test_movement_not_analysed_rejected():
    with pytest.raises(ValueError, match="movement MOV_X, which is not analysed"):
        count([delay_record("v1", at(8, 1), movement_id="MOV_X")])


def test_same_vehicle_twice_rejected():
    with pytest.raises(ValueError, match="v1 appears more than once"):
        count([
            delay_record("v1", at(8, 1)),
            delay_record("v1", at(8, 20)),
        ])


def test_same_vehicle_complete_and_incomplete_rejected():
    with pytest.raises(ValueError, match="v1 appears more than once"):
        count(
            [delay_record("v1", at(8, 1))],
            [incomplete("v1", at(8, 29))],
        )


def test_incomplete_without_crossing_is_not_checked_for_duplicates():
    """It is not a crossing, so it cannot double-count anything."""

    counts = count(
        [delay_record("v1", at(8, 1))],
        [incomplete("v1", None)],
    )

    assert counts[("MOV_E_T", FIRST)] == 1


# ============================================================
# VEHICLES PER HOUR
# ============================================================

@pytest.mark.parametrize(
    "vehicles, expected",
    [(0, 0.0), (1, 4.0), (120, 480.0)],
)
def test_vehicles_per_hour(vehicles, expected):
    assert vehicles_per_hour(vehicles) == expected
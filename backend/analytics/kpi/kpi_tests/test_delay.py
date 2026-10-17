from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi.delay import (
    NO_ARRIVALS_REASON,
    MovementDelay,
    movement_delays,
)
from backend.analytics.kpi.intervals import analysis_intervals
from jaadah.models.kpis import KpiStatus
from jaadah.models.outputs import IncompletePassage, VehicleDelayRecord


RIYADH = timezone(timedelta(hours=3))

MOVEMENTS = ["MOV_E_T", "MOV_E_L"]


def at(hour, minute, second=0):
    """A Riyadh time on the test day."""

    return datetime(2026, 10, 14, hour, minute, second, tzinfo=RIYADH)


# Two intervals: 08:00–08:15 and 08:15–08:30.
INTERVALS = analysis_intervals(at(8, 0), at(8, 30))
FIRST, SECOND = INTERVALS


def passage(vehicle_id, entry, time_loss_s, halted_time_s, **overrides):
    """
    A completed East-through passage entering at `entry`.

    Free-flow travel time is 25 s, so the vehicle spends
    25 + time_loss_s in the zone. It crosses the stop line 10 s before
    leaving.
    """

    zone_time = timedelta(seconds=25 + time_loss_s)

    data = {
        "run_id": "RUN_1",
        "vehicle_id": vehicle_id,
        "movement_id": "MOV_E_T",
        "zone_entry_time": entry,
        "stop_line_time": entry + zone_time - timedelta(seconds=10),
        "zone_exit_time": entry + zone_time,
        "zone_distance_m": 330.0,
        "free_flow_travel_time_s": 25.0,
        "halted_time_s": halted_time_s,
    }
    data.update(overrides)
    return VehicleDelayRecord(**data)


def unfinished(vehicle_id, entry, **overrides):
    """A vehicle still in the zone when the run ended."""

    data = {
        "run_id": "RUN_1",
        "vehicle_id": vehicle_id,
        "movement_id": "MOV_E_T",
        "zone_entry_time": entry,
        "last_seen_time": at(8, 45),
    }
    data.update(overrides)
    return IncompletePassage(**data)


def delays(delay_records=(), incomplete_passages=(), run_id="RUN_1"):
    return movement_delays(
        run_id=run_id,
        movement_ids=MOVEMENTS,
        intervals=INTERVALS,
        delay_records=list(delay_records),
        incomplete_passages=list(incomplete_passages),
    )


# ============================================================
# MEAN DELAY AND QUEUE DURATION
# ============================================================

def test_mean_delay_and_queue_duration():
    result = delays([
        passage("v1", at(8, 1), time_loss_s=30, halted_time_s=20),
        passage("v2", at(8, 3), time_loss_s=0, halted_time_s=0),
        passage("v3", at(8, 5), time_loss_s=45, halted_time_s=35),
    ])

    assert result[("MOV_E_T", FIRST)] == MovementDelay(
        status=KpiStatus.OK,
        completed_vehicles=3,
        incomplete_vehicles=0,
        mean_control_delay_s=25.0,
        mean_queue_duration_s=pytest.approx(55 / 3),
        reason=None,
    )


def test_queue_duration_counts_vehicles_that_did_not_stop():
    """One vehicle stopped 40 s, three did not: 40 / 4 = 10 s."""

    result = delays([
        passage("v1", at(8, 1), time_loss_s=50, halted_time_s=40),
        passage("v2", at(8, 2), time_loss_s=2, halted_time_s=0),
        passage("v3", at(8, 3), time_loss_s=1, halted_time_s=0),
        passage("v4", at(8, 4), time_loss_s=3, halted_time_s=0),
    ])

    assert result[("MOV_E_T", FIRST)].mean_queue_duration_s == 10.0


def test_single_vehicle():
    result = delays([passage("v1", at(8, 1), 12.5, 4.0)])

    summary = result[("MOV_E_T", FIRST)]

    assert summary.status == KpiStatus.OK
    assert summary.mean_control_delay_s == 12.5
    assert summary.mean_queue_duration_s == 4.0


def test_movements_are_separate():
    result = delays([
        passage("v1", at(8, 1), 10, 0),
        passage("v2", at(8, 1), 50, 30, movement_id="MOV_E_L"),
    ])

    assert result[("MOV_E_T", FIRST)].mean_control_delay_s == 10
    assert result[("MOV_E_L", FIRST)].mean_control_delay_s == 50


# ============================================================
# WHICH INTERVAL A VEHICLE BELONGS TO
# ============================================================

def test_delay_belongs_to_arrival_interval():
    """Arrives 08:14:50, leaves 08:16:05: counted in 08:00–08:15."""

    result = delays([passage("v1", at(8, 14, 50), 50, 30)])

    assert result[("MOV_E_T", FIRST)].completed_vehicles == 1
    assert result[("MOV_E_T", SECOND)].completed_vehicles == 0


def test_arrival_on_boundary_belongs_to_later_interval():
    result = delays([passage("v1", at(8, 15), 20, 5)])

    assert result[("MOV_E_T", SECOND)].completed_vehicles == 1


@pytest.mark.parametrize("entry", [at(7, 59, 50), at(8, 30), at(8, 31)])
def test_arrival_outside_analysis_period_not_counted(entry):
    """Arrived during warm-up (even if served after 08:00) or clearance."""

    result = delays([passage("v1", entry, 20, 5)])

    assert all(
        summary.completed_vehicles == 0 for summary in result.values()
    )


# ============================================================
# VEHICLES THAT HAD NOT FINISHED
# ============================================================

def test_unfinished_vehicle_makes_interval_unavailable():
    result = delays(
        [passage("v1", at(8, 20), 15, 5)],
        [unfinished("v9", at(8, 25))],
    )

    summary = result[("MOV_E_T", SECOND)]

    assert summary.status == KpiStatus.UNAVAILABLE
    assert summary.mean_control_delay_s is None
    assert summary.mean_queue_duration_s is None
    assert summary.completed_vehicles == 1
    assert summary.incomplete_vehicles == 1
    assert "1 vehicle(s) had not finished" in summary.reason
    assert "clearance" in summary.reason


def test_unfinished_vehicle_only_affects_its_own_interval():
    result = delays(
        [passage("v1", at(8, 1), 15, 5)],
        [unfinished("v9", at(8, 25))],
    )

    assert result[("MOV_E_T", FIRST)].status == KpiStatus.OK


def test_unfinished_vehicle_only_affects_its_own_movement():
    result = delays(
        [passage("v1", at(8, 20), 15, 5, movement_id="MOV_E_L")],
        [unfinished("v9", at(8, 25))],
    )

    assert result[("MOV_E_L", SECOND)].status == KpiStatus.OK


def test_reason_counts_unfinished_vehicles():
    result = delays(incomplete_passages=[
        unfinished("v8", at(8, 20)),
        unfinished("v9", at(8, 25)),
    ])

    assert result[("MOV_E_T", SECOND)].reason.startswith("2 vehicle(s)")


def test_unfinished_vehicle_that_crossed_stop_line_still_counts():
    result = delays(incomplete_passages=[
        unfinished("v9", at(8, 25), stop_line_time=at(8, 26)),
    ])

    assert result[("MOV_E_T", SECOND)].status == KpiStatus.UNAVAILABLE


def test_unfinished_vehicle_that_arrived_in_warmup_ignored():
    result = delays(
        [passage("v1", at(8, 1), 15, 5)],
        [unfinished("v9", at(7, 59))],
    )

    assert result[("MOV_E_T", FIRST)].status == KpiStatus.OK


# ============================================================
# INTERVALS WITH NO ARRIVALS
# ============================================================

def test_no_arrivals_is_not_applicable():
    result = delays([passage("v1", at(8, 1), 15, 5)])

    summary = result[("MOV_E_L", FIRST)]

    assert summary.status == KpiStatus.NOT_APPLICABLE
    assert summary.mean_control_delay_s is None
    assert summary.mean_queue_duration_s is None
    assert summary.reason == NO_ARRIVALS_REASON


def test_every_movement_and_interval_is_in_result():
    result = delays()

    assert set(result) == {
        (movement_id, interval)
        for movement_id in MOVEMENTS
        for interval in INTERVALS
    }


def test_ok_result_has_no_reason():
    result = delays([passage("v1", at(8, 1), 15, 5)])

    assert result[("MOV_E_T", FIRST)].reason is None


# ============================================================
# INPUT CHECKS
# ============================================================

def test_record_from_another_run_rejected():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        delays([passage("v1", at(8, 1), 15, 5, run_id="RUN_2")])


def test_unfinished_from_another_run_rejected():
    with pytest.raises(ValueError, match="belongs to run RUN_2"):
        delays(incomplete_passages=[
            unfinished("v9", at(8, 25), run_id="RUN_2")
        ])


def test_movement_not_analysed_rejected():
    with pytest.raises(ValueError, match="movement MOV_X, which is not"):
        delays([passage("v1", at(8, 1), 15, 5, movement_id="MOV_X")])


def test_same_vehicle_twice_rejected():
    with pytest.raises(ValueError, match="v1 appears more than once"):
        delays([
            passage("v1", at(8, 1), 15, 5),
            passage("v1", at(8, 20), 15, 5),
        ])


def test_same_vehicle_completed_and_unfinished_rejected():
    with pytest.raises(ValueError, match="v1 appears more than once"):
        delays(
            [passage("v1", at(8, 1), 15, 5)],
            [unfinished("v1", at(8, 25))],
        )
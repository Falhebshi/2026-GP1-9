"""
Period values of the historical analysis, from two hand-made days.

Day A is Tue 27 Oct 2026 and day B is Wed 28 Oct. Each test gives the
days a few vehicles, cycle queues and demand in chosen 15-minute slots
(slot 30 is 07:30-07:45) and checks the combined value against a hand
calculation.
"""

import math
from datetime import date, datetime, timedelta

import pytest

from backend.analytics.service import DEFAULT_MAPPING_PATH, RunMeasurements
from backend.analytics.trends import (
    DELAY,
    LOS,
    QUEUE,
    QUEUE_DURATION,
    THROUGHPUT,
    VC,
    hour_slots,
    period_values,
    prepare_day,
    slot_of,
)
from jaadah.kpi_inputs.cycle_queues import CycleQueues
from jaadah.kpi_inputs.vehicle_passages import VehiclePassages
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import KpiLevel, KpiStatus, KpiUnit, LevelOfServiceGrade
from jaadah.models.outputs import ApproachCycleQueueRecord, CycleQueueRecord, VehicleDelayRecord
from jaadah.models.scenario import SimulationRun
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import RunWindow


DAY_A, DAY_B = date(2026, 10, 27), date(2026, 10, 28)
CONFIG = load_network_mappings(DEFAULT_MAPPING_PATH)
LANES = [lane.lane_id for lane in CONFIG.approach_lanes]
SIGNAL_APPROACHES = ["APP_E", "APP_N", "APP_S", "APP_W"]
CYCLE_S = 120
CYCLES_PER_SLOT = 8           # cycles starting at +0, +120, ... +840 s of each slot

M, VEH, MOV, APP, INT, LANE = (
    KpiUnit.METRES, KpiUnit.VEHICLES, KpiLevel.MOVEMENT, KpiLevel.APPROACH,
    KpiLevel.INTERSECTION, KpiLevel.LANE,
)


def at(day: date, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day.isoformat()}T{clock}+03:00")


def run_id(day: date) -> str:
    return f"RUN_HISTORY_{day:%Y%m%d}_S42"


def car(day, number, entry, loss_s, halted_s, movement="MOV_E_W"):
    """A car with a chosen time loss: free-flow 30 s, so it spends 30 + loss_s in the zone."""

    start = at(day, entry)
    return VehicleDelayRecord(
        run_id=run_id(day), vehicle_id=f"{movement}__{day:%Y%m%d}__{number:03d}", movement_id=movement,
        zone_entry_time=start, stop_line_time=start + timedelta(seconds=10),
        zone_exit_time=start + timedelta(seconds=30 + loss_s),
        zone_distance_m=400.0, free_flow_travel_time_s=30.0, halted_time_s=halted_s,
    )


def cycles(day, slots, lane_values=None, cut_lane_values=(), cut_approach_slots=()):
    """
    Cycle records for every lane and signalised approach in the slots,
    0 m unless lane_values gives a lane's queues (in metres, one per
    cycle in time order). cut_lane_values marks those lane values as cut
    off at the section end; cut_approach_slots marks (approach, slot)
    cycles as reaching the zone end.
    """

    lane_values = lane_values or {}
    lanes, approaches = [], []
    order = 0

    for slot in sorted(slots):
        slot_start = at(day, "00:00:00") + timedelta(minutes=15 * slot)
        for k in range(CYCLES_PER_SLOT):
            start = slot_start + timedelta(seconds=CYCLE_S * k)
            end = start + timedelta(seconds=CYCLE_S)
            for lane in LANES:
                metres = lane_values.get(lane, [])[order] if lane in lane_values else 0.0
                lanes.append(CycleQueueRecord(
                    run_id=run_id(day), lane_id=lane, cycle_start=start, cycle_end=end,
                    max_queue_length_m=metres, max_queue_vehicles=math.ceil(metres / 7.5),
                    reaches_section_end=(lane, metres) in cut_lane_values,
                ))
            for approach in SIGNAL_APPROACHES:
                cut = (approach, slot) in cut_approach_slots
                approaches.append(ApproachCycleQueueRecord(
                    run_id=run_id(day), approach_id=approach, cycle_start=start, cycle_end=end,
                    max_queue_length_m=388.0 if cut else 0.0, max_queue_vehicles=52 if cut else 0,
                    reaches_zone_end=cut,
                ))
            order += 1

    return CycleQueues(lanes, approaches)


def demand(day, movement, slot, count):
    start = at(day, "00:00:00") + timedelta(minutes=15 * slot)
    return SimulationDemand(
        demand_id=f"DEM_{movement}_{start:%Y%m%dT%H%M}", movement_id=movement,
        interval_start=start, interval_end=start + timedelta(minutes=15),
        vehicle_count=count, source="synthetic", source_observation_ids=["OBS_1"],
    )


def stored_day(day, cars=(), queues=None, demands=(), slots=frozenset({30})):
    midnight = at(day, "00:00:00")
    run = SimulationRun(
        run_id=run_id(day), scenario_id=f"SCN_HISTORY_{day:%Y%m%d}", random_seed=42,
        network_version="jaadah_network_v2", sumo_version="1.27.1", step_length_s=0.4,
        mapping_version=CONFIG.mapping_version, started_at=midnight - timedelta(days=1),
        demand_sha256="a" * 64, route_file_sha256="b" * 64, status="completed",
    )
    window = RunWindow(
        epoch=midnight - timedelta(minutes=15), analysis_start=midnight,
        analysis_end=midnight + timedelta(days=1), run_end=midnight + timedelta(days=1, minutes=15),
    )
    measurements = RunMeasurements(
        run, window, VehiclePassages(list(cars), [], []),
        queues or cycles(day, slots), list(demands),
    )
    return prepare_day(day, measurements)


# ============================================================
# SLOTS
# ============================================================

def test_slots_of_the_day():
    assert slot_of(at(DAY_A, "00:00:00")) == 0
    assert slot_of(at(DAY_A, "07:30:00")) == 30
    assert slot_of(at(DAY_A, "07:44:59")) == 30
    assert slot_of(at(DAY_A, "23:45:00")) == 95
    assert hour_slots(17) == {68, 69, 70, 71}


def test_an_hour_outside_the_day_is_refused():
    with pytest.raises(ValueError, match="hour must be 0 to 23"):
        hour_slots(24)


def test_no_day_or_no_slot_is_refused():
    with pytest.raises(ValueError, match="at least one day"):
        period_values([])
    with pytest.raises(ValueError, match="at least one slot"):
        period_values([stored_day(DAY_A)], frozenset())


# ============================================================
# DELAY, LEVEL OF SERVICE, QUEUE DURATION
# ============================================================

def two_days_of_east_through():
    """
    East through, 07:30 slot. Day A: 2 cars, time loss 20 s and 40 s,
    stopped 10 s and 20 s. Day B: 1 car, 60 s, stopped 30 s.
    """

    day_a = stored_day(DAY_A, cars=[car(DAY_A, 1, "07:30:10", 20, 10), car(DAY_A, 2, "07:31:00", 40, 20)])
    day_b = stored_day(DAY_B, cars=[car(DAY_B, 1, "07:32:00", 60, 30)])
    return [day_a, day_b]


def test_delay_is_the_mean_over_every_vehicle():
    """
    (20 + 40 + 60) / 3 = 40 s. The mean of the two day means,
    (30 + 60) / 2 = 45 s, would count day B's single car twice as much.
    """

    values = period_values(two_days_of_east_through(), frozenset({30}))

    assert values[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, MOV, "MOV_E_W")].value == pytest.approx(40.0)
    # East left had no cars (not applicable, left out): the approach and
    # the intersection have the same 40 s
    assert values[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, APP, "APP_E")].value == pytest.approx(40.0)
    assert values[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, INT, "INT_001")].value == pytest.approx(40.0)


def test_level_of_service_is_graded_from_the_combined_delay():
    values = period_values(two_days_of_east_through(), frozenset({30}))

    # 40 s is above 35 and at most 55: LOS D
    assert values[(LOS, KpiUnit.GRADE, MOV, "MOV_E_W")].los_grade == LevelOfServiceGrade.D
    assert values[(LOS, KpiUnit.GRADE, INT, "INT_001")].los_grade == LevelOfServiceGrade.D


def test_queue_duration_is_the_mean_over_every_vehicle():
    values = period_values(two_days_of_east_through(), frozenset({30}))

    # (10 + 20 + 30) / 3 = 20 s
    assert values[(QUEUE_DURATION, KpiUnit.SECONDS, MOV, "MOV_E_W")].value == pytest.approx(20.0)


def test_one_unavailable_interval_makes_the_delay_unavailable():
    """
    Day B's East queue reaches the end of its zone at 07:30: that
    interval's delay is unknown, so the combined delay is unavailable,
    not the 30 s of day A alone.
    """

    day_a, _ = two_days_of_east_through()
    day_b = stored_day(
        DAY_B, cars=[car(DAY_B, 1, "07:32:00", 60, 30)],
        queues=cycles(DAY_B, {30}, cut_approach_slots={("APP_E", 30)}),
    )

    values = period_values([day_a, day_b], frozenset({30}))

    for level, element in ((MOV, "MOV_E_W"), (APP, "APP_E"), (INT, "INT_001")):
        delay = values[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, level, element)]
        assert delay.status == KpiStatus.UNAVAILABLE
        assert "end of the measurement zone" in delay.reason
    assert values[(LOS, KpiUnit.GRADE, INT, "INT_001")].status == KpiStatus.UNAVAILABLE


def test_slots_with_no_vehicles_do_not_apply():
    values = period_values(two_days_of_east_through(), frozenset({30}))

    delay = values[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, MOV, "MOV_E_S")]
    assert delay.status == KpiStatus.NOT_APPLICABLE


# ============================================================
# THROUGHPUT
# ============================================================

def test_throughput_is_the_mean_hourly_flow():
    """
    Day A: 2 cars cross the stop line in the 07:30 slot = 8 veh/h;
    day B: 1 car = 4 veh/h. Mean (8 + 4) / 2 = 6 veh/h.
    """

    values = period_values(two_days_of_east_through(), frozenset({30}))

    assert values[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, MOV, "MOV_E_W")].value == pytest.approx(6.0)
    assert values[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, APP, "APP_E")].value == pytest.approx(6.0)
    assert values[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, INT, "INT_001")].value == pytest.approx(6.0)


def test_throughput_is_not_blocked_by_the_zone_end():
    """The zone end hides delay, not the cars that crossed the stop line."""

    day_a, _ = two_days_of_east_through()
    day_b = stored_day(
        DAY_B, cars=[car(DAY_B, 1, "07:32:00", 60, 30)],
        queues=cycles(DAY_B, {30}, cut_approach_slots={("APP_E", 30)}),
    )

    values = period_values([day_a, day_b], frozenset({30}))

    assert values[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, MOV, "MOV_E_W")].value == pytest.approx(6.0)


# ============================================================
# QUEUE LENGTH
# ============================================================

FIVE_SLOTS = frozenset({28, 29, 30, 31, 32})      # 07:00-08:15: 40 cycles a day, 80 over two days


def queue_days(cut=()):
    """
    East lane 3 queues 1, 2, ... 40 m on day A and 41, ... 80 m on day B
    (one value per cycle); the values in cut are cut off at the section end.
    """

    def day(d, values):
        marked = {("LANE_E_3", float(v)) for v in values if v in cut}
        return stored_day(
            d, slots=FIVE_SLOTS,
            queues=cycles(d, FIVE_SLOTS, {"LANE_E_3": [float(v) for v in values]}, cut_lane_values=marked),
        )

    return [day(DAY_A, range(1, 41)), day(DAY_B, range(41, 81))]


def test_queue_is_the_95th_percentile_of_every_cycle_pooled():
    """80 cycles: rank ceil(0.95 x 80) = 76, so 76 m."""

    values = period_values(queue_days(), FIVE_SLOTS)

    assert values[(QUEUE, M, LANE, "LANE_E_3")].value == pytest.approx(76.0)
    # East through uses lanes 2, 3, 4; the longest is lane 3
    assert values[(QUEUE, M, MOV, "MOV_E_W")].value == pytest.approx(76.0)
    assert values[(QUEUE, VEH, LANE, "LANE_E_3")].value == math.ceil(76 / 7.5)


def test_cut_off_cycles_above_the_percentile_do_not_change_it():
    """
    The 3 longest cycles (78, 79, 80 m) were cut off: their real queues
    were longer still, so cycle 76 stays the 76th. The value is exact.
    """

    values = period_values(queue_days(cut={78, 79, 80}), FIVE_SLOTS)

    assert values[(QUEUE, M, LANE, "LANE_E_3")].status == KpiStatus.OK
    assert values[(QUEUE, M, LANE, "LANE_E_3")].value == pytest.approx(76.0)


def test_a_cut_off_cycle_at_the_percentile_makes_the_queue_unavailable():
    """Cycles 76 to 80 were cut off: the 76th is one of them, so its real value is unknown."""

    values = period_values(queue_days(cut={76, 77, 78, 79, 80}), FIVE_SLOTS)

    lane = values[(QUEUE, M, LANE, "LANE_E_3")]
    assert lane.status == KpiStatus.UNAVAILABLE
    assert "section" in lane.reason


# ============================================================
# VOLUME-TO-CAPACITY RATIO
# ============================================================

def test_volume_to_capacity_is_the_highest_interval_with_its_time():
    """
    North left at 07:30: 100 vehicles on day A, 200 on day B. Its HCM
    capacity is 1,900 x 3 lanes x 0.971 / 1.05 x 15 s / 120 s = 658.9
    veh/h, so v/c is 400 / 658.9 = 0.61 on day A and 800 / 658.9 = 1.21
    on day B. The peak is day B's, with its interval.
    """

    day_a = stored_day(DAY_A, demands=[demand(DAY_A, "MOV_N_E", 30, 100)])
    day_b = stored_day(DAY_B, demands=[demand(DAY_B, "MOV_N_E", 30, 200)])

    vc = period_values([day_a, day_b], frozenset({30}))[(VC, KpiUnit.RATIO, MOV, "MOV_N_E")]

    capacity = 1900 * 3 * 0.971 / 1.05 * 15 / 120
    assert vc.status == KpiStatus.OK
    assert vc.value == pytest.approx(800 / capacity, rel=1e-3)
    assert vc.peak_interval.start == at(DAY_B, "07:30:00")
    assert vc.peak_interval.end == at(DAY_B, "07:45:00")


def test_volume_to_capacity_does_not_apply_to_a_slip():
    values = period_values([stored_day(DAY_A)], frozenset({30}))

    assert values[(VC, KpiUnit.RATIO, MOV, "MOV_N_W_SLIP")].status == KpiStatus.NOT_APPLICABLE

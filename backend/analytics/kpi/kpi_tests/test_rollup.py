import pytest

from backend.analytics.kpi.delay import MovementDelay
from backend.analytics.kpi.hcm_delay import calculate_hcm_delays
from backend.analytics.kpi.kpi_tests.test_capacity import (
    ATTRIBUTES,
    DEMAND,
    GROUPS,
    LANES,
    MOVEMENT_MODELS,
    program,
    results,
)
from backend.analytics.kpi.kpi_tests.test_hcm_delay import INTERVALS
from backend.analytics.kpi.parameters import level_of_service
from backend.analytics.kpi.queue import LaneQueue
from backend.analytics.kpi.rollup import (
    EXCLUDES_UNCONTROLLED,
    INCLUDES_UNCONTROLLED,
    NOTHING_TO_COMBINE_REASON,
    PART_UNAVAILABLE_REASON,
    Part,
    combine_highest,
    combine_sum,
    combine_weighted_mean,
    hcm_rollup,
    measured_delay_rollup,
    queue_rollup,
    storage_ratio_rollup,
    throughput_rollup,
)
from jaadah.models.kpis import KpiStatus
from jaadah.models.network import ApproachLane, Movement, MovementAttributes


OK = KpiStatus.OK
NA = KpiStatus.NOT_APPLICABLE
UNAVAILABLE = KpiStatus.UNAVAILABLE

INTERVAL = INTERVALS[0]


# ============================================================
# THE CASE-STUDY LAYOUT WITH ITS THREE SLIPS
# ============================================================

SLIPS = [("MOV_S_R", "APP_S"), ("MOV_W_R", "APP_W"), ("MOV_N_R", "APP_N")]

MOVEMENTS = {
    **MOVEMENT_MODELS,
    **{
        m: Movement(movement_id=m, intersection_id="INT_01", approach_id=a)
        for m, a in SLIPS
    },
}

ALL_ATTRIBUTES = {
    **ATTRIBUTES,
    **{
        m: MovementAttributes(movement_id=m, movement_type="right", control="uncontrolled")
        for m, _ in SLIPS
    },
}

SLIP_LANES = [
    ApproachLane(
        lane_id=f"LANE_{a[-1]}_SLIP",
        approach_id=a,
        lane_index=9,
        served_movement_ids=[m],
        lane_width_m=3.5,
    )
    for m, a in SLIPS
]

ALL_LANES = [
    lane.model_copy(update={"storage_length_m": 100.0}) for lane in LANES + SLIP_LANES
]


def delay(mean, vehicles, queue_duration=None, status=OK):
    return MovementDelay(
        status, vehicles, 0,
        mean if status == OK else None,
        queue_duration if status == OK else None,
        None,
    )


def all_delays(**overrides):
    """Every movement 20 s with 10 vehicles, except the overrides."""

    values = {m: delay(20.0, 10, 5.0) for m in MOVEMENTS}
    values.update(overrides)
    return {(m, INTERVAL): d for m, d in values.items()}


def all_queues(**overrides):
    """Every lane 30 m / 5 veh, except the overrides."""

    values = {lane.lane_id: LaneQueue(30.0, 5) for lane in ALL_LANES}
    values.update(overrides)
    return {(lane_id, INTERVAL): q for lane_id, q in values.items()}


# ============================================================
# GENERIC COMBINATIONS
# ============================================================

def test_weighted_mean_by_hand():
    """(10 x 3 + 40 x 1) / 4 = 17.5."""

    result = combine_weighted_mean([Part(OK, 10, 3), Part(OK, 40, 1)])

    assert result.value == pytest.approx(17.5)


def test_one_unavailable_part_makes_the_result_unavailable():
    result = combine_weighted_mean([Part(OK, 10, 3), Part(UNAVAILABLE, None)])

    assert result.status == UNAVAILABLE
    assert result.reason == PART_UNAVAILABLE_REASON
    assert result.value is None


def test_not_applicable_parts_are_left_out():
    result = combine_weighted_mean([Part(OK, 10, 3), Part(NA, None)])

    assert result.status == OK
    assert result.value == 10


def test_only_not_applicable_parts_give_not_applicable():
    result = combine_sum([Part(NA, None), Part(NA, None)])

    assert result.status == NA
    assert result.reason == NOTHING_TO_COMBINE_REASON


def test_weighted_mean_with_no_vehicles_is_not_applicable():
    assert combine_weighted_mean([Part(OK, 10, 0)]).status == NA


def test_sum_by_hand():
    assert combine_sum([Part(OK, 400), Part(OK, 0), Part(OK, 120)]).value == 520


def test_highest_names_its_lane():
    result = combine_highest(
        [Part(OK, 30, lane_id="A"), Part(OK, 70, lane_id="B", is_shared=True)]
    )

    assert result.value == 70
    assert result.measured_on_lane_id == "B"
    assert result.is_shared


def test_highest_is_never_an_average():
    assert combine_highest([Part(OK, 10), Part(OK, 90)]).value == 90


# ============================================================
# MEASURED DELAY AND QUEUE DURATION
# ============================================================

def test_approach_delay_is_weighted_by_completed_vehicles():
    """East: 300 veh at 10 s and 100 veh at 50 s: 20 s, not 30 s."""

    delays = all_delays(
        MOV_E_L=delay(50.0, 100, 5.0),
        MOV_E_T=delay(10.0, 300, 5.0),
    )

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL)

    assert out[("approach", "APP_E")].value == pytest.approx(20.0)


def test_intersection_delay_is_weighted_over_all_movements():
    delays = all_delays(MOV_N_L=delay(110.0, 10, 5.0))

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL)

    # 9 movements of 10 vehicles: (8 x 20 + 110) / 9 = 30
    assert out[("intersection", "INT_01")].value == pytest.approx(30.0)


def test_queue_duration_is_averaged_the_same_way():
    delays = all_delays(
        MOV_E_L=delay(50.0, 100, 40.0),
        MOV_E_T=delay(10.0, 300, 0.0),
    )

    out = measured_delay_rollup(
        MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL, quantity="queue_duration"
    )

    assert out[("approach", "APP_E")].value == pytest.approx(10.0)


def test_slips_are_included_in_measured_delay_with_a_note():
    delays = all_delays(MOV_S_R=delay(2.0, 30))

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL)

    # South: through 10 veh at 20 s, slip 30 veh at 2 s
    assert out[("approach", "APP_S")].value == pytest.approx((200 + 60) / 40)
    assert out[("approach", "APP_S")].uncontrolled_movements == INCLUDES_UNCONTROLLED
    assert out[("intersection", "INT_01")].uncontrolled_movements == INCLUDES_UNCONTROLLED


def test_approach_without_slip_has_no_note():
    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, all_delays(), INTERVAL)

    assert out[("approach", "APP_E")].uncontrolled_movements is None


def test_unavailable_movement_makes_approach_and_intersection_unavailable():
    delays = all_delays(MOV_W_T=delay(None, 10, status=UNAVAILABLE))

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL)

    assert out[("approach", "APP_W")].status == UNAVAILABLE
    assert out[("intersection", "INT_01")].status == UNAVAILABLE
    assert out[("approach", "APP_E")].status == OK


def test_movement_without_arrivals_is_left_out():
    delays = all_delays(MOV_E_L=delay(None, 0, status=NA))

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, delays, INTERVAL)

    assert out[("approach", "APP_E")].status == OK
    assert out[("approach", "APP_E")].value == pytest.approx(20.0)


def test_measured_delay_has_no_level_of_service_yet():
    """Graded after the runs are combined (section 7.6)."""

    out = measured_delay_rollup(MOVEMENTS, ALL_ATTRIBUTES, all_delays(), INTERVAL)

    assert out[("intersection", "INT_01")].los_grade is None


# ============================================================
# THROUGHPUT
# ============================================================

def test_throughput_is_summed():
    flows = {(m, INTERVAL): 100.0 for m in MOVEMENTS}

    out = throughput_rollup(MOVEMENTS, ALL_ATTRIBUTES, flows, INTERVAL)

    assert out[("approach", "APP_E")].value == 200
    assert out[("approach", "APP_S")].value == 200  # through + slip
    assert out[("intersection", "INT_01")].value == 900


def test_zero_throughput_is_a_real_zero():
    flows = {(m, INTERVAL): 0.0 for m in MOVEMENTS}

    out = throughput_rollup(MOVEMENTS, ALL_ATTRIBUTES, flows, INTERVAL)

    assert out[("approach", "APP_N")].status == OK
    assert out[("approach", "APP_N")].value == 0


# ============================================================
# QUEUE LENGTH AND STORAGE RATIO
# ============================================================

def test_approach_queue_is_the_longest_lane():
    queues = all_queues(LANE_E_3=LaneQueue(85.0, 12))

    out = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("approach", "APP_E")].value == 85
    assert out[("approach", "APP_E")].measured_on_lane_id == "LANE_E_3"
    assert out[("intersection", "INT_01")].measured_on_lane_id == "LANE_E_3"


def test_movement_queue_is_its_longest_lane():
    queues = all_queues(LANE_E_4=LaneQueue(60.0, 9), LANE_E_1=LaneQueue(90.0, 13))

    out = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("movement", "MOV_E_T")].value == 60
    assert out[("movement", "MOV_E_T")].measured_on_lane_id == "LANE_E_4"
    assert not out[("movement", "MOV_E_T")].is_shared


def test_shared_tag_only_when_longest_lane_is_shared():
    queues = all_queues(LANE_E_2=LaneQueue(70.0, 10))

    out = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("movement", "MOV_E_L")].measured_on_lane_id == "LANE_E_2"
    assert out[("movement", "MOV_E_L")].is_shared
    assert out[("movement", "MOV_E_T")].is_shared


def test_metres_and_vehicles_are_each_the_longest_separately():
    """A long lane of large gaps and a short lane of many cars."""

    queues = all_queues(LANE_S_1=LaneQueue(80.0, 8), LANE_S_2=LaneQueue(70.0, 11))

    metres = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL, unit="m")
    vehicles = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL, unit="veh")

    assert metres[("approach", "APP_S")].measured_on_lane_id == "LANE_S_1"
    assert vehicles[("approach", "APP_S")].measured_on_lane_id == "LANE_S_2"
    assert vehicles[("approach", "APP_S")].value == 11


def test_slip_lanes_are_included_in_the_queue():
    queues = all_queues(LANE_N_SLIP=LaneQueue(95.0, 14))

    out = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("approach", "APP_N")].measured_on_lane_id == "LANE_N_SLIP"


def test_lane_without_records_makes_the_queue_unavailable():
    queues = all_queues(LANE_W_3=None)

    out = queue_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("approach", "APP_W")].status == UNAVAILABLE
    assert out[("movement", "MOV_W_T")].status == UNAVAILABLE
    assert out[("movement", "MOV_W_L")].status == OK
    assert out[("intersection", "INT_01")].status == UNAVAILABLE


def test_storage_ratio_is_the_highest_lane():
    queues = all_queues(LANE_N_2=LaneQueue(90.0, 13))

    out = storage_ratio_rollup(ALL_LANES, MOVEMENTS, queues, INTERVAL)

    assert out[("approach", "APP_N")].value == pytest.approx(0.9)
    assert out[("approach", "APP_N")].measured_on_lane_id == "LANE_N_2"


def test_unknown_storage_length_makes_the_ratio_unavailable():
    lanes = [
        lane.model_copy(update={"storage_length_m": None})
        if lane.lane_id == "LANE_S_1" else lane
        for lane in ALL_LANES
    ]

    out = storage_ratio_rollup(lanes, MOVEMENTS, all_queues(), INTERVAL)

    assert out[("approach", "APP_S")].status == UNAVAILABLE
    assert out[("approach", "APP_E")].status == OK


# ============================================================
# HCM RESULTS
# ============================================================

def hcm(demand=None):
    capacity = results(demand)
    delays = calculate_hcm_delays([(INTERVAL, capacity)], program())[0]
    return capacity, delays


def test_hcm_approach_delay_is_weighted_by_lane_group_demand():
    """Equation 19-28."""

    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    east = [g for g in GROUPS if g.approach_id == "APP_E"]
    demand = {g.lane_group_id: capacity.lane_groups[g.lane_group_id].demand_veh_h for g in east}
    expected = sum(
        delays.lane_groups[g].control_delay_s * v for g, v in demand.items()
    ) / sum(demand.values())

    assert out[("control_delay", "approach", "APP_E")].value == pytest.approx(expected)


def test_hcm_intersection_delay_is_weighted_by_demand():
    """Equation 19-29."""

    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    ids = [g.lane_group_id for g in GROUPS]
    expected = sum(
        delays.lane_groups[g].control_delay_s * capacity.lane_groups[g].demand_veh_h
        for g in ids
    ) / sum(capacity.lane_groups[g].demand_veh_h for g in ids)

    assert out[("control_delay", "intersection", "INT_01")].value == pytest.approx(expected)


def test_hcm_level_of_service_comes_from_delay_alone():
    """South is over capacity (v/c > 1), but its approach LOS is graded
    from delay alone (note to Exhibit 19-8)."""

    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    for key, result in out.items():
        if key[0] == "control_delay":
            assert result.los_grade == level_of_service(result.value)


def test_hcm_delay_excludes_slips_with_a_note():
    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    assert out[("control_delay", "approach", "APP_S")].uncontrolled_movements == EXCLUDES_UNCONTROLLED
    assert out[("control_delay", "approach", "APP_E")].uncontrolled_movements is None
    assert out[("control_delay", "intersection", "INT_01")].uncontrolled_movements == EXCLUDES_UNCONTROLLED


def test_approach_volume_to_capacity_is_the_highest_group():
    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    east = [
        capacity.lane_groups[g.lane_group_id].volume_to_capacity
        for g in GROUPS if g.approach_id == "APP_E"
    ]

    assert out[("volume_to_capacity", "approach", "APP_E")].value == pytest.approx(max(east))


def test_approach_capacity_is_the_sum_of_groups():
    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    east = sum(
        capacity.lane_groups[g.lane_group_id].capacity_veh_h
        for g in GROUPS if g.approach_id == "APP_E"
    )

    assert out[("capacity", "approach", "APP_E")].value == pytest.approx(east)


def test_intersection_capacity_is_not_reported():
    capacity, delays = hcm()
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    assert ("capacity", "intersection", "INT_01") not in out
    assert ("volume_to_capacity", "intersection", "INT_01") not in out


def test_missing_demand_makes_hcm_approach_and_intersection_unavailable():
    capacity, delays = hcm({k: v for k, v in DEMAND.items() if k != "MOV_W_T"})
    out = hcm_rollup(GROUPS, MOVEMENTS, ALL_ATTRIBUTES, capacity, delays)

    assert out[("control_delay", "approach", "APP_W")].status == UNAVAILABLE
    assert out[("control_delay", "intersection", "INT_01")].status == UNAVAILABLE
    assert out[("control_delay", "approach", "APP_E")].status == OK


# ============================================================
# ONE INTERSECTION ONLY
# ============================================================

def test_movements_of_two_intersections_rejected():
    movements = {
        **MOVEMENTS,
        "MOV_N_R": Movement(movement_id="MOV_N_R", intersection_id="INT_02", approach_id="APP_N"),
    }

    with pytest.raises(ValueError, match="exactly one intersection"):
        measured_delay_rollup(movements, ALL_ATTRIBUTES, all_delays(), INTERVAL)
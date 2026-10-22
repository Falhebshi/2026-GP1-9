import pytest

from backend.analytics.kpi import capacity
from backend.analytics.kpi.capacity import (
    MISSING_DEMAND_REASON,
    MULTIPLE_GREENS_CRITICAL_REASON,
    NO_DEMAND_REASON,
    PERMITTED_LEFT_REASON,
    SPLIT_PHASES_REASON,
    calculate_capacity,
    distribute_demand,
    effective_green,
    lane_group_green,
    lane_utilization_factor,
    lane_width_factor,
    lane_change_probability,
    left_turn_factor,
    modified_left_turn_equivalent,
    phase_lost_time,
    saturation_flow,
    signal_timing_origin,
)
from backend.analytics.kpi.lane_groups import derive_lane_groups
from jaadah.models.kpis import InputOrigin, KpiStatus
from jaadah.models.network import (
    ApproachLane,
    Movement,
    MovementAttributes,
)
from jaadah.models.signals import SignalPhase, SignalProgram


# ============================================================
# THE CASE-STUDY LAYOUT (confirmed 17 Oct, lanes from the median)
# ============================================================

MOVEMENTS = [
    ("MOV_E_L", "APP_E", "left"),
    ("MOV_E_T", "APP_E", "through"),
    ("MOV_W_L", "APP_W", "left"),
    ("MOV_W_T", "APP_W", "through"),
    ("MOV_S_T", "APP_S", "through"),
    ("MOV_N_L", "APP_N", "left"),
]

MOVEMENT_MODELS = {
    m: Movement(movement_id=m, intersection_id="INT_01", approach_id=a)
    for m, a, _ in MOVEMENTS
}

ATTRIBUTES = {
    m: MovementAttributes(movement_id=m, movement_type=t, control="signalized")
    for m, _, t in MOVEMENTS
}


def lane(lane_id, approach_id, lane_index, served, width=3.5):
    return ApproachLane(
        lane_id=lane_id,
        approach_id=approach_id,
        lane_index=lane_index,
        served_movement_ids=served,
        lane_width_m=width,
    )


LANES = [
    lane("LANE_E_1", "APP_E", 1, ["MOV_E_L"]),
    lane("LANE_E_2", "APP_E", 2, ["MOV_E_L", "MOV_E_T"]),
    lane("LANE_E_3", "APP_E", 3, ["MOV_E_T"]),
    lane("LANE_E_4", "APP_E", 4, ["MOV_E_T"]),
    lane("LANE_W_1", "APP_W", 1, ["MOV_W_L"]),
    lane("LANE_W_2", "APP_W", 2, ["MOV_W_L", "MOV_W_T"]),
    lane("LANE_W_3", "APP_W", 3, ["MOV_W_T"]),
    lane("LANE_S_1", "APP_S", 1, ["MOV_S_T"]),
    lane("LANE_S_2", "APP_S", 2, ["MOV_S_T"]),
    lane("LANE_N_1", "APP_N", 1, ["MOV_N_L"]),
    lane("LANE_N_2", "APP_N", 2, ["MOV_N_L"]),
    lane("LANE_N_3", "APP_N", 3, ["MOV_N_L"]),
]

LANES_BY_ID = {lane.lane_id: lane for lane in LANES}

GROUPS = derive_lane_groups(LANES, list(ATTRIBUTES.values()))
GROUPS_BY_ID = {g.lane_group_id: g for g in GROUPS}
EAST_GROUPS = [g for g in GROUPS if g.approach_id == "APP_E"]


def phase(phase_id, order, served, green):
    return SignalPhase(
        phase_id=phase_id,
        sequence_order=order,
        served_movement_ids=served,
        green_time_s=green,
        yellow_time_s=3,
        all_red_time_s=2,
    )


def program(phases=None, source="baseline_model"):
    """One phase per approach; C = 120 s (greens 40 + 15 + 30 + 15)."""

    return SignalProgram(
        signal_program_id="SP_1",
        scenario_id="SCN_BASE",
        control_type="fixed_time",
        cycle_length_s=120,
        source=source,
        phases=phases or [
            phase("P_E", 0, ["MOV_E_L", "MOV_E_T"], 40),
            phase("P_N", 1, ["MOV_N_L"], 15),
            phase("P_W", 2, ["MOV_W_L", "MOV_W_T"], 30),
            phase("P_S", 3, ["MOV_S_T"], 15),
        ],
    )


DEMAND = {
    "MOV_E_L": 300,
    "MOV_E_T": 1500,
    "MOV_W_L": 200,
    "MOV_W_T": 1000,
    "MOV_S_T": 600,
    "MOV_N_L": 500,
}


def results(demand=None, signal_program=None):
    return calculate_capacity(
        GROUPS,
        LANES_BY_ID,
        MOVEMENT_MODELS,
        ATTRIBUTES,
        signal_program or program(),
        DEMAND if demand is None else demand,
    )


# ============================================================
# ADJUSTMENT FACTORS
# ============================================================

@pytest.mark.parametrize(
    "width, expected",
    [(2.9, 0.96), (3.048, 1.00), (3.5, 1.00), (3.932, 1.00), (4.0, 1.04)],
)
def test_lane_width_factor(width, expected):
    assert lane_width_factor(width) == expected


@pytest.mark.parametrize(
    "lanes, movement_type, expected",
    [
        (1, "through", 1.000),
        (2, "through", 0.952),
        (3, "through", 0.908),
        (1, "left", 1.000),
        (2, "left", 0.971),
        (1, "right", 1.000),
        (2, "right", 0.885),
    ],
)
def test_lane_utilization_factor(lanes, movement_type, expected):
    """HCM 7th edition, Exhibit 19-15."""

    assert lane_utilization_factor(lanes, movement_type) == expected


@pytest.mark.parametrize(
    "lanes, movement_type, expected",
    [(4, "through", 0.908), (3, "left", 0.971), (3, "right", 0.885)],
)
def test_more_lanes_than_listed_use_smallest_value(lanes, movement_type, expected):
    """Note to Exhibit 19-15: the smallest value of the same type."""

    assert lane_utilization_factor(lanes, movement_type) == expected


def test_lane_utilization_without_lanes_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        lane_utilization_factor(0, "through")


@pytest.mark.parametrize(
    "flow_per_lane, expected",
    [(0, 0.0), (3600 / 3.7 / 2, 1.0), (3600 / 3.7, 0.0), (2000, 0.0)],
)
def test_lane_change_probability(flow_per_lane, expected):
    """Equation 31-50: highest at medium flow, 0 at no or very high flow."""

    assert lane_change_probability(flow_per_lane) == pytest.approx(expected)


@pytest.mark.parametrize(
    "flow_per_lane, expected",
    [(0, 1.0), (3600 / 3.7 / 2, 1.05)],
)
def test_modified_left_turn_equivalent(flow_per_lane, expected):
    """Equation 31-47: E_L,m between 1.0 and E_L = 1.05."""

    assert modified_left_turn_equivalent(flow_per_lane) == pytest.approx(expected)


def test_lane_width_below_eight_feet_rejected():
    with pytest.raises(ValueError, match="below 8.0 ft"):
        lane_width_factor(2.4)


@pytest.mark.parametrize(
    "share, expected",
    [(0, 1.0), (1, 1 / 1.05), (0.5, 1 / 1.025)],
)
def test_left_turn_factor(share, expected):
    assert left_turn_factor(share) == pytest.approx(expected)


# ============================================================
# SATURATION FLOW
# ============================================================

def test_saturation_flow_of_exclusive_left_lane():
    """1,900 x 1 lane x 1.00 width x 1.000 utilisation x 1/1.05."""

    group = GROUPS_BY_ID["APP_E_L"]

    assert saturation_flow(group, LANES_BY_ID, ATTRIBUTES, 1.0) == pytest.approx(
        1900 / 1.05
    )


def test_saturation_flow_of_two_through_lanes():
    """1,900 x 2 lanes x 0.952 utilisation."""

    group = GROUPS_BY_ID["APP_E_T"]

    assert saturation_flow(group, LANES_BY_ID, ATTRIBUTES, 0.0) == pytest.approx(
        1900 * 2 * 0.952
    )


def test_saturation_flow_of_three_left_lanes():
    """North: 1,900 x 3 x 0.971 (exclusive left, smallest value) / 1.05."""

    group = GROUPS_BY_ID["APP_N_L"]

    assert saturation_flow(group, LANES_BY_ID, ATTRIBUTES, 1.0) == pytest.approx(
        1900 * 3 * 0.971 / 1.05
    )


def test_saturation_flow_uses_average_lane_width():
    """Widths 2.9 m and 3.3 m average 3.1 m: normal width (1.00)."""

    lanes = {
        "LANE_E_3": lane("LANE_E_3", "APP_E", 3, ["MOV_E_T"], width=2.9),
        "LANE_E_4": lane("LANE_E_4", "APP_E", 4, ["MOV_E_T"], width=3.3),
    }

    assert saturation_flow(
        GROUPS_BY_ID["APP_E_T"], lanes, ATTRIBUTES, 0.0
    ) == pytest.approx(1900 * 2 * 0.952)


def test_narrow_lanes_reduce_saturation_flow():
    lanes = {"LANE_E_1": lane("LANE_E_1", "APP_E", 1, ["MOV_E_L"], width=3.0)}

    assert saturation_flow(
        GROUPS_BY_ID["APP_E_L"], lanes, ATTRIBUTES, 1.0
    ) == pytest.approx(1900 * 0.96 / 1.05)


@pytest.mark.parametrize("share", [-0.1, 1.1])
def test_invalid_left_turn_share_rejected(share):
    with pytest.raises(ValueError, match="between 0 and 1"):
        saturation_flow(GROUPS_BY_ID["APP_E_LT"], LANES_BY_ID, ATTRIBUTES, share)


# ============================================================
# DEMAND DISTRIBUTION (section 9.4)
# ============================================================

def east(left, through):
    return distribute_demand(
        EAST_GROUPS,
        LANES_BY_ID,
        ATTRIBUTES,
        {"MOV_E_L": left, "MOV_E_T": through},
    )


def test_few_left_turners_all_use_the_left_lane():
    """
    300 lefts fit in the left lane (v/s 300 / 1,809.5 = 0.166), so the
    shared lane carries only through traffic. Through spreads over the
    shared lane and the two through lanes with the per-lane saturation
    flows of Chapter 31 (no lane utilisation): 1,500 / (1,900 + 3,800)
    = 0.263, so 500 in the shared lane and 1,000 in the through lanes.
    """

    result = east(300, 1500)

    assert result.flows[("MOV_E_L", "APP_E_L")] == pytest.approx(300)
    assert result.flows[("MOV_E_L", "APP_E_LT")] == pytest.approx(0)
    assert result.flows[("MOV_E_T", "APP_E_LT")] == pytest.approx(500, abs=0.2)
    assert result.flows[("MOV_E_T", "APP_E_T")] == pytest.approx(1000, abs=0.2)


def test_left_lane_never_carries_more_than_left_demand():
    """
    The physical rule added to Chapter 31 Step G: with few left-turners
    the exclusive left lane is simply less busy than the others.
    """

    result = east(300, 1500)
    ratios = {
        g: result.group_flows[g] / result.lane_choice_saturation_flows[g]
        for g in ("APP_E_L", "APP_E_LT", "APP_E_T")
    }

    assert result.group_flows["APP_E_L"] == pytest.approx(300)
    assert ratios["APP_E_L"] < ratios["APP_E_LT"]


def test_many_left_turners_spill_into_the_shared_lane():
    result = east(600, 1500)

    assert result.flows[("MOV_E_L", "APP_E_LT")] > 0
    assert result.left_turn_shares["APP_E_LT"] > 0


def test_all_groups_used_end_with_the_same_flow_ratio():
    result = east(600, 1500)

    ratios = [
        result.group_flows[g] / result.lane_choice_saturation_flows[g]
        for g in ("APP_E_L", "APP_E_LT", "APP_E_T")
    ]

    assert max(ratios) - min(ratios) < 1e-3


def test_demand_is_kept():
    result = east(600, 1500)

    left = sum(v for (m, _), v in result.flows.items() if m == "MOV_E_L")
    through = sum(v for (m, _), v in result.flows.items() if m == "MOV_E_T")

    assert left == pytest.approx(600)
    assert through == pytest.approx(1500)


def test_shared_lane_saturation_flow_follows_its_left_share():
    result = east(600, 1500)

    share = result.left_turn_shares["APP_E_LT"]
    equivalent = result.shared_left_turn_equivalent

    assert result.saturation_flows["APP_E_LT"] == pytest.approx(
        1900 / (1 + share * (equivalent - 1))
    )


def test_shared_lane_uses_modified_equivalent():
    """
    v_app = (600 + 1,500) / 3 lanes serving through traffic = 700;
    P_lc = 1 - (2 x 700 / 973 - 1)^2; E_L,m = 0.05 x P_lc + 1.
    """

    result = east(600, 1500)

    p_lc = 1 - (2 * 700 / (3600 / 3.7) - 1) ** 2

    assert result.shared_left_turn_equivalent == pytest.approx(0.05 * p_lc + 1)


def test_exclusive_through_lanes_use_lane_utilization_for_capacity():
    result = east(600, 1500)

    assert result.lane_choice_saturation_flows["APP_E_T"] == pytest.approx(3800)
    assert result.saturation_flows["APP_E_T"] == pytest.approx(3800 * 0.952)


def test_no_flows_are_negative():
    result = east(600, 1500)

    assert all(flow >= 0 for flow in result.flows.values())


def test_zero_left_demand():
    result = east(0, 1500)

    assert result.group_flows["APP_E_L"] == 0
    assert result.left_turn_shares["APP_E_L"] == 1.0


def test_movement_with_one_group_gets_all_its_demand():
    north = [g for g in GROUPS if g.approach_id == "APP_N"]

    result = distribute_demand(north, LANES_BY_ID, ATTRIBUTES, {"MOV_N_L": 500})

    assert result.group_flows["APP_N_L"] == pytest.approx(500)


def test_missing_demand_rejected():
    with pytest.raises(ValueError, match="no demand for movement MOV_E_T"):
        distribute_demand(EAST_GROUPS, LANES_BY_ID, ATTRIBUTES, {"MOV_E_L": 300})


def test_negative_demand_rejected():
    with pytest.raises(ValueError, match="must not be negative"):
        east(-1, 1500)


def test_distribution_that_does_not_settle_rejected(monkeypatch):
    monkeypatch.setattr(capacity, "DISTRIBUTION_MAX_ROUNDS", 1)

    with pytest.raises(ValueError, match="did not settle within 1 rounds"):
        east(600, 1500)


# ============================================================
# GREEN TIME (section 9.5)
# ============================================================

def test_effective_green_equals_displayed_green():
    """g = G - l1 + e with l1 = e = 2.0 s (Equation 19-3)."""

    assert effective_green(phase("P", 0, ["MOV_E_T"], 40)) == 40


@pytest.mark.parametrize("yellow, all_red, expected", [(3, 2, 5), (4, 2, 6)])
def test_phase_lost_time(yellow, all_red, expected):
    """l1 + (Y + Rc - e) = 2 + (Y + Rc - 2)."""

    timing = SignalPhase(
        phase_id="P",
        sequence_order=0,
        served_movement_ids=["MOV_E_T"],
        green_time_s=40,
        yellow_time_s=yellow,
        all_red_time_s=all_red,
    )

    assert phase_lost_time(timing) == expected


def test_green_of_a_lane_group():
    assert lane_group_green(GROUPS_BY_ID["APP_E_LT"], program()) == 40


def test_green_of_shared_lane_split_over_phases_is_none():
    split = program([
        phase("P_ET", 0, ["MOV_E_T"], 30),
        phase("P_EL", 1, ["MOV_E_L"], 10),
        phase("P_N", 2, ["MOV_N_L"], 15),
        phase("P_W", 3, ["MOV_W_L", "MOV_W_T"], 20),
        phase("P_S", 4, ["MOV_S_T"], 20),
    ])

    assert lane_group_green(GROUPS_BY_ID["APP_E_LT"], split) is None
    assert lane_group_green(GROUPS_BY_ID["APP_E_L"], split) == 10


# ============================================================
# CAPACITY AND VOLUME-TO-CAPACITY RATIO
# ============================================================

def test_lane_group_capacity_and_ratio():
    """c = s x g / C = 1,809.5 x 40 / 120; X = 300 / c."""

    group = results().lane_groups["APP_E_L"]

    expected_capacity = 1900 / 1.05 * 40 / 120

    assert group.status == KpiStatus.OK
    assert group.green_s == 40
    assert group.capacity_veh_h == pytest.approx(expected_capacity)
    assert group.volume_to_capacity == pytest.approx(300 / expected_capacity)


def test_flow_ratio_property():
    group = results().lane_groups["APP_S_T"]

    assert group.flow_ratio == pytest.approx(600 / (1900 * 2 * 0.952))


def test_ratio_above_one_is_reported():
    """South: 600 veh/h against 452 veh/h of capacity."""

    assert results().lane_groups["APP_S_T"].volume_to_capacity > 1


def test_every_lane_group_has_a_result():
    assert set(results().lane_groups) == set(GROUPS_BY_ID)


# ============================================================
# MOVEMENT VALUES (section 9.6)
# ============================================================

def test_movement_using_shared_lane_is_tagged():
    movement = results().movements["MOV_E_T"]

    assert movement.shared_lane_group_id == "APP_E_LT"


def test_movement_not_using_shared_lane_is_not_tagged():
    """With 300 lefts, none use the shared lane."""

    assert results().movements["MOV_E_L"].shared_lane_group_id is None


def test_movement_ratio_is_highest_of_the_groups_it_uses():
    result = results()

    used = ("APP_E_LT", "APP_E_T")

    assert result.movements["MOV_E_T"].volume_to_capacity == pytest.approx(
        max(result.lane_groups[g].volume_to_capacity for g in used)
    )


def test_movement_capacity_is_demand_over_ratio():
    movement = results().movements["MOV_E_T"]

    assert movement.capacity_veh_h == pytest.approx(
        1500 / movement.volume_to_capacity
    )


def test_movement_saturation_flow_is_demand_over_flow_ratio():
    result = results()
    movement = result.movements["MOV_E_T"]

    assert movement.saturation_flow_veh_h == pytest.approx(
        1500 / result.lane_groups["APP_E_T"].flow_ratio, rel=1e-4
    )


def test_movement_with_zero_demand_is_not_applicable():
    movement = results({**DEMAND, "MOV_N_L": 0}).movements["MOV_N_L"]

    assert movement.status == KpiStatus.NOT_APPLICABLE
    assert movement.reason == NO_DEMAND_REASON
    assert movement.volume_to_capacity is None


# ============================================================
# CRITICAL VOLUME-TO-CAPACITY RATIO
# ============================================================

def test_critical_ratio_by_hand():
    """
    Highest v/s per phase, times C / (C - L) with L = 4 x 5 s = 20 s.
    """

    result = results()
    groups = result.lane_groups

    per_phase = [
        max(groups[g].flow_ratio for g in ("APP_E_L", "APP_E_LT", "APP_E_T")),
        groups["APP_N_L"].flow_ratio,
        max(groups[g].flow_ratio for g in ("APP_W_L", "APP_W_LT", "APP_W_T")),
        groups["APP_S_T"].flow_ratio,
    ]

    assert result.critical_status == KpiStatus.OK
    assert result.critical_volume_to_capacity == pytest.approx(
        sum(per_phase) * 120 / 100
    )


def test_critical_ratio_can_be_below_one_while_a_group_is_above():
    result = results()

    assert result.critical_volume_to_capacity < 1
    assert result.lane_groups["APP_S_T"].volume_to_capacity > 1


# ============================================================
# UNAVAILABLE RESULTS
# ============================================================

def test_missing_demand_makes_its_approach_unavailable():
    demand = {k: v for k, v in DEMAND.items() if k != "MOV_W_T"}

    result = results(demand)

    for group_id in ("APP_W_L", "APP_W_LT", "APP_W_T"):
        assert result.lane_groups[group_id].status == KpiStatus.UNAVAILABLE
        assert result.lane_groups[group_id].reason == MISSING_DEMAND_REASON

    assert result.lane_groups["APP_E_T"].status == KpiStatus.OK
    assert result.movements["MOV_W_T"].status == KpiStatus.UNAVAILABLE
    assert result.critical_status == KpiStatus.UNAVAILABLE


def test_permitted_left_turn_is_unavailable():
    """East-left runs with West-through: it must turn through gaps."""

    permitted = program([
        phase("P_EW", 0, ["MOV_E_L", "MOV_E_T", "MOV_W_T"], 40),
        phase("P_WL", 1, ["MOV_W_L"], 30),
        phase("P_N", 2, ["MOV_N_L"], 15),
        phase("P_S", 3, ["MOV_S_T"], 15),
    ])

    result = results(signal_program=permitted)

    assert result.lane_groups["APP_E_L"].reason == PERMITTED_LEFT_REASON
    assert result.lane_groups["APP_E_LT"].reason == PERMITTED_LEFT_REASON
    assert result.lane_groups["APP_E_T"].status == KpiStatus.OK
    assert result.movements["MOV_E_L"].reason == (
        capacity.LANE_GROUP_UNAVAILABLE_REASON
    )


def test_shared_lane_split_over_phases_is_unavailable():
    split = program([
        phase("P_ET", 0, ["MOV_E_T"], 30),
        phase("P_EL", 1, ["MOV_E_L"], 10),
        phase("P_N", 2, ["MOV_N_L"], 15),
        phase("P_W", 3, ["MOV_W_L", "MOV_W_T"], 20),
        phase("P_S", 4, ["MOV_S_T"], 20),
    ])

    result = results(signal_program=split)

    assert result.lane_groups["APP_E_LT"].reason == SPLIT_PHASES_REASON
    assert result.lane_groups["APP_E_L"].status == KpiStatus.OK


# ============================================================
# SIGNAL TIMING ORIGIN (section 9.8)
# ============================================================

@pytest.mark.parametrize(
    "source, expected",
    [
        ("observed", InputOrigin.OBSERVED),
        ("baseline_model", InputOrigin.MODELLED_ASSUMPTION),
        ("intervention", InputOrigin.MODELLED_ASSUMPTION),
    ],
)
def test_signal_timing_origin(source, expected):
    assert signal_timing_origin(program(source=source)) == expected


# ============================================================
# MOVEMENTS SERVED IN MORE THAN ONE PHASE (PR #33 review)
# ============================================================

def two_greens_for_north():
    """North left gets 5 s twice (phases 2 and 5); C stays 120 s."""

    return program(
        phases=[
            phase("P_E", 0, ["MOV_E_L", "MOV_E_T"], 40),
            phase("P_N1", 1, ["MOV_N_L"], 5),
            phase("P_W", 2, ["MOV_W_L", "MOV_W_T"], 30),
            phase("P_S", 3, ["MOV_S_T"], 15),
            phase("P_N2", 4, ["MOV_N_L"], 5),
        ]
    )


def through_only_phase_for_east():
    """East left + through for 30 s, then East through alone for 5 s."""

    return program(
        phases=[
            phase("P_E", 0, ["MOV_E_L", "MOV_E_T"], 30),
            phase("P_ET", 1, ["MOV_E_T"], 5),
            phase("P_N", 2, ["MOV_N_L"], 15),
            phase("P_W", 3, ["MOV_W_L", "MOV_W_T"], 30),
            phase("P_S", 4, ["MOV_S_T"], 15),
        ]
    )


def test_baseline_has_one_green_per_lane_group():
    assert all(g.green_periods == 1 for g in results().lane_groups.values())


def test_two_greens_keep_capacity():
    """c = s x (g1 + g2) / C is correct for capacity."""

    north = results(signal_program=two_greens_for_north()).lane_groups["APP_N_L"]

    assert north.status == KpiStatus.OK
    assert north.green_periods == 2
    assert north.green_s == pytest.approx(5 + 5)
    assert north.capacity_veh_h == pytest.approx(north.saturation_flow_veh_h * 10 / 120)


def test_two_greens_make_critical_ratio_unavailable():
    """North's demand would be counted in both of its phases."""

    result = results(signal_program=two_greens_for_north())

    assert result.critical_status == KpiStatus.UNAVAILABLE
    assert result.critical_reason == MULTIPLE_GREENS_CRITICAL_REASON
    assert result.critical_volume_to_capacity is None


def test_two_greens_leave_other_groups_alone():
    result = results(signal_program=two_greens_for_north())

    assert result.lane_groups["APP_E_T"].status == KpiStatus.OK
    assert result.lane_groups["APP_E_T"].green_periods == 1


def test_shared_lane_with_a_through_only_phase_is_unavailable():
    """
    The shared lane's through cars also move in the through-only phase,
    which the lane group's green would leave out.
    """

    result = results(signal_program=through_only_phase_for_east())
    shared = result.lane_groups["APP_E_LT"]

    assert shared.status == KpiStatus.UNAVAILABLE
    assert shared.reason == SPLIT_PHASES_REASON


def test_through_only_phase_adds_green_to_exclusive_through_lanes():
    result = results(signal_program=through_only_phase_for_east())

    through = result.lane_groups["APP_E_T"]
    left = result.lane_groups["APP_E_L"]

    assert through.green_periods == 2
    assert through.green_s == pytest.approx(30 + 5)
    assert left.green_periods == 1
    assert left.status == KpiStatus.OK

from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi.capacity import LaneGroupCapacity
from backend.analytics.kpi.hcm_delay import (
    CHAIN_BROKEN_REASON,
    FULL_CYCLE_GREEN_REASON,
    MULTIPLE_GREENS_REASON,
    NO_CAPACITY_REASON,
    NO_DEMAND_REASON,
    calculate_hcm_delays,
    incremental_delay,
    initial_queue_delay,
    lane_group_delay,
    progression_factor,
    uniform_delay,
)
from backend.analytics.kpi.intervals import analysis_intervals
from backend.analytics.kpi.kpi_tests.test_capacity import (
    DEMAND,
    program,
    results,
    two_greens_for_north,
)
from jaadah.models.kpis import KpiStatus, LevelOfServiceGrade
from jaadah.models.signals import SignalPhase


RIYADH = timezone(timedelta(hours=3))

INTERVALS = analysis_intervals(
    datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
    datetime(2026, 10, 14, 9, 0, tzinfo=RIYADH),
)


def group(demand, capacity, green=40.0, group_id="APP_X_T"):
    """A lane group result with the given demand, capacity and green."""

    return LaneGroupCapacity(
        lane_group_id=group_id,
        status=KpiStatus.OK,
        reason=None,
        demand_veh_h=demand,
        saturation_flow_veh_h=capacity * 120 / green,
        green_s=green,
        capacity_veh_h=capacity,
        volume_to_capacity=demand / capacity,
    )


def chain(south_demands):
    """Capacity results for consecutive intervals, varying South."""

    return [
        (interval, results({**DEMAND, "MOV_S_T": south}))
        for interval, south in zip(INTERVALS, south_demands)
    ]


# ============================================================
# PROGRESSION FACTOR AND UNIFORM DELAY
# ============================================================

@pytest.mark.parametrize("green_ratio", [0.2, 0.333, 0.5])
@pytest.mark.parametrize("ratio", [0.3, 0.8, 1.2])
def test_random_arrivals_give_progression_factor_one(green_ratio, ratio):
    """Platoon ratio 1.0 (arrival type 3): PF = 1 (Equation 19-20)."""

    assert progression_factor(green_ratio, ratio) == pytest.approx(1.0)


def test_favourable_progression_lowers_the_factor():
    assert progression_factor(0.333, 0.8, platoon_ratio=1.33) < 1


def test_uniform_delay_by_hand():
    """0.5 x 120 x (1 - 1/3)^2 / (1 - 0.8/3) = 36.36 s."""

    assert uniform_delay(120, 40, 0.8) == pytest.approx(
        0.5 * 120 * (2 / 3) ** 2 / (1 - 0.8 / 3)
    )


def test_uniform_delay_stops_growing_at_capacity():
    """min(1, X): above capacity d1 equals its value at X = 1."""

    assert uniform_delay(120, 40, 1.5) == pytest.approx(uniform_delay(120, 40, 1.0))


# ============================================================
# INCREMENTAL DELAY
# ============================================================

def test_incremental_delay_by_hand():
    """900 x 0.25 x [(0.8 - 1) + sqrt(0.04 + 8 x 0.5 x 0.8 / (600 x 0.25))]."""

    expected = 900 * 0.25 * (-0.2 + (0.04 + 8 * 0.5 * 0.8 / 150) ** 0.5)

    assert incremental_delay(480, 600) == pytest.approx(expected)


def test_incremental_delay_grows_quickly_above_capacity():
    assert incremental_delay(720, 600) > 5 * incremental_delay(480, 600)


# ============================================================
# INITIAL QUEUE DELAY (Equations 19-44 to 19-49)
# ============================================================

def test_no_initial_queue_and_spare_capacity_gives_no_d3():
    result = initial_queue_delay(0, 400, 600)

    assert result.delay_s == 0
    assert result.residual_queue_veh == 0


def test_no_initial_queue_over_capacity_leaves_a_queue_but_no_d3():
    """The overflow of this interval is in d2; d3 is only for Qb."""

    result = initial_queue_delay(0, 600, 452.2)

    assert result.delay_s == pytest.approx(0)
    assert result.residual_queue_veh == pytest.approx(0.25 * (600 - 452.2))


def test_initial_queue_over_capacity_by_hand():
    """
    Qb = 37, v = 600, c = 452.2: Qeo = 0.25 x 147.8, t_A = T,
    Qe = Qb + Qeo; d3 by Equation 19-44.
    """

    qb, v, c, t = 37.0, 600.0, 452.2, 0.25
    qeo = t * (v - c)
    qe = qb + qeo
    expected = 3600 / (v * t) * (
        t * (qb + qe - qeo) / 2 + (qe ** 2 - qeo ** 2) / (2 * c) - qb ** 2 / (2 * c)
    )

    result = initial_queue_delay(qb, v, c)

    assert result.delay_s == pytest.approx(expected)
    assert result.residual_queue_veh == pytest.approx(qe)


def test_initial_queue_cleared_within_the_interval():
    """Qb = 20, spare 200 veh/h: cleared after 0.1 h, Qe = 0."""

    result = initial_queue_delay(20, 400, 600)

    assert result.unmet_demand_duration_h == pytest.approx(0.1)
    assert result.residual_queue_veh == pytest.approx(0)
    assert result.delay_s > 0


def test_initial_queue_not_cleared_within_the_interval():
    """Qb = 80, spare 200 veh/h: only 50 served in 15 minutes."""

    result = initial_queue_delay(80, 400, 600)

    assert result.unmet_demand_duration_h == pytest.approx(0.25)
    assert result.residual_queue_veh == pytest.approx(30)


# ============================================================
# ONE LANE GROUP
# ============================================================

def test_control_delay_is_the_sum_of_three_terms():
    delay = lane_group_delay(group(480, 600), 120, initial_queue_veh=10)

    assert delay.control_delay_s == pytest.approx(
        delay.uniform_delay_s + delay.incremental_delay_s + delay.initial_queue_delay_s
    )


def test_without_initial_queue_d1_is_the_baseline():
    delay = lane_group_delay(group(480, 600), 120, initial_queue_veh=0)

    assert delay.uniform_delay_s == pytest.approx(uniform_delay(120, 40, 0.8))
    assert delay.initial_queue_delay_s == 0


def test_initial_queue_raises_d1_towards_the_saturated_value():
    """Equation 19-40: saturated for the unmet-demand part of T."""

    without = lane_group_delay(group(400, 600), 120, initial_queue_veh=0)
    with_queue = lane_group_delay(group(400, 600), 120, initial_queue_veh=20)

    saturated = uniform_delay(120, 40, 1.0)
    expected = saturated * 0.1 / 0.25 + without.uniform_delay_s * 0.15 / 0.25

    assert with_queue.uniform_delay_s == pytest.approx(expected)


def test_over_capacity_group_is_los_f():
    delay = lane_group_delay(group(720, 600), 120, initial_queue_veh=0)

    assert delay.los_grade == LevelOfServiceGrade.F


def test_group_without_demand_is_not_applicable_but_keeps_draining():
    """No demand: no delay, but the queue still empties at capacity."""

    delay = lane_group_delay(group(0, 600), 120, initial_queue_veh=200)

    assert delay.status == KpiStatus.NOT_APPLICABLE
    assert delay.reason == NO_DEMAND_REASON
    assert delay.residual_queue_veh == pytest.approx(200 - 600 * 0.25)


# ============================================================
# THE ANALYSIS PERIOD: RESIDUAL QUEUE CARRIED FORWARD
# ============================================================

def test_first_interval_starts_without_initial_queue():
    first = calculate_hcm_delays(chain([600]), program())[0]

    assert first.lane_groups["APP_S_T"].initial_queue_veh == 0


def test_residual_queue_becomes_next_initial_queue():
    out = calculate_hcm_delays(chain([600, 600, 300, 300]), program())

    for previous, following in zip(out, out[1:]):
        assert following.lane_groups["APP_S_T"].initial_queue_veh == pytest.approx(
            previous.lane_groups["APP_S_T"].residual_queue_veh
        )


def test_queue_grows_while_over_capacity_and_clears_after():
    """South: 600, 600 (over 452 veh/h), then 300, 300."""

    out = calculate_hcm_delays(chain([600, 600, 300, 300]), program())
    queues = [r.lane_groups["APP_S_T"].residual_queue_veh for r in out]

    assert queues[0] < queues[1]
    assert queues[2] < queues[1]
    assert queues[3] == pytest.approx(0)


def test_d3_appears_only_after_an_overloaded_interval():
    out = calculate_hcm_delays(chain([600, 600, 300, 300]), program())

    assert out[0].lane_groups["APP_S_T"].initial_queue_delay_s == pytest.approx(0)
    assert out[1].lane_groups["APP_S_T"].initial_queue_delay_s > 0


def test_other_lane_groups_are_not_affected():
    out = calculate_hcm_delays(chain([600, 600, 300, 300]), program())

    east = [r.lane_groups["APP_E_T"].control_delay_s for r in out]

    assert max(east) == pytest.approx(min(east))


def test_intervals_must_be_consecutive():
    gap = [chain([600])[0], (INTERVALS[2], results(DEMAND))]

    with pytest.raises(ValueError, match="consecutive"):
        calculate_hcm_delays(gap, program())


def test_unavailable_group_breaks_its_chain():
    """Without West-through demand, West has no capacity at 08:15, so
    its initial queue at 08:30 is unknown."""

    demand_without_west = {k: v for k, v in DEMAND.items() if k != "MOV_W_T"}

    capacity = [
        (INTERVALS[0], results(DEMAND)),
        (INTERVALS[1], results(demand_without_west)),
        (INTERVALS[2], results(DEMAND)),
    ]

    out = calculate_hcm_delays(capacity, program())

    assert out[1].lane_groups["APP_W_T"].reason == NO_CAPACITY_REASON
    assert out[2].lane_groups["APP_W_T"].reason == CHAIN_BROKEN_REASON
    assert out[2].lane_groups["APP_E_T"].status == KpiStatus.OK


# ============================================================
# MOVEMENTS
# ============================================================

def test_movement_delay_is_weighted_by_its_flow_in_each_group():
    capacity = results(DEMAND)
    out = calculate_hcm_delays([(INTERVALS[0], capacity)], program())[0]

    flows = {
        g: f for (m, g), f in capacity.flows.items() if m == "MOV_E_T" and f > 0
    }
    expected = sum(
        out.lane_groups[g].control_delay_s * f for g, f in flows.items()
    ) / sum(flows.values())

    assert out.movements["MOV_E_T"].control_delay_s == pytest.approx(expected)


def test_movement_with_single_group_has_its_delay():
    out = calculate_hcm_delays(chain([600]), program())[0]

    assert out.movements["MOV_S_T"].control_delay_s == pytest.approx(
        out.lane_groups["APP_S_T"].control_delay_s
    )


def test_movement_without_capacity_is_not_reported():
    demand_without_west = {k: v for k, v in DEMAND.items() if k != "MOV_W_T"}

    out = calculate_hcm_delays(
        [(INTERVALS[0], results(demand_without_west))], program()
    )[0]

    assert out.movements["MOV_W_T"].status == KpiStatus.UNAVAILABLE


# ============================================================
# TWO GREENS PER CYCLE (PR #33 review)
# ============================================================

def test_two_greens_have_no_hcm_delay_in_any_interval():
    """Uniform delay assumes one green per cycle."""

    timing = two_greens_for_north()
    capacity = [(i, results(signal_program=timing)) for i in INTERVALS]

    out = calculate_hcm_delays(capacity, timing)

    for interval_result in out:
        north = interval_result.lane_groups["APP_N_L"]
        assert north.status == KpiStatus.UNAVAILABLE
        assert north.reason == MULTIPLE_GREENS_REASON


def test_two_greens_leave_other_delays_alone():
    timing = two_greens_for_north()
    out = calculate_hcm_delays([(INTERVALS[0], results(signal_program=timing))], timing)[0]

    assert out.lane_groups["APP_E_T"].status == KpiStatus.OK
    assert out.movements["MOV_N_L"].status == KpiStatus.UNAVAILABLE


# ============================================================
# GREEN FOR THE WHOLE CYCLE (PR #33 review)
# ============================================================

def always_green_south():
    """One phase, South through, 120 s green with no yellow or all-red."""

    return program(
        phases=[
            SignalPhase(
                phase_id="P_S",
                sequence_order=0,
                served_movement_ids=["MOV_S_T"],
                green_time_s=120,
                yellow_time_s=0,
                all_red_time_s=0,
            )
        ]
    )


@pytest.mark.parametrize("green", [120, 130, 0])
def test_uniform_delay_rejects_green_outside_the_cycle(green):
    """The reviewer's example, uniform_delay(120, 120, 0.5), no longer divides by zero."""

    with pytest.raises(ValueError, match="shorter than cycle_s"):
        uniform_delay(120, green, 0.5)


def test_whole_cycle_green_has_no_hcm_delay():
    timing = always_green_south()
    capacity = [(i, results(signal_program=timing)) for i in INTERVALS[:2]]

    out = calculate_hcm_delays(capacity, timing)

    for interval_result in out:
        south = interval_result.lane_groups["APP_S_T"]
        assert south.status == KpiStatus.UNAVAILABLE
        assert south.reason == FULL_CYCLE_GREEN_REASON


def test_whole_cycle_green_keeps_capacity():
    """c = s x g / C = s."""

    south = results(signal_program=always_green_south()).lane_groups["APP_S_T"]

    assert south.status == KpiStatus.OK
    assert south.capacity_veh_h == pytest.approx(south.saturation_flow_veh_h)

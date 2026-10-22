"""
HCM control delay and level of service.

Control delay d = d1 + d2 + d3 (HCM 7th edition, Equation 19-18):
- d1 uniform delay (Equations 19-19 to 19-21, adjusted for an initial
  queue with Equations 19-37 to 19-41),
- d2 incremental delay (Equations 19-26 and 19-27),
- d3 initial queue delay (Equations 19-44 to 19-49).

Uniform delay assumes one green per cycle, shorter than the cycle: a
lane group whose movements are served in more than one phase, or that
is green for the whole cycle, has no HCM delay.

The intervals of the analysis period are calculated in order: the
residual queue at the end of one interval is the initial queue of the
next (a multiple-period analysis). The first interval starts with no
initial queue. See docs/kpi_engine.md section 10.

This is a prediction from the HCM formulas, used as a cross-check of
the control delay measured in the simulation (delay.py).
"""

import math
from typing import NamedTuple

from backend.analytics.kpi.capacity import CapacityResults, LaneGroupCapacity
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.parameters import (
    ANALYSIS_INTERVAL_S,
    INCREMENTAL_DELAY_FACTOR,
    PLATOON_RATIO,
    UPSTREAM_FILTERING_FACTOR,
    level_of_service,
)
from jaadah.models.kpis import KpiStatus, LevelOfServiceGrade
from jaadah.models.signals import SignalProgram


ANALYSIS_PERIOD_H = ANALYSIS_INTERVAL_S / 3600

NO_DEMAND_REASON = "no demand in this interval"
NO_CAPACITY_REASON = "the lane group has no capacity result"
FULL_CYCLE_GREEN_REASON = (
    "green for the whole cycle: not a signal-controlled movement"
)
MULTIPLE_GREENS_REASON = (
    "movement served in more than one phase: HCM delay not supported yet"
)
CHAIN_BROKEN_REASON = (
    "the initial queue is unknown because an earlier interval of this "
    "lane group has no result"
)


class LaneGroupDelay(NamedTuple):
    """HCM delay of one lane group in one interval."""

    lane_group_id: str
    status: KpiStatus
    reason: str | None
    uniform_delay_s: float | None
    incremental_delay_s: float | None
    initial_queue_delay_s: float | None
    control_delay_s: float | None
    los_grade: LevelOfServiceGrade | None
    initial_queue_veh: float | None
    residual_queue_veh: float | None


class HcmMovementDelay(NamedTuple):
    """
    HCM delay of one movement in one interval: the delays of the lane
    groups it uses, weighted by its flow in each (as Equation 19-28
    weights lane groups by their flow).
    """

    movement_id: str
    status: KpiStatus
    reason: str | None
    control_delay_s: float | None
    los_grade: LevelOfServiceGrade | None


class HcmDelayResults(NamedTuple):
    """All HCM delay results of the intersection in one interval."""

    interval: AnalysisInterval
    lane_groups: dict[str, LaneGroupDelay]
    movements: dict[str, HcmMovementDelay]


# ============================================================
# THE THREE DELAY TERMS
# ============================================================

def progression_factor(
    green_ratio: float,
    volume_to_capacity: float,
    platoon_ratio: float = PLATOON_RATIO,
) -> float:
    """
    Progression adjustment factor PF (HCM Equations 19-20 and 19-21),
    with P = platoon ratio x g/C (Equation 19-15). With random arrivals
    (platoon ratio 1.0) PF is exactly 1.
    """

    arriving_on_green = platoon_ratio * green_ratio
    flow_ratio = min(1.0, volume_to_capacity) * green_ratio

    return (
        (1 - arriving_on_green) / (1 - green_ratio)
        * (1 - flow_ratio) / (1 - min(1.0, volume_to_capacity) * arriving_on_green)
        * (
            1
            + flow_ratio
            * (1 - arriving_on_green / green_ratio)
            / (1 - green_ratio)
        )
    )


def uniform_delay(
    cycle_s: float,
    green_s: float,
    volume_to_capacity: float,
) -> float:
    """
    Uniform delay d1 without an initial queue (HCM Equation 19-19):
    PF x 0.5 C (1 - g/C)^2 / (1 - min(1, X) g/C).

    Raises ValueError unless the green is shorter than the cycle: with
    green for the whole cycle there is no red, and the equation divides
    by zero.
    """

    if not 0 < green_s < cycle_s:
        raise ValueError("green_s must be above 0 and shorter than cycle_s")

    green_ratio = green_s / cycle_s

    return (
        progression_factor(green_ratio, volume_to_capacity)
        * 0.5 * cycle_s * (1 - green_ratio) ** 2
        / (1 - min(1.0, volume_to_capacity) * green_ratio)
    )


def incremental_delay(demand_veh_h: float, capacity_veh_h: float) -> float:
    """
    Incremental delay d2 (HCM Equations 19-26 and 19-27):
    900 T [(X - 1) + sqrt((X - 1)^2 + 8 k I X / (c T))].
    """

    ratio = demand_veh_h / capacity_veh_h
    t = ANALYSIS_PERIOD_H

    return 900 * t * (
        (ratio - 1)
        + math.sqrt(
            (ratio - 1) ** 2
            + 8 * INCREMENTAL_DELAY_FACTOR * UPSTREAM_FILTERING_FACTOR * ratio
            / (capacity_veh_h * t)
        )
    )


class InitialQueueResult(NamedTuple):
    """Initial queue delay d3 and the queue left at the end (veh)."""

    delay_s: float
    residual_queue_veh: float
    unmet_demand_duration_h: float


def initial_queue_delay(
    initial_queue_veh: float,
    demand_veh_h: float,
    capacity_veh_h: float,
) -> InitialQueueResult:
    """
    Initial queue delay d3 and residual queue Qe (HCM Equations 19-44
    to 19-49):
    d3 = 3,600 / (v T) x (t_A (Qb + Qe - Qeo) / 2
                          + (Qe^2 - Qeo^2) / (2 c_A) - Qb^2 / (2 c_A)).

    With pretimed control and no permitted left turns the average
    capacity c_A equals the capacity c (Equations 19-42 and 19-43 with
    a saturated capacity equal to c).
    """

    t = ANALYSIS_PERIOD_H
    queue = initial_queue_veh

    if demand_veh_h >= capacity_veh_h:
        end_queue_without_initial = t * (demand_veh_h - capacity_veh_h)
        duration = t
    else:
        end_queue_without_initial = 0.0
        duration = (
            min(queue / (capacity_veh_h - demand_veh_h), t) if queue > 0 else 0.0
        )

    residual = queue + duration * (demand_veh_h - capacity_veh_h)

    delay = 3600 / (demand_veh_h * t) * (
        duration * (queue + residual - end_queue_without_initial) / 2
        + (residual ** 2 - end_queue_without_initial ** 2) / (2 * capacity_veh_h)
        - queue ** 2 / (2 * capacity_veh_h)
    )

    return InitialQueueResult(
        delay_s=delay,
        residual_queue_veh=max(0.0, residual),
        unmet_demand_duration_h=duration,
    )


# ============================================================
# ONE LANE GROUP IN ONE INTERVAL
# ============================================================

def lane_group_delay(
    capacity: LaneGroupCapacity,
    cycle_s: float,
    initial_queue_veh: float,
) -> LaneGroupDelay:
    """
    Control delay of one lane group in one interval, given the queue
    left over from the previous interval.
    """

    demand = capacity.demand_veh_h
    cap = capacity.capacity_veh_h
    green = capacity.green_s
    ratio = demand / cap

    # Residual queue at the end of the interval: also needed when there
    # is no demand, so that the next interval starts correctly.
    queue = initial_queue_delay(initial_queue_veh, demand, cap) if demand > 0 else None

    if demand == 0:
        residual = max(0.0, initial_queue_veh - cap * ANALYSIS_PERIOD_H)

        return LaneGroupDelay(
            capacity.lane_group_id, KpiStatus.NOT_APPLICABLE, NO_DEMAND_REASON,
            None, None, None, None, None, initial_queue_veh, residual,
        )

    # d1: baseline uniform delay, adjusted for the initial queue
    # (Equations 19-37, 19-38 and 19-40). While the initial queue is
    # being served the lane group operates saturated: the saturated
    # uniform delay is d1 with X = 1.
    baseline = uniform_delay(cycle_s, green, ratio)

    if initial_queue_veh > 0:
        if demand >= cap:
            unmet = ANALYSIS_PERIOD_H
        else:
            unmet = min(initial_queue_veh / (cap - demand), ANALYSIS_PERIOD_H)

        saturated = uniform_delay(cycle_s, green, 1.0)
        d1 = (
            saturated * unmet / ANALYSIS_PERIOD_H
            + baseline * (ANALYSIS_PERIOD_H - unmet) / ANALYSIS_PERIOD_H
        )
    else:
        d1 = baseline

    d2 = incremental_delay(demand, cap)
    d3 = queue.delay_s
    control = d1 + d2 + d3

    return LaneGroupDelay(
        lane_group_id=capacity.lane_group_id,
        status=KpiStatus.OK,
        reason=None,
        uniform_delay_s=d1,
        incremental_delay_s=d2,
        initial_queue_delay_s=d3,
        control_delay_s=control,
        los_grade=level_of_service(control, ratio),
        initial_queue_veh=initial_queue_veh,
        residual_queue_veh=queue.residual_queue_veh,
    )


# ============================================================
# THE ANALYSIS PERIOD
# ============================================================

def calculate_hcm_delays(
    capacity_by_interval: list[tuple[AnalysisInterval, CapacityResults]],
    program: SignalProgram,
) -> list[HcmDelayResults]:
    """
    HCM delay of every lane group and movement for consecutive
    intervals, carrying each lane group's residual queue into the next
    interval. The first interval starts with no initial queue.

    Raises ValueError when the intervals are not back to back.
    """

    for (previous, _), (following, _) in zip(
        capacity_by_interval, capacity_by_interval[1:]
    ):
        if previous.end != following.start:
            raise ValueError("the intervals must be consecutive")

    queues: dict[str, float | None] = {}
    results = []

    for interval, capacity in capacity_by_interval:
        group_delays = {}

        for group_id, group in capacity.lane_groups.items():
            initial_queue = queues.get(group_id, 0.0)

            if group.status == KpiStatus.OK and group.green_periods > 1:
                delay = _unavailable(group_id, MULTIPLE_GREENS_REASON)
            elif group.status == KpiStatus.OK and group.green_s >= program.cycle_length_s:
                delay = _unavailable(group_id, FULL_CYCLE_GREEN_REASON)
            elif initial_queue is None:
                delay = _unavailable(group_id, CHAIN_BROKEN_REASON)
            elif group.status != KpiStatus.OK:
                delay = _unavailable(group_id, NO_CAPACITY_REASON)
            else:
                delay = lane_group_delay(group, program.cycle_length_s, initial_queue)

            group_delays[group_id] = delay
            queues[group_id] = (
                delay.residual_queue_veh
                if delay.residual_queue_veh is not None
                else None
            )

        results.append(
            HcmDelayResults(
                interval=interval,
                lane_groups=group_delays,
                movements=_movement_delays(capacity, group_delays),
            )
        )

    return results


def _unavailable(group_id: str, reason: str) -> LaneGroupDelay:
    return LaneGroupDelay(
        group_id, KpiStatus.UNAVAILABLE, reason,
        None, None, None, None, None, None, None,
    )


def _movement_delays(
    capacity: CapacityResults,
    group_delays: dict[str, LaneGroupDelay],
) -> dict[str, HcmMovementDelay]:
    """Flow-weighted delay of each movement over the groups it uses."""

    results = {}

    for movement_id, movement in capacity.movements.items():
        if movement.status != KpiStatus.OK:
            results[movement_id] = HcmMovementDelay(
                movement_id, movement.status, movement.reason, None, None
            )
            continue

        used = {
            group_id: flow
            for (m, group_id), flow in capacity.flows.items()
            if m == movement_id and flow > 0
        }

        if any(group_delays[g].status != KpiStatus.OK for g in used):
            results[movement_id] = HcmMovementDelay(
                movement_id, KpiStatus.UNAVAILABLE,
                "a lane group of this movement has no HCM delay", None, None,
            )
            continue

        delay = sum(
            group_delays[g].control_delay_s * flow for g, flow in used.items()
        ) / sum(used.values())

        results[movement_id] = HcmMovementDelay(
            movement_id=movement_id,
            status=KpiStatus.OK,
            reason=None,
            control_delay_s=delay,
            los_grade=level_of_service(delay, movement.volume_to_capacity),
        )

    return results
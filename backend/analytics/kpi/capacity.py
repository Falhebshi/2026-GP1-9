"""
HCM saturation flow, capacity and volume-to-capacity ratio.

These KPIs are calculated with the HCM method from the lanes, the
signal program and the demand; they do not use the simulation's
measurements. See docs/kpi_engine.md section 9.
"""

from statistics import fmean
from typing import NamedTuple

from backend.analytics.kpi.lane_groups import LaneGroup
from backend.analytics.kpi.parameters import (
    AREA_TYPE_FACTOR,
    BASE_SATURATION_FLOW_PC_H_LN,
    BUS_BLOCKAGE_FACTOR,
    CAV_FACTOR,
    DOWNSTREAM_LANE_BLOCKAGE_FACTOR,
    EFFECTIVE_GREEN_EXTENSION_S,
    HEAVY_VEHICLE_GRADE_FACTOR,
    LANE_UTILIZATION_FACTORS,
    LANE_WIDTH_FACTOR_NARROW,
    LANE_WIDTH_FACTOR_NORMAL,
    LANE_WIDTH_FACTOR_WIDE,
    LANE_WIDTH_MINIMUM_M,
    LANE_WIDTH_NARROW_LIMIT_M,
    LANE_WIDTH_WIDE_LIMIT_M,
    LANE_CHANGE_CRITICAL_HEADWAY_S,
    LEFT_TURN_EQUIVALENT,
    PARKING_FACTOR,
    PEDESTRIAN_BICYCLE_FACTOR,
    START_UP_LOST_TIME_S,
    SUSTAINED_SPILLBACK_FACTOR,
    WORK_ZONE_FACTOR,
)
from jaadah.models.kpis import InputOrigin, KpiStatus
from jaadah.models.network import (
    ApproachLane,
    Movement,
    MovementAttributes,
    MovementType,
)
from jaadah.models.signals import (
    SignalPhase,
    SignalProgram,
    SignalProgramSource,
)


# Demand distribution (section 9.4): stop when no lane group's flow
# changes by more than this between two rounds (HCM Chapter 31,
# Step H: 0.1 veh/h).
DISTRIBUTION_TOLERANCE_VEH_H = 0.1
DISTRIBUTION_MAX_ROUNDS = 100

# The product of the factors that do not depend on the lane group.
FIXED_FACTORS = (
    HEAVY_VEHICLE_GRADE_FACTOR
    * PARKING_FACTOR
    * BUS_BLOCKAGE_FACTOR
    * AREA_TYPE_FACTOR
    * PEDESTRIAN_BICYCLE_FACTOR
    * WORK_ZONE_FACTOR
    * DOWNSTREAM_LANE_BLOCKAGE_FACTOR
    * SUSTAINED_SPILLBACK_FACTOR
    * CAV_FACTOR
)


# ============================================================
# SATURATION FLOW
# ============================================================

def saturation_flow(
    group: LaneGroup,
    lanes_by_id: dict[str, ApproachLane],
    movement_attributes: dict[str, MovementAttributes],
    left_turn_share: float,
    left_turn_equivalent: float = LEFT_TURN_EQUIVALENT,
    include_lane_utilization: bool = True,
) -> float:
    """
    Saturation flow of one lane group, in veh/h: N times the adjusted
    saturation flow per lane of HCM Equation 19-8,
    s = s0 x N x f_w x f_LU x f_LT x (the fixed factors).

    left_turn_share is the share of left-turning vehicles in the group
    (P_LT, from 0 to 1): 1 for an exclusive left-turn lane, 0 for a
    through-only group. left_turn_equivalent is E_L (1.05), or the
    modified E_L,m for a shared lane (Chapter 31, Equation 31-47).
    include_lane_utilization is False for the lane-choice calculation
    of Chapter 31, which uses per-lane saturation flows without f_LU.
    """

    if not 0 <= left_turn_share <= 1:
        raise ValueError("left_turn_share must be between 0 and 1")

    widths = [lanes_by_id[lane_id].lane_width_m for lane_id in group.lane_ids]

    return (
        BASE_SATURATION_FLOW_PC_H_LN
        * group.lane_count
        * lane_width_factor(fmean(widths))
        * (
            lane_utilization_factor(
                group.lane_count, _utilization_type(group, movement_attributes)
            )
            if include_lane_utilization
            else 1.0
        )
        * left_turn_factor(left_turn_share, left_turn_equivalent)
        * FIXED_FACTORS
    )


def lane_width_factor(average_width_m: float) -> float:
    """
    HCM lane-width factor for a group's average lane width
    (Exhibit 19-20). The factor may not be used below 8.0 ft.
    """

    if average_width_m < LANE_WIDTH_MINIMUM_M:
        raise ValueError(
            "the lane width factor does not apply to an average lane "
            f"width below 8.0 ft ({LANE_WIDTH_MINIMUM_M} m); "
            f"got {average_width_m} m"
        )

    if average_width_m < LANE_WIDTH_NARROW_LIMIT_M:
        return LANE_WIDTH_FACTOR_NARROW

    if average_width_m > LANE_WIDTH_WIDE_LIMIT_M:
        return LANE_WIDTH_FACTOR_WIDE

    return LANE_WIDTH_FACTOR_NORMAL


def lane_utilization_factor(lane_count: int, movement_type: str) -> float:
    """
    HCM default lane-utilisation factor (Exhibit 19-15) for a number of
    lanes of one movement type ("through", "left" or "right"). For more
    lanes than the exhibit lists, the smallest value of that type is
    used.
    """

    factors = LANE_UTILIZATION_FACTORS[movement_type]

    if lane_count < 1:
        raise ValueError("lane_count must be at least 1")

    if lane_count in factors:
        return factors[lane_count]

    return min(factors.values())


def _utilization_type(
    group: LaneGroup,
    movement_attributes: dict[str, MovementAttributes],
) -> str:
    """
    Exhibit 19-15 row type of a lane group: "left" or "right" for an
    exclusive turn lane group, otherwise "through". Shared groups have
    one lane, so their type does not change the factor.
    """

    types = {movement_attributes[m].movement_type for m in group.movement_ids}

    if types == {MovementType.LEFT}:
        return "left"

    if types == {MovementType.RIGHT}:
        return "right"

    return "through"


def left_turn_factor(
    left_turn_share: float,
    left_turn_equivalent: float = LEFT_TURN_EQUIVALENT,
) -> float:
    """
    Protected left-turn factor: 1 / (1 + P_LT x (E_L - 1)).
    With only left turns this is 1 / E_L = 0.952 (Equation 19-14); for
    a shared lane, E_L is replaced by the modified E_L,m (Equation
    31-63 form).
    """

    return 1 / (1 + left_turn_share * (left_turn_equivalent - 1))


def lane_change_probability(approach_flow_per_lane: float) -> float:
    """
    Probability of a lane change among the approach through lanes
    (HCM Equation 31-50): 1 - (2 v_app / s_lc - 1)^2, at least 0, with
    s_lc = 3,600 / 3.7 s. It is highest at medium flows and 0 at no
    flow or at 973 veh/h/ln and above.
    """

    lane_change_flow = 3600 / LANE_CHANGE_CRITICAL_HEADWAY_S

    return max(0.0, 1 - (2 * approach_flow_per_lane / lane_change_flow - 1) ** 2)


def modified_left_turn_equivalent(approach_flow_per_lane: float) -> float:
    """E_L,m = (E_L - 1) x P_lc + 1 (HCM Equation 31-47)."""

    return (LEFT_TURN_EQUIVALENT - 1) * lane_change_probability(
        approach_flow_per_lane
    ) + 1


# ============================================================
# DEMAND DISTRIBUTION OVER LANE GROUPS
# ============================================================

class DemandDistribution(NamedTuple):
    """
    How the demand of one approach is spread over its lane groups.

    flows: veh/h of each (movement_id, lane_group_id) pair.
    group_flows: total veh/h of each lane group.
    left_turn_shares: share of left-turning vehicles in each group.
    saturation_flows: saturation flow of each group (veh/h) used for
    capacity, with its left-turn share and lane utilisation.
    lane_choice_saturation_flows: the per-lane saturation flows of the
    Chapter 31 lane-choice calculation (no lane utilisation), over
    which the flow ratios are equalized.
    shared_left_turn_equivalent: E_L,m used for shared lanes.
    """

    flows: dict[tuple[str, str], float]
    group_flows: dict[str, float]
    left_turn_shares: dict[str, float]
    saturation_flows: dict[str, float]
    lane_choice_saturation_flows: dict[str, float]
    shared_left_turn_equivalent: float


def distribute_demand(
    groups: list[LaneGroup],
    lanes_by_id: dict[str, ApproachLane],
    movement_attributes: dict[str, MovementAttributes],
    demand_veh_h: dict[str, float],
) -> DemandDistribution:
    """
    Spread each movement's demand over the lane groups of one approach
    so that every lane group a movement uses has the same flow ratio
    v/s (docs/kpi_engine.md section 9.4).

    groups are the lane groups of one approach. demand_veh_h gives the
    demand of every movement those groups serve.

    Raises ValueError when a served movement has no demand, a demand
    is negative, or the distribution does not settle within
    DISTRIBUTION_MAX_ROUNDS rounds.
    """

    served = sorted({m for group in groups for m in group.movement_ids})

    for movement_id in served:
        if movement_id not in demand_veh_h:
            raise ValueError(f"no demand for movement {movement_id}")

        if demand_veh_h[movement_id] < 0:
            raise ValueError(
                f"demand of movement {movement_id} must not be negative"
            )

    allowed = {
        movement_id: [
            g.lane_group_id for g in groups if movement_id in g.movement_ids
        ]
        for movement_id in served
    }
    groups_by_id = {g.lane_group_id: g for g in groups}

    # Chapter 31, Step A: modified through-car equivalent for the left
    # turns in shared lanes, from the average flow per lane that can
    # serve through traffic (Equation 31-51).
    shared_equivalent = modified_left_turn_equivalent(
        _approach_flow_per_through_lane(groups, movement_attributes, demand_veh_h)
    )

    def lane_choice_saturation(group, share):
        """Per-lane saturation flows of Chapter 31 (no f_LU)."""

        return saturation_flow(
            group,
            lanes_by_id,
            movement_attributes,
            share,
            left_turn_equivalent=(
                shared_equivalent if group.is_shared else LEFT_TURN_EQUIVALENT
            ),
            include_lane_utilization=False,
        )

    # Step 1: split each movement equally over the groups it may use.
    flows = {
        (movement_id, group_id): demand_veh_h[movement_id] / len(group_ids)
        for movement_id, group_ids in allowed.items()
        for group_id in group_ids
    }

    for _ in range(DISTRIBUTION_MAX_ROUNDS):
        previous = dict(flows)

        # Step 3 (for the current flows): saturation flow of each group.
        shares = _left_turn_shares(groups, flows, movement_attributes)
        saturation = {
            g.lane_group_id: lane_choice_saturation(g, shares[g.lane_group_id])
            for g in groups
        }

        # Step 2: redistribute each movement in turn.
        for movement_id, group_ids in allowed.items():
            others = {
                group_id: _group_flow(groups_by_id[group_id], flows)
                - flows[(movement_id, group_id)]
                for group_id in group_ids
            }

            new_flows = _water_fill(
                demand_veh_h[movement_id],
                {group_id: saturation[group_id] for group_id in group_ids},
                others,
            )

            for group_id, flow in new_flows.items():
                flows[(movement_id, group_id)] = flow

        # Step 4: stop when nothing changes any more.
        change = max(
            abs(flows[key] - previous[key]) for key in flows
        ) if flows else 0.0

        if change <= DISTRIBUTION_TOLERANCE_VEH_H:
            shares = _left_turn_shares(groups, flows, movement_attributes)

            return DemandDistribution(
                flows=flows,
                group_flows={
                    g.lane_group_id: _group_flow(g, flows) for g in groups
                },
                left_turn_shares=shares,
                saturation_flows={
                    g.lane_group_id: saturation_flow(
                        g,
                        lanes_by_id,
                        movement_attributes,
                        shares[g.lane_group_id],
                        left_turn_equivalent=(
                            shared_equivalent
                            if g.is_shared
                            else LEFT_TURN_EQUIVALENT
                        ),
                    )
                    for g in groups
                },
                lane_choice_saturation_flows={
                    g.lane_group_id: lane_choice_saturation(
                        g, shares[g.lane_group_id]
                    )
                    for g in groups
                },
                shared_left_turn_equivalent=shared_equivalent,
            )

    raise ValueError(
        "the demand distribution did not settle within "
        f"{DISTRIBUTION_MAX_ROUNDS} rounds"
    )


def _approach_flow_per_through_lane(
    groups: list[LaneGroup],
    movement_attributes: dict[str, MovementAttributes],
    demand_veh_h: dict[str, float],
) -> float:
    """
    v_app of HCM Equation 31-51: the approach's demand divided by the
    number of lanes that serve through traffic (shared or exclusive).
    0 when no lane serves through traffic.
    """

    through_lanes = sum(
        g.lane_count
        for g in groups
        if any(
            movement_attributes[m].movement_type == MovementType.THROUGH
            for m in g.movement_ids
        )
    )

    if through_lanes == 0:
        return 0.0

    served = {m for g in groups for m in g.movement_ids}

    return sum(demand_veh_h[m] for m in served) / through_lanes


def _group_flow(
    group: LaneGroup,
    flows: dict[tuple[str, str], float],
) -> float:
    """Total flow of one lane group."""

    return sum(
        flows[(movement_id, group.lane_group_id)]
        for movement_id in group.movement_ids
    )


def _left_turn_shares(
    groups: list[LaneGroup],
    flows: dict[tuple[str, str], float],
    movement_attributes: dict[str, MovementAttributes],
) -> dict[str, float]:
    """
    Share of left-turning vehicles in each lane group.

    A group carrying no flow gets 1 when it serves only left turns and
    0 otherwise.
    """

    shares = {}

    for group in groups:
        is_left = {
            m: movement_attributes[m].movement_type == MovementType.LEFT
            for m in group.movement_ids
        }
        total = _group_flow(group, flows)

        if total == 0:
            shares[group.lane_group_id] = 1.0 if all(is_left.values()) else 0.0
            continue

        left = sum(
            flows[(m, group.lane_group_id)]
            for m in group.movement_ids
            if is_left[m]
        )
        shares[group.lane_group_id] = left / total

    return shares


def _water_fill(
    demand: float,
    saturation: dict[str, float],
    others: dict[str, float],
) -> dict[str, float]:
    """
    Spread one movement's demand over its groups so that the groups
    that receive some of it end up with the same flow ratio
    (others + own flow) / saturation, filling the least loaded groups
    first. A group already above that level receives nothing.
    """

    order = sorted(saturation, key=lambda g: others[g] / saturation[g])

    active: list[str] = []
    level = 0.0

    for index, group_id in enumerate(order):
        active.append(group_id)

        level = (demand + sum(others[g] for g in active)) / sum(
            saturation[g] for g in active
        )

        next_start = (
            others[order[index + 1]] / saturation[order[index + 1]]
            if index + 1 < len(order)
            else None
        )

        if next_start is None or level <= next_start:
            break

    return {
        group_id: (
            max(0.0, level * saturation[group_id] - others[group_id])
            if group_id in active
            else 0.0
        )
        for group_id in saturation
    }


# ============================================================
# CAPACITY, VOLUME-TO-CAPACITY RATIO AND CRITICAL V/C
# ============================================================

PERMITTED_LEFT_REASON = "permitted left turns are not supported"
SPLIT_PHASES_REASON = (
    "shared lane whose movements are served in different phases "
    "is not supported"
)
MISSING_DEMAND_REASON = "no demand for a movement of this approach"
NO_DEMAND_REASON = "no demand in this interval"
LANE_GROUP_UNAVAILABLE_REASON = (
    "a lane group of this movement has no capacity result"
)
INTERSECTION_UNAVAILABLE_REASON = (
    "a lane group of the intersection has no capacity result"
)


class LaneGroupCapacity(NamedTuple):
    """HCM results of one lane group in one interval."""

    lane_group_id: str
    status: KpiStatus
    reason: str | None
    demand_veh_h: float | None
    saturation_flow_veh_h: float | None
    green_s: float | None
    capacity_veh_h: float | None
    volume_to_capacity: float | None

    @property
    def flow_ratio(self) -> float | None:
        """v / s."""

        if self.status != KpiStatus.OK:
            return None

        return self.demand_veh_h / self.saturation_flow_veh_h


class MovementCapacity(NamedTuple):
    """
    HCM results of one movement in one interval (section 9.6).

    shared_lane_group_id names a shared lane group the movement uses,
    for the "Shared lane" tag; None when it uses none.
    """

    movement_id: str
    status: KpiStatus
    reason: str | None
    demand_veh_h: float | None
    saturation_flow_veh_h: float | None
    capacity_veh_h: float | None
    volume_to_capacity: float | None
    shared_lane_group_id: str | None


class CapacityResults(NamedTuple):
    """
    All HCM capacity results of the intersection in one interval.

    flows gives the demand of each (movement_id, lane_group_id) pair
    from the demand distribution (veh/h); hcm_delay.py uses it to
    weight lane-group delays per movement.
    """

    lane_groups: dict[str, LaneGroupCapacity]
    movements: dict[str, MovementCapacity]
    critical_volume_to_capacity: float | None
    critical_status: KpiStatus
    critical_reason: str | None
    flows: dict[tuple[str, str], float]


def signal_timing_origin(program: SignalProgram) -> InputOrigin:
    """
    Input origin of the signal timing (section 9.8): observed for an
    observed program, modelled assumption otherwise.
    """

    if program.source == SignalProgramSource.OBSERVED:
        return InputOrigin.OBSERVED

    return InputOrigin.MODELLED_ASSUMPTION


def calculate_capacity(
    groups: list[LaneGroup],
    lanes_by_id: dict[str, ApproachLane],
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
    program: SignalProgram,
    demand_veh_h: dict[str, float],
) -> CapacityResults:
    """
    Calculate the HCM capacity results of the intersection for one
    interval.

    groups are all lane groups of the intersection (lane_groups.py).
    demand_veh_h gives each movement's demand in the interval, in
    veh/h; a movement missing from it has no demand record.
    """

    group_results: dict[str, LaneGroupCapacity] = {}
    flows: dict[tuple[str, str], float] = {}

    for approach_id in sorted({g.approach_id for g in groups}):
        approach_groups = [g for g in groups if g.approach_id == approach_id]
        served = {m for g in approach_groups for m in g.movement_ids}

        if not served <= demand_veh_h.keys():
            for g in approach_groups:
                group_results[g.lane_group_id] = _unavailable_group(
                    g, MISSING_DEMAND_REASON
                )
            continue

        distribution = distribute_demand(
            approach_groups,
            lanes_by_id,
            movement_attributes,
            {m: demand_veh_h[m] for m in served},
        )
        flows.update(distribution.flows)

        for g in approach_groups:
            group_results[g.lane_group_id] = _group_capacity(
                g,
                distribution,
                program,
                movements,
                movement_attributes,
            )

    movement_results = _movement_capacities(groups, group_results, flows)

    critical, status, reason = _critical_volume_to_capacity(
        groups, group_results, program
    )

    return CapacityResults(
        lane_groups=group_results,
        movements=movement_results,
        critical_volume_to_capacity=critical,
        critical_status=status,
        critical_reason=reason,
        flows=flows,
    )


def _group_capacity(
    group: LaneGroup,
    distribution: DemandDistribution,
    program: SignalProgram,
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
) -> LaneGroupCapacity:
    """c = s x g / C and X = v / c for one lane group."""

    for movement_id in group.movement_ids:
        if _is_permitted_left(
            movement_id, program, movements, movement_attributes
        ):
            return _unavailable_group(group, PERMITTED_LEFT_REASON)

    green = lane_group_green(group, program)

    if green is None:
        return _unavailable_group(group, SPLIT_PHASES_REASON)

    demand = distribution.group_flows[group.lane_group_id]
    saturation = distribution.saturation_flows[group.lane_group_id]
    capacity = saturation * green / program.cycle_length_s

    return LaneGroupCapacity(
        lane_group_id=group.lane_group_id,
        status=KpiStatus.OK,
        reason=None,
        demand_veh_h=demand,
        saturation_flow_veh_h=saturation,
        green_s=green,
        capacity_veh_h=capacity,
        volume_to_capacity=demand / capacity,
    )


def lane_group_green(group: LaneGroup, program: SignalProgram) -> float | None:
    """
    Effective green of a lane group: the total effective green of the
    phases that serve all of its movements. None when no phase serves
    all of them.
    """

    phases = [
        phase
        for phase in program.phases
        if group.movement_ids <= set(phase.served_movement_ids)
    ]

    if not phases:
        return None

    return sum(effective_green(phase) for phase in phases)


def effective_green(phase: SignalPhase) -> float:
    """
    Effective green of one phase (HCM Equation 19-3):
    g = G + Y + Rc - l1 - l2 with l2 = Y + Rc - e, so g = G - l1 + e.
    """

    return phase.green_time_s - START_UP_LOST_TIME_S + EFFECTIVE_GREEN_EXTENSION_S


def phase_lost_time(phase: SignalPhase) -> float:
    """
    Lost time of one phase: l1 + l2, with clearance lost time
    l2 = Y + Rc - e (page 19-14).
    """

    clearance_lost_time = (
        phase.yellow_time_s + phase.all_red_time_s - EFFECTIVE_GREEN_EXTENSION_S
    )

    return START_UP_LOST_TIME_S + clearance_lost_time


def _is_permitted_left(
    movement_id: str,
    program: SignalProgram,
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
) -> bool:
    """
    True when a left turn shares a phase with a through movement of
    another approach, so it must turn through gaps in that traffic.
    """

    if movement_attributes[movement_id].movement_type != MovementType.LEFT:
        return False

    approach_id = movements[movement_id].approach_id

    for phase in program.phases:
        if movement_id not in phase.served_movement_ids:
            continue

        for other_id in phase.served_movement_ids:
            other = movement_attributes.get(other_id)

            if (
                other is not None
                and other.movement_type == MovementType.THROUGH
                and movements[other_id].approach_id != approach_id
            ):
                return True

    return False


def _unavailable_group(group: LaneGroup, reason: str) -> LaneGroupCapacity:
    return LaneGroupCapacity(
        lane_group_id=group.lane_group_id,
        status=KpiStatus.UNAVAILABLE,
        reason=reason,
        demand_veh_h=None,
        saturation_flow_veh_h=None,
        green_s=None,
        capacity_veh_h=None,
        volume_to_capacity=None,
    )


def _movement_capacities(
    groups: list[LaneGroup],
    group_results: dict[str, LaneGroupCapacity],
    flows: dict[tuple[str, str], float],
) -> dict[str, MovementCapacity]:
    """Movement values from the lane groups each movement uses."""

    results = {}
    served = sorted({m for g in groups for m in g.movement_ids})

    for movement_id in served:
        own_groups = [g for g in groups if movement_id in g.movement_ids]

        unavailable = [
            g for g in own_groups
            if group_results[g.lane_group_id].status != KpiStatus.OK
        ]

        if unavailable:
            reason = (
                group_results[unavailable[0].lane_group_id].reason
                if len(own_groups) == 1
                else LANE_GROUP_UNAVAILABLE_REASON
            )
            results[movement_id] = MovementCapacity(
                movement_id, KpiStatus.UNAVAILABLE, reason,
                None, None, None, None, None,
            )
            continue

        demand = sum(flows[(movement_id, g.lane_group_id)] for g in own_groups)

        if demand == 0:
            results[movement_id] = MovementCapacity(
                movement_id, KpiStatus.NOT_APPLICABLE, NO_DEMAND_REASON,
                0.0, None, None, None, None,
            )
            continue

        used = [g for g in own_groups if flows[(movement_id, g.lane_group_id)] > 0]

        ratio = max(group_results[g.lane_group_id].volume_to_capacity for g in used)
        flow_ratio = max(group_results[g.lane_group_id].flow_ratio for g in used)

        shared = [g.lane_group_id for g in used if g.is_shared]

        results[movement_id] = MovementCapacity(
            movement_id=movement_id,
            status=KpiStatus.OK,
            reason=None,
            demand_veh_h=demand,
            saturation_flow_veh_h=demand / flow_ratio,
            capacity_veh_h=demand / ratio,
            volume_to_capacity=ratio,
            shared_lane_group_id=shared[0] if shared else None,
        )

    return results


def _critical_volume_to_capacity(
    groups: list[LaneGroup],
    group_results: dict[str, LaneGroupCapacity],
    program: SignalProgram,
) -> tuple[float | None, KpiStatus, str | None]:
    """
    Xc = sum of each phase's highest flow ratio x C / (C - L)
    (HCM Equation 19-30), with L the total lost time of the phases.
    Jaadah's phases run in sequence, so every phase is critical.
    """

    if any(r.status != KpiStatus.OK for r in group_results.values()):
        return None, KpiStatus.UNAVAILABLE, INTERSECTION_UNAVAILABLE_REASON

    total_critical = 0.0

    for phase in program.phases:
        served = set(phase.served_movement_ids)
        ratios = [
            group_results[g.lane_group_id].flow_ratio
            for g in groups
            if g.movement_ids <= served
        ]

        if ratios:
            total_critical += max(ratios)

    cycle = program.cycle_length_s
    lost_time = sum(phase_lost_time(phase) for phase in program.phases)

    return total_critical * cycle / (cycle - lost_time), KpiStatus.OK, None
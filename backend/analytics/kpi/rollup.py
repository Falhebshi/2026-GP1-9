"""
Roll-up: combining lane, lane-group and movement results into
movement, approach and intersection values for one interval of one
run (docs/kpi_engine.md section 11).

- Delays and queue durations are averaged, weighted by vehicles
  (measured) or by lane-group demand (HCM, Equations 19-28 and 19-29).
- Throughput and capacity are summed.
- Volume-to-capacity ratios, queue lengths and storage ratios take the
  worst (highest) value; they are never averaged.

When any part is unavailable, the combined value is unavailable; when
all its unavailable parts give the same reason, that reason is kept, so
the cause stays visible at every level. Parts that are not applicable
are left out; when no part is left, the combined value is not
applicable.

A queue is measured twice: per lane, over the lane's section, and per
approach, over the whole measurement zone (section 5). Movements take
their longest lane; an approach takes the larger of its full-zone queue
and its uncontrolled slip lanes; the intersection takes its longest
approach.

Two conditions make every value of an approach unavailable in an
interval (passed as blocked, from delay.py and queue.py): the queue
reached the end of the measurement zone (delay, queue duration and
queue), and vehicles could not enter the network (also throughput).

Uncontrolled right-turn slips are included in the measured delay,
queue duration, throughput, queue length and storage ratio of their
approach and of the intersection, and excluded from the HCM delay; the
results say so in uncontrolled_movements (the KpiResult field).

Level of service of measured delays is graded after the runs are
combined (section 7.6); HCM levels of service are graded here.
"""

from typing import NamedTuple

from backend.analytics.kpi.capacity import CapacityResults
from backend.analytics.kpi.delay import MovementDelay
from backend.analytics.kpi.hcm_delay import HcmDelayResults
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.lane_groups import LaneGroup
from backend.analytics.kpi.parameters import level_of_service
from backend.analytics.kpi.queue import (
    NO_RECORDS_REASON,
    SECTION_END_REASON,
    ZONE_END_REASON,
    LaneQueue,
    storage_ratio,
)
from jaadah.models.kpis import (
    KpiStatus,
    LevelOfServiceGrade,
    UncontrolledMovements,
)
from jaadah.models.network import (
    ApproachLane,
    Movement,
    MovementAttributes,
    MovementControl,
)


INCLUDES_UNCONTROLLED = UncontrolledMovements.INCLUDED
EXCLUDES_UNCONTROLLED = UncontrolledMovements.EXCLUDED
PART_UNAVAILABLE_REASON = "a part of this element has no result"
NOTHING_TO_COMBINE_REASON = "no part of this element has a result"
NO_APPROACH_RECORDS_REASON = "no cycle records for this approach in this interval"
NO_STORAGE_LENGTH_REASON = "the lane has no storage length"
SLIP_SECTION_END_REASON = (
    "the queue on an uncontrolled right-turn lane extends beyond its section"
)


class RolledUp(NamedTuple):
    """
    One combined value.

    measured_on_lane_id names the lane a queue value comes from;
    is_shared is True when that lane is shared by several movements.
    uncontrolled_movements says whether uncontrolled right turns are
    included or excluded (None when the element has none).
    """

    status: KpiStatus
    value: float | None
    reason: str | None = None
    measured_on_lane_id: str | None = None
    is_shared: bool = False
    uncontrolled_movements: UncontrolledMovements | None = None
    los_grade: LevelOfServiceGrade | None = None


class Part(NamedTuple):
    """
    One input to a combination: a status, a value and a weight, with
    the reason when it has no value.
    """

    status: KpiStatus
    value: float | None
    weight: float = 1.0
    lane_id: str | None = None
    is_shared: bool = False
    reason: str | None = None


# ============================================================
# GENERIC COMBINATIONS
# ============================================================

def combine_weighted_mean(parts: list[Part]) -> RolledUp:
    """Weighted mean of the parts that apply."""

    usable = _usable(parts)

    if isinstance(usable, RolledUp):
        return usable

    total_weight = sum(p.weight for p in usable)

    if total_weight == 0:
        return RolledUp(KpiStatus.NOT_APPLICABLE, None, NOTHING_TO_COMBINE_REASON)

    value = sum(p.value * p.weight for p in usable) / total_weight

    return RolledUp(KpiStatus.OK, value)


def combine_sum(parts: list[Part]) -> RolledUp:
    """Sum of the parts that apply."""

    usable = _usable(parts)

    if isinstance(usable, RolledUp):
        return usable

    return RolledUp(KpiStatus.OK, sum(p.value for p in usable))


def combine_highest(parts: list[Part]) -> RolledUp:
    """
    The highest of the parts that apply, with the lane it was measured
    on (the first such part when several are equal).
    """

    usable = _usable(parts)

    if isinstance(usable, RolledUp):
        return usable

    worst = max(usable, key=lambda p: p.value)

    return RolledUp(
        KpiStatus.OK,
        worst.value,
        measured_on_lane_id=worst.lane_id,
        is_shared=worst.is_shared,
    )


def _usable(parts: list[Part]) -> list[Part] | RolledUp:
    """
    The parts that apply, or the combined result when they cannot be
    combined: unavailable if any part is unavailable (with the parts'
    reason when they all give the same one), not applicable if no part
    applies.
    """

    unavailable = [p for p in parts if p.status == KpiStatus.UNAVAILABLE]

    if unavailable:
        return RolledUp(KpiStatus.UNAVAILABLE, None, shared_reason(unavailable))

    usable = [p for p in parts if p.status == KpiStatus.OK]

    if not usable:
        return RolledUp(KpiStatus.NOT_APPLICABLE, None, NOTHING_TO_COMBINE_REASON)

    return usable


def shared_reason(parts) -> str:
    """
    The reason the parts give, when they all give the same one;
    otherwise PART_UNAVAILABLE_REASON.
    """

    reasons = {p.reason for p in parts}

    if len(reasons) == 1 and None not in reasons:
        return reasons.pop()

    return PART_UNAVAILABLE_REASON


# ============================================================
# MEASURED DELAY, QUEUE DURATION AND THROUGHPUT
# ============================================================

def measured_delay_rollup(
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
    delays: dict[tuple[str, AnalysisInterval], MovementDelay],
    interval: AnalysisInterval,
    quantity: str = "control_delay",
) -> dict[tuple[str, str], RolledUp]:
    """
    Approach and intersection values of the measured control delay
    (quantity "control_delay") or queue duration ("queue_duration"):
    the means of their movements, weighted by completed vehicles.
    Keys are ("approach", approach_id) and ("intersection", id).
    """

    field = {
        "control_delay": "mean_control_delay_s",
        "queue_duration": "mean_queue_duration_s",
    }[quantity]

    def part(movement_id):
        result = delays[(movement_id, interval)]
        return Part(
            result.status,
            getattr(result, field),
            result.completed_vehicles,
            reason=result.reason,
        )

    return _by_approach_and_intersection(
        movements,
        movement_attributes,
        part,
        combine_weighted_mean,
        INCLUDES_UNCONTROLLED,
    )


def throughput_rollup(
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
    throughput_veh_h: dict[tuple[str, AnalysisInterval], float],
    interval: AnalysisInterval,
    blocked: dict[tuple[str, AnalysisInterval], str] | None = None,
) -> dict[tuple[str, str], RolledUp]:
    """
    Approach and intersection throughput: sums of their movements.

    blocked maps (movement_id, interval) to the reason a movement's
    throughput is unavailable (vehicles could not enter the network).
    """

    blocked = blocked or {}

    def part(movement_id):
        reason = blocked.get((movement_id, interval))

        if reason is not None:
            return Part(KpiStatus.UNAVAILABLE, None, reason=reason)

        return Part(KpiStatus.OK, throughput_veh_h[(movement_id, interval)])

    return _by_approach_and_intersection(
        movements, movement_attributes, part, combine_sum, INCLUDES_UNCONTROLLED
    )


def _by_approach_and_intersection(
    movements, movement_attributes, part, combine, tag
):
    """Combine movement parts per approach and for the intersection."""

    analysed = [m for m in movements if m in movement_attributes]
    intersection_id = _intersection_id(movements, analysed)

    by_approach: dict[str, list[str]] = {}
    for movement_id in analysed:
        by_approach.setdefault(movements[movement_id].approach_id, []).append(
            movement_id
        )

    results = {}

    for approach_id, members in sorted(by_approach.items()):
        results[("approach", approach_id)] = _with_note(
            combine([part(m) for m in members]),
            members,
            movement_attributes,
            tag,
        )

    results[("intersection", intersection_id)] = _with_note(
        combine([part(m) for m in analysed]),
        analysed,
        movement_attributes,
        tag,
    )

    return results


# ============================================================
# QUEUE LENGTH AND STORAGE RATIO
# ============================================================

def queue_rollup(
    lanes: list[ApproachLane],
    movements: dict[str, Movement],
    lane_queues: dict[tuple[str, AnalysisInterval], LaneQueue | None],
    interval: AnalysisInterval,
    *,
    approach_queues: dict[tuple[str, AnalysisInterval], LaneQueue | None],
    slip_lane_ids: set[str] = frozenset(),
    blocked: dict[tuple[str, AnalysisInterval], str] | None = None,
    unit: str = "m",
) -> dict[tuple[str, str], RolledUp]:
    """
    Lane, movement, approach and intersection queue lengths, in metres
    (unit "m") or vehicles ("veh"). Keys are ("lane", id),
    ("movement", id), ("approach", id) and ("intersection", id).

    - A lane is unavailable when it has no cycle records, or when its
      queue reached the end of its section (the approach queue then
      gives the full length).
    - A movement takes its longest lane, with the lane it was measured
      on.
    - An approach takes the larger of its full-zone queue
      (approach_queues) and its uncontrolled slip lanes (slip_lane_ids,
      which the full-zone queue leaves out). It is unavailable when its
      queue reached the zone end.
    - The intersection takes its longest approach.

    blocked maps (approach_id, interval) to the reason every queue of
    that approach (lanes, movements and the approach) is unavailable.
    """

    blocked = blocked or {}

    def pick(queue):
        return queue.length_m if unit == "m" else queue.vehicles

    def lane_part(lane):
        queue = lane_queues[(lane.lane_id, interval)]
        reason = blocked.get((lane.approach_id, interval))

        if reason is None and queue is None:
            reason = NO_RECORDS_REASON
        elif reason is None and queue.reaches_end:
            reason = SECTION_END_REASON

        if reason is not None:
            return Part(KpiStatus.UNAVAILABLE, None, reason=reason)

        return Part(
            KpiStatus.OK,
            pick(queue),
            lane_id=lane.lane_id,
            is_shared=len(lane.served_movement_ids) > 1,
        )

    def approach_part(approach_id):
        queue = approach_queues[(approach_id, interval)]
        reason = blocked.get((approach_id, interval))

        if reason is None and queue is None:
            reason = NO_APPROACH_RECORDS_REASON
        elif reason is None and queue.reaches_end:
            reason = ZONE_END_REASON

        if reason is not None:
            return Part(KpiStatus.UNAVAILABLE, None, reason=reason)

        return Part(KpiStatus.OK, pick(queue))

    lane_parts = {lane.lane_id: lane_part(lane) for lane in lanes}
    results = _lanes_rollup(lanes, movements, lane_parts, approaches=False)

    approach_results = {}

    for approach_id in sorted({lane.approach_id for lane in lanes}):
        slips = []
        for lane in lanes:
            if lane.approach_id == approach_id and lane.lane_id in slip_lane_ids:
                part = lane_parts[lane.lane_id]
                if part.reason == SECTION_END_REASON:
                    part = part._replace(reason=SLIP_SECTION_END_REASON)
                slips.append(part)

        approach_results[approach_id] = combine_highest(
            [approach_part(approach_id), *slips]
        )
        results[("approach", approach_id)] = approach_results[approach_id]

    intersection_id = _intersection_id(
        movements, [m for lane in lanes for m in lane.served_movement_ids]
    )
    results[("intersection", intersection_id)] = combine_highest(
        [
            Part(r.status, r.value, lane_id=r.measured_on_lane_id,
                 is_shared=r.is_shared, reason=r.reason)
            for r in approach_results.values()
        ]
    )

    return results


def storage_ratio_rollup(
    lanes: list[ApproachLane],
    movements: dict[str, Movement],
    lane_queues: dict[tuple[str, AnalysisInterval], LaneQueue | None],
    interval: AnalysisInterval,
    blocked: dict[tuple[str, AnalysisInterval], str] | None = None,
) -> dict[tuple[str, str], RolledUp]:
    """
    Lane, movement, approach and intersection queue storage ratios: the
    highest lane ratio, with the lane it was measured on. A lane
    without a storage length or without queue records, or whose queue
    reached the end of its section, is unavailable, and so is every
    element it is part of; blocked is as for queue_rollup.
    """

    blocked = blocked or {}

    def lane_part(lane):
        queue = lane_queues[(lane.lane_id, interval)]
        reason = blocked.get((lane.approach_id, interval))

        if reason is None and queue is None:
            reason = NO_RECORDS_REASON
        elif reason is None and queue.reaches_end:
            reason = SECTION_END_REASON
        elif reason is None and lane.storage_length_m is None:
            reason = NO_STORAGE_LENGTH_REASON

        if reason is not None:
            return Part(KpiStatus.UNAVAILABLE, None, reason=reason)

        return Part(
            KpiStatus.OK,
            storage_ratio(queue.length_m, lane.storage_length_m),
            lane_id=lane.lane_id,
            is_shared=len(lane.served_movement_ids) > 1,
        )

    parts = {lane.lane_id: lane_part(lane) for lane in lanes}

    return _lanes_rollup(lanes, movements, parts, approaches=True)


def _lanes_rollup(lanes, movements, parts, approaches):
    """
    Each lane's own value, and the highest lane value per movement and,
    when approaches is True, per approach and for the intersection.
    """

    intersection_id = _intersection_id(
        movements, [m for lane in lanes for m in lane.served_movement_ids]
    )

    results = {}

    for lane in lanes:
        part = parts[lane.lane_id]
        results[("lane", lane.lane_id)] = RolledUp(
            part.status,
            part.value,
            part.reason,
            measured_on_lane_id=part.lane_id,
            is_shared=part.is_shared,
        )

    movement_ids = sorted({m for lane in lanes for m in lane.served_movement_ids})

    for movement_id in movement_ids:
        own = [l for l in lanes if movement_id in l.served_movement_ids]
        results[("movement", movement_id)] = combine_highest(
            [parts[l.lane_id] for l in own]
        )

    if not approaches:
        return results

    for approach_id in sorted({lane.approach_id for lane in lanes}):
        own = [l for l in lanes if l.approach_id == approach_id]
        results[("approach", approach_id)] = combine_highest(
            [parts[l.lane_id] for l in own]
        )

    results[("intersection", intersection_id)] = combine_highest(
        list(parts.values())
    )

    return results


# ============================================================
# HCM RESULTS
# ============================================================

def hcm_rollup(
    groups: list[LaneGroup],
    movements: dict[str, Movement],
    movement_attributes: dict[str, MovementAttributes],
    capacity: CapacityResults,
    hcm: HcmDelayResults,
) -> dict[tuple[str, str, str], RolledUp]:
    """
    Approach and intersection HCM results. Keys are (kpi, level, id)
    with kpi "control_delay" (with its level of service, from delay
    alone), "volume_to_capacity" and "capacity" (approach only; the
    intersection uses the critical ratio of capacity.py).
    """

    intersection_id = _intersection_id(
        movements, [m for g in groups for m in g.movement_ids]
    )

    def delay_part(group):
        delay = hcm.lane_groups[group.lane_group_id]
        demand = capacity.lane_groups[group.lane_group_id].demand_veh_h
        return Part(
            delay.status, delay.control_delay_s, demand or 0.0, reason=delay.reason
        )

    def capacity_part(group, field):
        result = capacity.lane_groups[group.lane_group_id]
        return Part(result.status, getattr(result, field), reason=result.reason)

    slips_exist = {
        movements[m].approach_id
        for m, a in movement_attributes.items()
        if a.control == MovementControl.UNCONTROLLED and m in movements
    }

    results = {}

    for approach_id in sorted({g.approach_id for g in groups}):
        own = [g for g in groups if g.approach_id == approach_id]
        note = EXCLUDES_UNCONTROLLED if approach_id in slips_exist else None

        results[("control_delay", "approach", approach_id)] = _graded(
            combine_weighted_mean([delay_part(g) for g in own]), note
        )
        results[("volume_to_capacity", "approach", approach_id)] = combine_highest(
            [capacity_part(g, "volume_to_capacity") for g in own]
        )
        results[("capacity", "approach", approach_id)] = combine_sum(
            [capacity_part(g, "capacity_veh_h") for g in own]
        )

    results[("control_delay", "intersection", intersection_id)] = _graded(
        combine_weighted_mean([delay_part(g) for g in groups]),
        EXCLUDES_UNCONTROLLED if slips_exist else None,
    )

    return results


def _graded(result: RolledUp, note: str | None) -> RolledUp:
    """Add the level of service (from delay alone) and the note."""

    grade = (
        level_of_service(result.value) if result.status == KpiStatus.OK else None
    )

    return result._replace(los_grade=grade, uncontrolled_movements=note)


# ============================================================
# HELPERS
# ============================================================

def _intersection_id(movements: dict[str, Movement], movement_ids) -> str:
    """The single intersection of the given movements."""

    ids = {movements[m].intersection_id for m in movement_ids}

    if len(ids) != 1:
        raise ValueError("the movements must belong to exactly one intersection")

    return ids.pop()


def _with_note(result, members, movement_attributes, note):
    """Add the uncontrolled-movement note when a member is a slip."""

    has_slip = any(
        movement_attributes[m].control == MovementControl.UNCONTROLLED
        for m in members
    )

    return result._replace(uncontrolled_movements=note if has_slip else None)
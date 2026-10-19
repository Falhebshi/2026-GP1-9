"""
Roll-up: combining lane, lane-group and movement results into
movement, approach and intersection values for one interval of one
run (docs/kpi_engine.md section 11).

- Delays and queue durations are averaged, weighted by vehicles
  (measured) or by lane-group demand (HCM, Equations 19-28 and 19-29).
- Throughput and capacity are summed.
- Volume-to-capacity ratios, queue lengths and storage ratios take the
  worst (highest) value; they are never averaged.

When any part is unavailable, the combined value is unavailable. Parts
that are not applicable are left out; when no part is left, the
combined value is not applicable.

Uncontrolled right-turn slips are included in the measured delay,
queue duration, throughput, queue length and storage ratio of their
approach and of the intersection, and excluded from the HCM delay; the
results say so in uncontrolled_note.

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
from backend.analytics.kpi.queue import LaneQueue, storage_ratio
from jaadah.models.kpis import KpiStatus, LevelOfServiceGrade
from jaadah.models.network import (
    ApproachLane,
    Movement,
    MovementAttributes,
    MovementControl,
)


INCLUDES_UNCONTROLLED = "includes uncontrolled right turns"
EXCLUDES_UNCONTROLLED = "excludes uncontrolled right turns"
PART_UNAVAILABLE_REASON = "a part of this element has no result"
NOTHING_TO_COMBINE_REASON = "no part of this element has a result"


class RolledUp(NamedTuple):
    """
    One combined value.

    measured_on_lane_id names the lane a queue value comes from;
    is_shared is True when that lane is shared by several movements.
    uncontrolled_note says whether uncontrolled right turns are
    included or excluded (None when the element has none).
    """

    status: KpiStatus
    value: float | None
    reason: str | None = None
    measured_on_lane_id: str | None = None
    is_shared: bool = False
    uncontrolled_note: str | None = None
    los_grade: LevelOfServiceGrade | None = None


class Part(NamedTuple):
    """One input to a combination: a status, a value and a weight."""

    status: KpiStatus
    value: float | None
    weight: float = 1.0
    lane_id: str | None = None
    is_shared: bool = False


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
    combined: unavailable if any part is unavailable, not applicable if
    no part applies.
    """

    if any(p.status == KpiStatus.UNAVAILABLE for p in parts):
        return RolledUp(KpiStatus.UNAVAILABLE, None, PART_UNAVAILABLE_REASON)

    usable = [p for p in parts if p.status == KpiStatus.OK]

    if not usable:
        return RolledUp(KpiStatus.NOT_APPLICABLE, None, NOTHING_TO_COMBINE_REASON)

    return usable


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
            result.status, getattr(result, field), result.completed_vehicles
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
) -> dict[tuple[str, str], RolledUp]:
    """Approach and intersection throughput: sums of their movements."""

    def part(movement_id):
        return Part(KpiStatus.OK, throughput_veh_h[(movement_id, interval)])

    return _by_approach_and_intersection(
        movements, movement_attributes, part, combine_sum, INCLUDES_UNCONTROLLED
    )


def _by_approach_and_intersection(
    movements, movement_attributes, part, combine, uncontrolled_note
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
            uncontrolled_note,
        )

    results[("intersection", intersection_id)] = _with_note(
        combine([part(m) for m in analysed]),
        analysed,
        movement_attributes,
        uncontrolled_note,
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
    unit: str = "m",
) -> dict[tuple[str, str], RolledUp]:
    """
    Movement, approach and intersection queue lengths, in metres
    (unit "m") or vehicles ("veh"): the longest lane, with the lane it
    was measured on. Keys are ("movement", id), ("approach", id) and
    ("intersection", id).
    """

    def lane_part(lane):
        queue = lane_queues[(lane.lane_id, interval)]

        if queue is None:
            return Part(KpiStatus.UNAVAILABLE, None)

        value = queue.length_m if unit == "m" else queue.vehicles

        return Part(
            KpiStatus.OK,
            value,
            lane_id=lane.lane_id,
            is_shared=len(lane.served_movement_ids) > 1,
        )

    return _lanes_rollup(lanes, movements, lane_part)


def storage_ratio_rollup(
    lanes: list[ApproachLane],
    movements: dict[str, Movement],
    lane_queues: dict[tuple[str, AnalysisInterval], LaneQueue | None],
    interval: AnalysisInterval,
) -> dict[tuple[str, str], RolledUp]:
    """
    Movement, approach and intersection queue storage ratios: the
    highest lane ratio, with the lane it was measured on. A lane
    without a storage length or without queue records makes the
    combined value unavailable.
    """

    def lane_part(lane):
        queue = lane_queues[(lane.lane_id, interval)]
        ratio = (
            storage_ratio(queue.length_m, lane.storage_length_m)
            if queue is not None
            else None
        )

        if ratio is None:
            return Part(KpiStatus.UNAVAILABLE, None)

        return Part(
            KpiStatus.OK,
            ratio,
            lane_id=lane.lane_id,
            is_shared=len(lane.served_movement_ids) > 1,
        )

    return _lanes_rollup(lanes, movements, lane_part)


def _lanes_rollup(lanes, movements, lane_part):
    """Highest lane value per movement, approach and intersection."""

    intersection_id = _intersection_id(
        movements, [m for lane in lanes for m in lane.served_movement_ids]
    )

    parts = {lane.lane_id: lane_part(lane) for lane in lanes}
    results = {}

    movement_ids = sorted({m for lane in lanes for m in lane.served_movement_ids})

    for movement_id in movement_ids:
        own = [l for l in lanes if movement_id in l.served_movement_ids]
        results[("movement", movement_id)] = combine_highest(
            [parts[l.lane_id] for l in own]
        )

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
        return Part(delay.status, delay.control_delay_s, demand or 0.0)

    def capacity_part(group, field):
        result = capacity.lane_groups[group.lane_group_id]
        return Part(result.status, getattr(result, field))

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

    return result._replace(los_grade=grade, uncontrolled_note=note)


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

    return result._replace(uncontrolled_note=note if has_slip else None)
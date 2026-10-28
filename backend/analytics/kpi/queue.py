"""
Queue length and queue storage ratio, per lane and per approach.

Each CycleQueueRecord gives the longest queue on one lane's section in
one signal cycle, and each ApproachCycleQueueRecord the longest full
queue of one approach over its measurement zone. A cycle belongs to the
interval that contains its cycle_start; a cycle that starts in the
warm-up or clearance is not used.

Two summaries are calculated for each lane and approach:
- per interval: the largest cycle queue in that interval;
- over the whole analysis period: the 95th-percentile cycle queue,
  using the nearest-rank method.

A lane or approach with no cycle records has no queue value (None): a
record is written for every lane, approach and cycle, even with no
queue, so a missing record means missing data, not an empty lane.

A cycle whose queue reached the end of what was measured (a lane's
section, or an approach's zone) is cut off: the real queue was longer.
A summary that depends on a cut-off cycle is marked reaches_end and is
reported as unavailable. Cut-off cycles hold the largest values, so the
period percentile depends on one only when the cycle at its rank is
cut off.

Works on the records of one run.
"""

import math
from typing import NamedTuple

from backend.analytics.kpi.intervals import AnalysisInterval, find_interval
from backend.analytics.kpi.parameters import QUEUE_PERCENTILE
from jaadah.models.outputs import ApproachCycleQueueRecord, CycleQueueRecord


SECTION_END_REASON = "queue extends beyond this lane's section; see the approach queue"
ZONE_END_REASON = (
    "the queue reached the end of the measurement zone; delay before the "
    "zone is not measured"
)
NO_RECORDS_REASON = "no cycle records for this lane in this interval"
PERIOD_INCOMPLETE_REASON = (
    "no cycle records in at least one interval of the analysis period"
)


class LaneQueue(NamedTuple):
    """
    A queue in both units: metres and vehicles. reaches_end is True when
    the value depends on a cycle cut off at the end of what was
    measured, so the real queue was longer.
    """

    length_m: float
    vehicles: int
    reaches_end: bool = False


# ============================================================
# LANES
# ============================================================

def interval_queues(
    run_id: str,
    lane_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[CycleQueueRecord],
) -> dict[tuple[str, AnalysisInterval], LaneQueue | None]:
    """
    Return the largest cycle queue of each lane in each interval.

    The value is None when a lane has no cycle record in an interval.
    Metres and vehicles are each the largest of the interval's cycles;
    reaches_end is True when one of the cycles reached the section end.
    """

    cycles = _cycles_by_key_and_interval(run_id, lane_ids, intervals, cycle_records, "lane_id")
    return _interval_summaries(lane_ids, intervals, cycles, "reaches_section_end")


def period_percentile_queues(
    run_id: str,
    lane_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[CycleQueueRecord],
) -> dict[str, LaneQueue | None]:
    """
    Return the 95th-percentile cycle queue of each lane over the whole
    analysis period (all its intervals together).

    The value is None (unavailable, PERIOD_INCOMPLETE_REASON) when a
    lane has no cycle record in any one of the intervals: a record is
    written for every lane and cycle, even with no queue, so a
    missing interval is missing data, and the percentile of the other
    intervals would not represent the whole period.
    """

    cycles = _cycles_by_key_and_interval(run_id, lane_ids, intervals, cycle_records, "lane_id")
    return _period_summaries(lane_ids, intervals, cycles, "reaches_section_end")


# ============================================================
# APPROACHES
# ============================================================

def approach_interval_queues(
    run_id: str,
    approach_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[ApproachCycleQueueRecord],
) -> dict[tuple[str, AnalysisInterval], LaneQueue | None]:
    """
    Return the largest full-zone cycle queue of each approach in each
    interval, the same way as interval_queues; reaches_end is True when
    one of the cycles reached the zone end.
    """

    cycles = _cycles_by_key_and_interval(
        run_id, approach_ids, intervals, cycle_records, "approach_id"
    )
    return _interval_summaries(approach_ids, intervals, cycles, "reaches_zone_end")


def approach_period_percentile_queues(
    run_id: str,
    approach_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[ApproachCycleQueueRecord],
) -> dict[str, LaneQueue | None]:
    """The 95th-percentile full-zone cycle queue of each approach, as for lanes."""

    cycles = _cycles_by_key_and_interval(
        run_id, approach_ids, intervals, cycle_records, "approach_id"
    )
    return _period_summaries(approach_ids, intervals, cycles, "reaches_zone_end")


def zone_end_approaches(
    approach_queues: dict[tuple[str, AnalysisInterval], LaneQueue | None],
) -> dict[tuple[str, AnalysisInterval], str]:
    """
    The (approach, interval) pairs in which the approach's queue reached
    its zone end, with the reason: there, the delay vehicles met before
    the zone is not measured, so the approach's measured delay, queue
    duration and queue are not valid.
    """

    return {
        key: ZONE_END_REASON
        for key, queue in approach_queues.items()
        if queue is not None and queue.reaches_end
    }


# ============================================================
# SHARED
# ============================================================

def storage_ratio(
    queue_length_m: float,
    storage_length_m: float | None,
) -> float | None:
    """
    Queue length divided by the lane's storage length.

    Returns None when the storage length is not known. A ratio above 1
    means the queue was longer than the lane's storage.
    """

    if storage_length_m is None:
        return None

    if storage_length_m <= 0:
        raise ValueError("storage_length_m must be positive")

    return queue_length_m / storage_length_m


def nearest_rank_percentile(values: list[float], percentile: float):
    """
    Return the value at rank ceil(percentile / 100 x n) of the sorted
    values: always one of the values themselves.

    For 20 values and the 95th percentile, this is the 19th smallest.
    """

    if not values:
        raise ValueError("values must not be empty")

    if not 0 < percentile <= 100:
        raise ValueError("percentile must be above 0 and at most 100")

    ordered = sorted(values)
    rank = math.ceil(percentile / 100 * len(ordered))

    return ordered[rank - 1]


def _interval_summaries(keys, intervals, cycles, flag):
    result = {}

    for key in keys:
        for interval in intervals:
            records = cycles[(key, interval)]

            if not records:
                result[(key, interval)] = None
                continue

            result[(key, interval)] = LaneQueue(
                length_m=max(r.max_queue_length_m for r in records),
                vehicles=max(r.max_queue_vehicles for r in records),
                reaches_end=any(getattr(r, flag) for r in records),
            )

    return result


def _period_summaries(keys, intervals, cycles, flag):
    result = {}

    for key in keys:
        if any(not cycles[(key, interval)] for interval in intervals):
            result[key] = None
            continue

        records = [record for interval in intervals for record in cycles[(key, interval)]]
        rank = math.ceil(QUEUE_PERCENTILE / 100 * len(records))

        # Cut-off cycles sort after uncut cycles of the same value: their
        # real queue was longer.
        by_length = sorted(records, key=lambda r: (r.max_queue_length_m, getattr(r, flag)))
        by_vehicles = sorted(records, key=lambda r: (r.max_queue_vehicles, getattr(r, flag)))

        result[key] = LaneQueue(
            length_m=by_length[rank - 1].max_queue_length_m,
            vehicles=by_vehicles[rank - 1].max_queue_vehicles,
            reaches_end=getattr(by_length[rank - 1], flag) or getattr(by_vehicles[rank - 1], flag),
        )

    return result


def _cycles_by_key_and_interval(run_id, keys, intervals, cycle_records, key_field):
    """
    Group the cycle records of one run by lane or approach (key_field)
    and by the interval that contains their cycle_start, after checking
    them.

    Raises ValueError when a record belongs to another run or to a lane
    or approach that is not analysed, or when one has two records for
    the same cycle.
    """

    kind = "lane" if key_field == "lane_id" else "approach"
    groups = {(key, interval): [] for key in keys for interval in intervals}
    analysed = set(keys)
    seen_cycles = set()

    for record in cycle_records:
        key = getattr(record, key_field)

        if record.run_id != run_id:
            raise ValueError(
                f"cycle record of {kind} {key} belongs to run "
                f"{record.run_id}, not {run_id}"
            )

        if key not in analysed:
            raise ValueError(f"{kind} {key} is not analysed")

        cycle_key = (key, record.cycle_start)

        if cycle_key in seen_cycles:
            raise ValueError(
                f"{kind} {key} has two records for the cycle "
                f"starting at {record.cycle_start.isoformat()}"
            )

        seen_cycles.add(cycle_key)

        interval = find_interval(record.cycle_start, intervals)

        if interval is not None:
            groups[(key, interval)].append(record)

    return groups

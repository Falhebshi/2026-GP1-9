"""
Queue length and queue storage ratio, per lane.

Each CycleQueueRecord gives the longest queue on one lane in one
signal cycle. A cycle belongs to the interval that contains its
cycle_start; a cycle that starts in the warm-up or clearance is not
used.

Two summaries are calculated for each lane:
- per interval: the largest cycle queue in that interval;
- over the whole analysis period: the 95th-percentile cycle queue,
  using the nearest-rank method.

A lane with no cycle records has no queue value (None): a record is
written for every lane and cycle, even with no queue, so a missing
record means missing data, not an empty lane.

Works on the records of one run.
"""

import math
from typing import NamedTuple

from backend.analytics.kpi.intervals import AnalysisInterval, find_interval
from backend.analytics.kpi.parameters import QUEUE_PERCENTILE
from jaadah.models.outputs import CycleQueueRecord


class LaneQueue(NamedTuple):
    """A queue in both units: metres and vehicles."""

    length_m: float
    vehicles: int


def interval_queues(
    run_id: str,
    lane_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[CycleQueueRecord],
) -> dict[tuple[str, AnalysisInterval], LaneQueue | None]:
    """
    Return the largest cycle queue of each lane in each interval.

    The value is None when a lane has no cycle record in an interval.
    Metres and vehicles are each the largest of the interval's cycles.
    """

    cycles = _cycles_by_lane_and_interval(
        run_id, lane_ids, intervals, cycle_records
    )

    result = {}

    for lane_id in lane_ids:
        for interval in intervals:
            records = cycles[(lane_id, interval)]

            if not records:
                result[(lane_id, interval)] = None
                continue

            result[(lane_id, interval)] = LaneQueue(
                length_m=max(r.max_queue_length_m for r in records),
                vehicles=max(r.max_queue_vehicles for r in records),
            )

    return result


PERIOD_INCOMPLETE_REASON = (
    "no cycle records in at least one interval of the analysis period"
)


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

    cycles = _cycles_by_lane_and_interval(
        run_id, lane_ids, intervals, cycle_records
    )

    result = {}

    for lane_id in lane_ids:
        if any(not cycles[(lane_id, interval)] for interval in intervals):
            result[lane_id] = None
            continue

        records = [
            record
            for interval in intervals
            for record in cycles[(lane_id, interval)]
        ]

        result[lane_id] = LaneQueue(
            length_m=nearest_rank_percentile(
                [r.max_queue_length_m for r in records], QUEUE_PERCENTILE
            ),
            vehicles=nearest_rank_percentile(
                [r.max_queue_vehicles for r in records], QUEUE_PERCENTILE
            ),
        )

    return result


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


def _cycles_by_lane_and_interval(
    run_id: str,
    lane_ids: list[str],
    intervals: list[AnalysisInterval],
    cycle_records: list[CycleQueueRecord],
) -> dict[tuple[str, AnalysisInterval], list[CycleQueueRecord]]:
    """
    Group the cycle records of one run by lane and by the interval
    that contains their cycle_start, after checking them.

    Raises ValueError when a record belongs to another run or to a
    lane that is not analysed, or when a lane has two records for the
    same cycle.
    """

    groups = {
        (lane_id, interval): []
        for lane_id in lane_ids
        for interval in intervals
    }

    analysed_lanes = set(lane_ids)
    seen_cycles = set()

    for record in cycle_records:
        if record.run_id != run_id:
            raise ValueError(
                f"cycle record of lane {record.lane_id} belongs to run "
                f"{record.run_id}, not {run_id}"
            )

        if record.lane_id not in analysed_lanes:
            raise ValueError(
                f"lane {record.lane_id} is not analysed"
            )

        cycle_key = (record.lane_id, record.cycle_start)

        if cycle_key in seen_cycles:
            raise ValueError(
                f"lane {record.lane_id} has two records for the cycle "
                f"starting at {record.cycle_start.isoformat()}"
            )

        seen_cycles.add(cycle_key)

        interval = find_interval(record.cycle_start, intervals)

        if interval is not None:
            groups[(record.lane_id, interval)].append(record)

    return groups
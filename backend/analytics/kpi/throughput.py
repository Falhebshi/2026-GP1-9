"""
Throughput: the vehicles each movement served, per analysis interval.

A vehicle is served when it crosses the stop line, so it is counted
in the interval that contains its stop_line_time. Vehicles that
crossed the stop line but had not left the zone when the run ended
(IncompletePassage with a stop_line_time) are counted too.

A movement's throughput is unavailable in an interval when vehicles of
its approach could not enter the network before the run ended
(blocked, from delay.uninserted_approaches): they were never served,
so the count would understate the demand the movement could serve.

Works on the records of one run. Combining runs (mean and standard
deviation across seeds) is done elsewhere, the same way for every KPI.
"""

from typing import NamedTuple

from backend.analytics.kpi.intervals import AnalysisInterval, find_interval
from backend.analytics.kpi.parameters import ANALYSIS_INTERVAL_S
from jaadah.models.kpis import KpiStatus
from jaadah.models.outputs import IncompletePassage, VehicleDelayRecord


SECONDS_PER_HOUR = 3600


class MovementThroughput(NamedTuple):
    """Throughput of one movement in one interval of one run."""

    status: KpiStatus
    value_veh_h: float | None
    reason: str | None = None


def count_served_vehicles(
    run_id: str,
    movement_ids: list[str],
    intervals: list[AnalysisInterval],
    delay_records: list[VehicleDelayRecord],
    incomplete_passages: list[IncompletePassage],
) -> dict[tuple[str, AnalysisInterval], int]:
    """
    Count the vehicles of each movement that crossed the stop line in
    each interval of one run.

    Every (movement, interval) pair is in the result, with 0 when no
    vehicle crossed: an interval the run covered with no traffic is a
    measured zero, not a missing value.

    Raises ValueError when a record belongs to another run or to a
    movement that is not analysed, or when a vehicle appears twice.
    """

    counts = {
        (movement_id, interval): 0
        for movement_id in movement_ids
        for interval in intervals
    }

    analysed_movements = set(movement_ids)
    seen_vehicles = set()

    crossings = [
        (record.run_id, record.vehicle_id, record.movement_id,
         record.stop_line_time)
        for record in delay_records
    ] + [
        (passage.run_id, passage.vehicle_id, passage.movement_id,
         passage.stop_line_time)
        for passage in incomplete_passages
        if passage.stop_line_time is not None
    ]

    for record_run_id, vehicle_id, movement_id, stop_line_time in crossings:
        if record_run_id != run_id:
            raise ValueError(
                f"vehicle {vehicle_id} belongs to run {record_run_id}, "
                f"not {run_id}"
            )

        if movement_id not in analysed_movements:
            raise ValueError(
                f"vehicle {vehicle_id} uses movement {movement_id}, "
                "which is not analysed"
            )

        if vehicle_id in seen_vehicles:
            raise ValueError(f"vehicle {vehicle_id} appears more than once")

        seen_vehicles.add(vehicle_id)

        interval = find_interval(stop_line_time, intervals)

        if interval is not None:
            counts[(movement_id, interval)] += 1

    return counts


def vehicles_per_hour(count: int) -> float:
    """Convert a count over one analysis interval to an hourly rate."""

    return count * SECONDS_PER_HOUR / ANALYSIS_INTERVAL_S


def movement_throughput(
    counts: dict[tuple[str, AnalysisInterval], int],
    blocked: dict[tuple[str, AnalysisInterval], str] | None = None,
) -> dict[tuple[str, AnalysisInterval], MovementThroughput]:
    """
    Hourly throughput of each (movement, interval) count, unavailable
    where blocked maps it to a reason.
    """

    blocked = blocked or {}

    return {
        key: (
            MovementThroughput(KpiStatus.UNAVAILABLE, None, blocked[key])
            if key in blocked
            else MovementThroughput(KpiStatus.OK, vehicles_per_hour(count))
        )
        for key, count in counts.items()
    }

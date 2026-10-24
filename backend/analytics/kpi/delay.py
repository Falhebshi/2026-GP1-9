"""
Control delay and queue duration, per movement and analysis interval.

A vehicle's delay belongs to the interval that contains its zone
entry (when it arrived). Its control delay is its time loss in the
zone, and its queue duration is the time it stood still there.

For each movement and interval:
- control delay = the mean time loss of the vehicles that arrived;
- queue duration = the mean time stopped of the same vehicles,
  counting vehicles that did not stop as 0 s.

When a vehicle that arrived in an interval had not finished its
passage when the run ended, the interval's values are unavailable:
its delay is unknown and leaving it out would understate the delay.
When no vehicle arrived, the values are not applicable.

Works on the records of one run. Level of service is not calculated
here: it is graded from the mean delay across seeds, after the runs
are combined.
"""

from statistics import fmean
from typing import NamedTuple

from backend.analytics.kpi.intervals import AnalysisInterval, find_interval
from jaadah.models.kpis import KpiStatus
from jaadah.models.outputs import IncompletePassage, VehicleDelayRecord


NO_ARRIVALS_REASON = "no vehicles arrived in this interval"


class MovementDelay(NamedTuple):
    """
    Delay of one movement in one interval of one run.

    mean_control_delay_s and mean_queue_duration_s are None unless
    status is OK; reason then says why.
    """

    status: KpiStatus
    completed_vehicles: int
    incomplete_vehicles: int
    mean_control_delay_s: float | None
    mean_queue_duration_s: float | None
    reason: str | None


def movement_delays(
    run_id: str,
    movement_ids: list[str],
    intervals: list[AnalysisInterval],
    delay_records: list[VehicleDelayRecord],
    incomplete_passages: list[IncompletePassage],
) -> dict[tuple[str, AnalysisInterval], MovementDelay]:
    """
    Return the delay of each movement in each interval of one run.

    Raises ValueError when a record belongs to another run or to a
    movement that is not analysed, or when a vehicle appears twice.
    """

    _check_records(run_id, movement_ids, delay_records, incomplete_passages)

    completed = {
        (movement_id, interval): []
        for movement_id in movement_ids
        for interval in intervals
    }
    incomplete_counts = {key: 0 for key in completed}

    for record in delay_records:
        interval = find_interval(record.zone_entry_time, intervals)

        if interval is not None:
            completed[(record.movement_id, interval)].append(record)

    for passage in incomplete_passages:
        interval = find_interval(passage.zone_entry_time, intervals)

        if interval is not None:
            incomplete_counts[(passage.movement_id, interval)] += 1

    return {
        key: _summarise(records, incomplete_counts[key])
        for key, records in completed.items()
    }


def _summarise(
    records: list[VehicleDelayRecord],
    incomplete_vehicles: int,
) -> MovementDelay:
    """Turn the vehicles of one movement and interval into a result."""

    if incomplete_vehicles > 0:
        return MovementDelay(
            status=KpiStatus.UNAVAILABLE,
            completed_vehicles=len(records),
            incomplete_vehicles=incomplete_vehicles,
            mean_control_delay_s=None,
            mean_queue_duration_s=None,
            reason=(
                f"{incomplete_vehicles} vehicle(s) had not finished their "
                "passage when the run ended; increase the clearance "
                "duration"
            ),
        )

    if not records:
        return MovementDelay(
            status=KpiStatus.NOT_APPLICABLE,
            completed_vehicles=0,
            incomplete_vehicles=0,
            mean_control_delay_s=None,
            mean_queue_duration_s=None,
            reason=NO_ARRIVALS_REASON,
        )

    return MovementDelay(
        status=KpiStatus.OK,
        completed_vehicles=len(records),
        incomplete_vehicles=0,
        mean_control_delay_s=fmean(r.time_loss_s for r in records),
        mean_queue_duration_s=fmean(r.halted_time_s for r in records),
        reason=None,
    )


def _check_records(
    run_id: str,
    movement_ids: list[str],
    delay_records: list[VehicleDelayRecord],
    incomplete_passages: list[IncompletePassage],
) -> None:
    """
    Raise ValueError when a record belongs to another run or to a
    movement that is not analysed, or when a vehicle appears twice.
    """

    analysed_movements = set(movement_ids)
    seen_vehicles = set()

    for record in [*delay_records, *incomplete_passages]:
        if record.run_id != run_id:
            raise ValueError(
                f"vehicle {record.vehicle_id} belongs to run "
                f"{record.run_id}, not {run_id}"
            )

        if record.movement_id not in analysed_movements:
            raise ValueError(
                f"vehicle {record.vehicle_id} uses movement "
                f"{record.movement_id}, which is not analysed"
            )

        if record.vehicle_id in seen_vehicles:
            raise ValueError(
                f"vehicle {record.vehicle_id} appears more than once"
            )

        seen_vehicles.add(record.vehicle_id)
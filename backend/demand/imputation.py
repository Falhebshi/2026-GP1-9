import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from jaadah.models.traffic import (
    ImputationMethod,
    TrafficObservation,
)


# Imputation limits
INTERVAL = timedelta(minutes=15)

MAX_GAP_INTERVALS = 4

MIN_REGRESSION_INTERVALS = 5 * 96

MIN_HISTORICAL_VALUES = 3


@dataclass(frozen=True)
class ImputedCount:
    """An estimated count for a detector that did not report."""

    site_id: str
    detector_id: str
    vehicle_count: int
    method: ImputationMethod


def day_type(interval_start: datetime) -> str:
    """
    Return the day type of an interval: workday (Sunday to Thursday),
    friday or saturday, as in the RCRC sample analysis.
    """

    weekday = interval_start.weekday()

    if weekday == 4:
        return "friday"

    if weekday == 5:
        return "saturday"

    return "workday"


def build_history_index(
    history: list[TrafficObservation],
) -> dict[tuple, dict[datetime, int]]:
    """
    Return the past counts of each detector, keyed by source, site and
    detector ID, then by interval start.

    A detector interval with different counts is left out, so the index
    does not depend on the order of the observations. A repeated
    identical count is kept once.
    """

    index = defaultdict(dict)
    conflicts = set()

    for observation in history:
        detector_key = (
            observation.source,
            observation.site_id,
            observation.detector_id,
        )
        counts = index[detector_key]
        first_count = counts.setdefault(
            observation.interval_start,
            observation.vehicle_count,
        )

        if first_count != observation.vehicle_count:
            conflicts.add((detector_key, observation.interval_start))

    for detector_key, interval_start in conflicts:
        del index[detector_key][interval_start]

    return index


def fit_neighbour_line(
    target_counts: dict[datetime, int],
    neighbour_counts: dict[datetime, int],
) -> tuple[float, float] | None:
    """
    Fit target = intercept + slope * neighbour on the intervals where
    both detectors reported (Chen et al., 2003).

    Returns None when there are too few common intervals or the
    neighbour's count never changed.
    """

    common = sorted(target_counts.keys() & neighbour_counts.keys())

    if len(common) < MIN_REGRESSION_INTERVALS:
        return None

    x = [neighbour_counts[interval] for interval in common]
    y = [target_counts[interval] for interval in common]
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    spread = sum((value - mean_x) ** 2 for value in x)

    if spread == 0:
        return None

    slope = sum(
        (x_value - mean_x) * (y_value - mean_y)
        for x_value, y_value in zip(x, y)
    ) / spread

    return mean_y - slope * mean_x, slope


def whole_vehicles(estimate: float) -> int:
    """Round an estimate to whole vehicles, never below zero."""

    return max(0, math.floor(estimate + 0.5))


def missing_run_length(
    present: set[datetime],
    interval_start: datetime,
    first_known: datetime,
    last_known: datetime,
) -> int:
    """
    Return how many consecutive intervals around interval_start the
    detector is missing, within the period that has any data.
    """

    length = 1

    for step in (-INTERVAL, INTERVAL):
        current = interval_start + step

        while (
            first_known <= current <= last_known
            and current not in present
        ):
            length += 1
            current += step

    return length


def impute_count(
    target: tuple,
    interval_start: datetime,
    neighbours: list[tuple],
    current_counts: dict[tuple, int],
    history_index: dict[tuple, dict[datetime, int]],
    first_known: datetime,
    last_known: datetime,
) -> ImputedCount | None:
    """
    Estimate the count of a detector that did not report in an interval.

    target and neighbours are (source, site ID, detector ID) keys.
    Neighbours are the other usable detectors on the same approach that
    count the same movement. current_counts holds the counts reported
    in this interval.

    Method 1 uses the neighbours that reported: one regression line per
    neighbour, fitted on history, and the median of their estimates.
    Method 2, used when no neighbour estimate is possible, is the
    average of the detector's past counts in the same time slot and
    day type. Returns None when the gap is longer than
    MAX_GAP_INTERVALS or neither method has enough history.
    """

    _, site_id, detector_id = target
    target_counts = {
        interval: count
        for interval, count in history_index.get(target, {}).items()
        if interval != interval_start
    }

    if missing_run_length(
        present=set(target_counts),
        interval_start=interval_start,
        first_known=first_known,
        last_known=last_known,
    ) > MAX_GAP_INTERVALS:
        return None

    estimates = []

    for neighbour in neighbours:
        if neighbour not in current_counts:
            continue

        line = fit_neighbour_line(
            target_counts=target_counts,
            neighbour_counts=history_index.get(neighbour, {}),
        )

        if line is not None:
            intercept, slope = line
            estimates.append(
                intercept + slope * current_counts[neighbour]
            )

    if estimates:
        return ImputedCount(
            site_id=site_id,
            detector_id=detector_id,
            vehicle_count=whole_vehicles(statistics.median(estimates)),
            method=ImputationMethod.NEIGHBOUR_REGRESSION,
        )

    same_slot = [
        count
        for interval, count in target_counts.items()
        if interval.time() == interval_start.time()
        and day_type(interval) == day_type(interval_start)
    ]

    if len(same_slot) >= MIN_HISTORICAL_VALUES:
        return ImputedCount(
            site_id=site_id,
            detector_id=detector_id,
            vehicle_count=whole_vehicles(statistics.fmean(same_slot)),
            method=ImputationMethod.HISTORICAL_AVERAGE,
        )

    return None

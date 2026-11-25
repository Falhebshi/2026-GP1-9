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

# Longest run of missing intervals that is estimated, counted back from
# the interval being estimated. Chosen by the gap-limit evaluation on the
# RCRC site 1444 report (analysis/rcrc_site_1444/gap_limit_evaluation.py):
# for this long, the hour before the gap still makes the estimate better
# than a typical day. Longer runs stay missing.
MAX_GAP_INTERVALS = 5

# Longest run of missing intervals the live update loop estimates once
# MAX_GAP_INTERVALS is passed, with the plain time-slot average (the hour
# before the gap no longer helps after MAX_GAP_INTERVALS): no limit. Only
# the live loop uses it (fallback_gap_intervals); every other run keeps
# longer gaps missing. The live page shows such intervals as "No detector
# data", so the estimate is never shown as traffic: it only keeps the
# simulation going through the outage, so the queues after it are right.
# A chain restarted after the outage instead would start on empty roads,
# and at a workday evening peak shows far less time loss than the day had
# (docs/live_update_loop.md, 2.5).
LIVE_FALLBACK_GAP_INTERVALS = math.inf

# Intervals before a gap used to measure how busy the day was.
RECENT_LEVEL_INTERVALS = 4

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
) -> int | None:
    """
    Return how many consecutive intervals the detector has been missing,
    counted back from interval_start (included) to its last reported
    interval. This is what a live system knows: how long the detector
    has been silent so far, not how long the gap will last.

    Returns None when the detector has no reported interval before
    interval_start since first_known: there is no data to estimate from.
    """

    length = 1
    current = interval_start - INTERVAL

    while current not in present:
        if current < first_known:
            return None

        length += 1
        current -= INTERVAL

    return length


def slot_average(
    counts: dict[datetime, int],
    moment: datetime,
) -> float | None:
    """
    Return the average count in the time slot and day type of `moment`
    on other days, or None when fewer than MIN_HISTORICAL_VALUES exist.
    """

    values = [
        count
        for interval, count in counts.items()
        if interval.time() == moment.time()
        and interval.date() != moment.date()
        and day_type(interval) == day_type(moment)
    ]

    if len(values) < MIN_HISTORICAL_VALUES:
        return None

    return statistics.fmean(values)


def level_ratio(
    recent_counts: list[int],
    recent_averages: list[float],
) -> float | None:
    """
    How busy the day is compared with a typical day: the counts of the
    intervals before a gap (RECENT_LEVEL_INTERVALS of them, in
    impute_count) divided by their slot averages. None when there are
    none, the lists differ in length, or the typical count is zero.
    """

    if not recent_counts or len(recent_counts) != len(recent_averages):
        return None

    typical = sum(recent_averages)

    if typical <= 0:
        return None

    return sum(recent_counts) / typical


def level_adjusted_estimate(
    average: float,
    ratio: float | None,
) -> int:
    """
    The estimate for a missing interval: its slot average, scaled by the
    level ratio when there is one. Used by impute_count and by the
    gap-limit evaluation, so the evaluation measures this exact rule.
    """

    return whole_vehicles(average * (ratio if ratio is not None else 1.0))


def recent_level(
    counts: dict[datetime, int],
    gap_start: datetime,
) -> float | None:
    """The level ratio of the RECENT_LEVEL_INTERVALS before gap_start."""

    recent = [
        gap_start - step * INTERVAL
        for step in range(RECENT_LEVEL_INTERVALS, 0, -1)
    ]

    if any(interval not in counts for interval in recent):
        return None

    averages = [slot_average(counts, interval) for interval in recent]

    if any(average is None for average in averages):
        return None

    return level_ratio([counts[interval] for interval in recent], averages)


def impute_count(
    target: tuple,
    interval_start: datetime,
    neighbours: list[tuple],
    current_counts: dict[tuple, int],
    history_index: dict[tuple, dict[datetime, int]],
    first_known: datetime,
    last_known: datetime,
    fallback_gap_intervals: int | None = None,
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
    average of the detector's counts in the same time slot and day type
    on other days, scaled by how busy the hour before the gap was
    compared with a typical day (level_adjusted_average). Without a
    complete hour before the gap, the plain average is used
    (historical_average). Returns None when the detector has been
    missing for more than MAX_GAP_INTERVALS, has no earlier data, or
    neither method has enough history.

    fallback_gap_intervals (the live update loop) estimates longer gaps
    too, up to that many intervals: from the neighbours when they
    reported, otherwise with the plain average (historical_average),
    since the hour before the gap no longer helps past
    MAX_GAP_INTERVALS.

    last_known is kept for the callers' signature; the gap is counted
    back from interval_start.
    """

    _, site_id, detector_id = target
    target_counts = {
        interval: count
        for interval, count in history_index.get(target, {}).items()
        if interval != interval_start
    }

    run_length = missing_run_length(
        present=set(target_counts),
        interval_start=interval_start,
        first_known=first_known,
    )

    if run_length is None:
        return None

    long_gap = run_length > MAX_GAP_INTERVALS

    if long_gap and (fallback_gap_intervals is None or run_length > fallback_gap_intervals):
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

    average = slot_average(target_counts, interval_start)

    if average is None:
        return None

    ratio = None if long_gap else recent_level(
        target_counts,
        gap_start=interval_start - (run_length - 1) * INTERVAL,
    )

    return ImputedCount(
        site_id=site_id,
        detector_id=detector_id,
        vehicle_count=level_adjusted_estimate(average, ratio),
        method=(
            ImputationMethod.LEVEL_ADJUSTED_AVERAGE
            if ratio is not None
            else ImputationMethod.HISTORICAL_AVERAGE
        ),
    )

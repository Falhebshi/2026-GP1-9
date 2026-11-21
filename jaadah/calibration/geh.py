"""
Compare simulated and observed hourly counts with the GEH statistic.

    GEH = sqrt(2 (M - C)^2 / (M + C))

M is the simulated and C the observed count, both in vehicles per hour.
GEH is defined on hourly flows, so four 15-minute counts are summed,
never one count multiplied by 4.

A detector-hour is eligible only when all four observed intervals were
reported (an interval the source did not report is never treated as
zero) and all four simulated intervals exist. Several seeds are combined
by averaging their simulated hourly counts before computing GEH.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from .parameters import GEH_THRESHOLD, INTERVALS_PER_HOUR, REQUIRED_PASS_SHARE

INTERVAL = timedelta(minutes=15)

# (detector_id, interval_end) -> vehicles in that 15-minute interval
IntervalCounts = Mapping[tuple[str, datetime], int]


@dataclass(frozen=True)
class HourlyComparison:
    """One eligible detector-hour, labelled by the hour's end."""

    detector_id: str
    hour_end: datetime
    observed: int
    simulated: float

    @property
    def geh(self) -> float:
        return geh(self.simulated, self.observed)

    @property
    def matches(self) -> bool:
        return self.geh < GEH_THRESHOLD


def geh(simulated: float, observed: float) -> float:
    """GEH of two hourly counts. Two zero counts agree exactly (0)."""

    if simulated < 0 or observed < 0:
        raise ValueError("counts must not be negative")

    total = simulated + observed
    if total == 0:
        return 0.0

    return math.sqrt(2 * (simulated - observed) ** 2 / total)


def hourly_count(counts: IntervalCounts, detector_id: str, hour_end: datetime) -> int | None:
    """Sum of the four intervals ending in (hour_end - 1 h, hour_end], or None if any is missing."""

    total = 0
    for step in range(INTERVALS_PER_HOUR):
        value = counts.get((detector_id, hour_end - step * INTERVAL))
        if value is None:
            return None
        total += value
    return total


def compare_hours(
    observed: IntervalCounts,
    simulated_by_seed: list[IntervalCounts],
    detector_ids: Iterable[str],
    hour_ends: Iterable[datetime],
) -> list[HourlyComparison]:
    """
    Return the eligible detector-hours with the mean simulated count.

    A detector-hour is left out when an observed interval is missing or
    any seed lacks a simulated interval.
    """

    if not simulated_by_seed:
        raise ValueError("at least one seed is required")

    hour_ends = list(hour_ends)
    comparisons = []

    for detector_id in detector_ids:
        for hour_end in hour_ends:
            observed_count = hourly_count(observed, detector_id, hour_end)
            if observed_count is None:
                continue

            seed_counts = [hourly_count(run, detector_id, hour_end) for run in simulated_by_seed]
            if any(value is None for value in seed_counts):
                continue

            comparisons.append(
                HourlyComparison(
                    detector_id=detector_id,
                    hour_end=hour_end,
                    observed=observed_count,
                    simulated=sum(seed_counts) / len(seed_counts),
                )
            )

    return comparisons


def pass_share(comparisons: list[HourlyComparison]) -> float | None:
    """Share of comparisons with GEH below the threshold; None when there are none."""

    if not comparisons:
        return None
    return sum(item.matches for item in comparisons) / len(comparisons)


def meets_target(comparisons: list[HourlyComparison]) -> bool | None:
    """Whether the pass share reaches the required share; None when nothing was compared."""

    share = pass_share(comparisons)
    if share is None:
        return None
    return share >= REQUIRED_PASS_SHARE

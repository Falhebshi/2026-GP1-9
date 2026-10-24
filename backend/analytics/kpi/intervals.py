"""
The 15-minute intervals that every KPI of a run is reported over.

The analysis period is given by its start and end (Scenario.start_time
and Scenario.end_time). Warm-up and clearance lie outside it, so they
are never part of any interval.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

from backend.analytics.kpi.parameters import ANALYSIS_INTERVAL_S


RIYADH_OFFSET = timedelta(hours=3)


class AnalysisInterval(NamedTuple):
    """One reporting interval: includes start, excludes end."""

    start: datetime
    end: datetime


def analysis_intervals(
    analysis_start: datetime,
    analysis_end: datetime,
) -> list[AnalysisInterval]:
    """
    Split the analysis period into back-to-back 15-minute intervals.

    Raises ValueError when a time has no timezone or is not in Riyadh
    time (UTC+03:00), when the end is not after the start, or when the
    period is not a whole number of intervals.
    """

    _check_riyadh_time(analysis_start, "analysis_start")
    _check_riyadh_time(analysis_end, "analysis_end")

    if analysis_end <= analysis_start:
        raise ValueError("analysis_end must be after analysis_start")

    period_s = (analysis_end - analysis_start).total_seconds()

    if period_s % ANALYSIS_INTERVAL_S != 0:
        raise ValueError(
            "the analysis period must be a whole number of "
            f"{ANALYSIS_INTERVAL_S // 60}-minute intervals; "
            f"got {period_s / 60:g} minutes"
        )

    step = timedelta(seconds=ANALYSIS_INTERVAL_S)
    count = int(period_s // ANALYSIS_INTERVAL_S)

    return [
        AnalysisInterval(
            start=analysis_start + index * step,
            end=analysis_start + (index + 1) * step,
        )
        for index in range(count)
    ]


def find_interval(
    moment: datetime,
    intervals: list[AnalysisInterval],
) -> AnalysisInterval | None:
    """
    Return the interval that contains moment, or None when moment is
    outside every interval (for example, during warm-up or clearance).
    """

    _check_riyadh_time(moment, "moment")

    for interval in intervals:
        if interval.start <= moment < interval.end:
            return interval

    return None


def _check_riyadh_time(value: datetime, name: str) -> None:
    """Require a timezone-aware datetime in Riyadh time (UTC+03:00)."""

    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")

    if value.utcoffset() != RIYADH_OFFSET:
        raise ValueError(f"{name} must use Riyadh time (UTC+03:00)")
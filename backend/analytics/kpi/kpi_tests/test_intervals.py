from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi.intervals import (
    AnalysisInterval,
    analysis_intervals,
    find_interval,
)


RIYADH = timezone(timedelta(hours=3))

START = datetime(2026, 10, 14, 8, 0, 0, tzinfo=RIYADH)
END = datetime(2026, 10, 14, 9, 0, 0, tzinfo=RIYADH)


def at(hour, minute, second=0):
    """A Riyadh time on the test day."""

    return datetime(2026, 10, 14, hour, minute, second, tzinfo=RIYADH)


# ============================================================
# BUILDING THE INTERVALS
# ============================================================

def test_one_hour_gives_four_intervals():
    intervals = analysis_intervals(START, END)

    assert intervals == [
        AnalysisInterval(at(8, 0), at(8, 15)),
        AnalysisInterval(at(8, 15), at(8, 30)),
        AnalysisInterval(at(8, 30), at(8, 45)),
        AnalysisInterval(at(8, 45), at(9, 0)),
    ]


def test_single_interval():
    intervals = analysis_intervals(START, at(8, 15))

    assert intervals == [AnalysisInterval(at(8, 0), at(8, 15))]


def test_intervals_are_back_to_back():
    intervals = analysis_intervals(START, at(10, 0))

    for previous, following in zip(intervals, intervals[1:]):
        assert previous.end == following.start


def test_interval_fields_can_be_read_by_name():
    interval = analysis_intervals(START, END)[0]

    assert interval.start == at(8, 0)
    assert interval.end == at(8, 15)


def test_period_crossing_midnight():
    intervals = analysis_intervals(at(23, 30), at(23, 30) + timedelta(hours=1))

    assert len(intervals) == 4
    assert intervals[-1].end == datetime(2026, 10, 15, 0, 30, tzinfo=RIYADH)


# ============================================================
# INVALID PERIODS
# ============================================================

@pytest.mark.parametrize("minutes", [50, 10, 61])
def test_period_not_whole_intervals_rejected(minutes):
    with pytest.raises(ValueError, match=f"got {minutes} minutes"):
        analysis_intervals(START, START + timedelta(minutes=minutes))


@pytest.mark.parametrize("end", [START, START - timedelta(minutes=15)])
def test_end_not_after_start_rejected(end):
    with pytest.raises(ValueError, match="must be after"):
        analysis_intervals(START, end)


@pytest.mark.parametrize("field", ["analysis_start", "analysis_end"])
def test_naive_time_rejected(field):
    times = {"analysis_start": START, "analysis_end": END}
    times[field] = times[field].replace(tzinfo=None)

    with pytest.raises(ValueError, match=f"{field} must include timezone"):
        analysis_intervals(**times)


def test_non_riyadh_time_rejected():
    utc_start = datetime(2026, 10, 14, 5, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="Riyadh"):
        analysis_intervals(utc_start, utc_start + timedelta(hours=1))


@pytest.mark.parametrize("bad_value", ["2026-10-14T08:00:00+03:00", None])
def test_non_datetime_rejected(bad_value):
    with pytest.raises(ValueError, match="must be a datetime"):
        analysis_intervals(bad_value, END)


# ============================================================
# FINDING AN INTERVAL
# ============================================================

INTERVALS = analysis_intervals(START, END)


def test_moment_inside_interval():
    assert find_interval(at(8, 20), INTERVALS) == INTERVALS[1]


def test_start_belongs_to_its_own_interval():
    assert find_interval(at(8, 15), INTERVALS) == INTERVALS[1]


def test_moment_just_before_end_stays_in_interval():
    moment = at(8, 15) - timedelta(microseconds=1)

    assert find_interval(moment, INTERVALS) == INTERVALS[0]


def test_first_and_last_moments():
    assert find_interval(at(8, 0), INTERVALS) == INTERVALS[0]
    assert find_interval(at(8, 59, 59), INTERVALS) == INTERVALS[-1]


@pytest.mark.parametrize(
    "moment",
    [at(7, 59, 59), at(9, 0), at(9, 5)],
)
def test_warmup_and_clearance_are_outside(moment):
    """Before 08:00 is warm-up; 09:00 and after is clearance."""

    assert find_interval(moment, INTERVALS) is None


def test_no_intervals():
    assert find_interval(at(8, 20), []) is None


def test_naive_moment_rejected():
    with pytest.raises(ValueError, match="moment must include timezone"):
        find_interval(datetime(2026, 10, 14, 8, 20), INTERVALS)
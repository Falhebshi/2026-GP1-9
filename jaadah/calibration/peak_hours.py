"""
Which hours of a day the model is tested on (peak hours).

Every day gets the two test hours of its day type (parameters.py): a
workday (Sunday to Thursday), a Friday or a Saturday. Times are
Riyadh time; each window is one hour, [start, start + 1 h).
"""

from datetime import date, datetime, time, timedelta, timezone

from .parameters import TEST_HOUR_STARTS

RIYADH = timezone(timedelta(hours=3))


def day_type(day: date) -> str:
    """'friday', 'saturday' or 'workday' (Sunday to Thursday)."""

    weekday = day.weekday()  # Monday = 0
    if weekday == 4:
        return "friday"
    if weekday == 5:
        return "saturday"
    return "workday"


def hour_windows(day: date) -> list[tuple[datetime, datetime]]:
    """The day's test hours as (start, end) pairs, earliest first."""

    windows = []
    for start_text in TEST_HOUR_STARTS[day_type(day)]:
        start = datetime.combine(day, time.fromisoformat(start_text), tzinfo=RIYADH)
        windows.append((start, start + timedelta(hours=1)))
    return sorted(windows)


def days_between(first: date, last: date) -> list[date]:
    """Every day from first to last, both included."""

    if last < first:
        raise ValueError("the last day is before the first day")
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]

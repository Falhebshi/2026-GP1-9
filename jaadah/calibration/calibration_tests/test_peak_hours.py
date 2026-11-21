from datetime import date, timedelta

import pytest

from jaadah.calibration.peak_hours import day_type, days_between, hour_windows


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 8, 30), "workday"),   # Sunday
        (date(2026, 9, 3), "workday"),    # Thursday
        (date(2026, 9, 4), "friday"),
        (date(2026, 9, 5), "saturday"),
    ],
)
def test_day_type(day, expected):
    assert day_type(day) == expected


def test_workday_windows_are_one_hour_in_riyadh_time():
    windows = hour_windows(date(2026, 9, 1))
    assert [(start.strftime("%H:%M"), end.strftime("%H:%M")) for start, end in windows] == [
        ("07:15", "08:15"), ("13:45", "14:45"),
    ]
    assert all(start.utcoffset() == timedelta(hours=3) for start, _ in windows)


def test_midnight_window_belongs_to_its_own_calendar_day():
    windows = hour_windows(date(2026, 9, 4))   # Friday
    first_start, first_end = windows[0]
    assert (first_start.date(), first_start.strftime("%H:%M")) == (date(2026, 9, 4), "00:00")
    assert first_end - first_start == timedelta(hours=1)


def test_windows_are_at_least_three_hours_apart():
    for day in days_between(date(2026, 8, 30), date(2026, 9, 5)):
        (first, _), (second, _) = hour_windows(day)
        assert second - first >= timedelta(hours=3)


def test_days_between_includes_both_ends():
    assert days_between(date(2026, 8, 30), date(2026, 9, 1)) == [
        date(2026, 8, 30), date(2026, 8, 31), date(2026, 9, 1),
    ]
    with pytest.raises(ValueError):
        days_between(date(2026, 9, 1), date(2026, 8, 30))

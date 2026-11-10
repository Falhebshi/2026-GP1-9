"""
The Trends page's data, from a hand-made week of stored days.

The week is Tue 3 Nov to Mon 9 Nov 2026 (Friday 6 and Saturday 7 are
the weekend). Every day, one East-through car arrives at 07:30 with a
chosen time loss; each day has cycle records for every lane in all 96
slots, so queues can be pooled over whole days.
"""

from datetime import date, timedelta

import pytest

from backend.analytics.kpi.parameters import HISTORY_MIN_DAY_SHARE
from backend.analytics.trends_page import (
    HISTORY_SCENARIO_ID,
    build_trends,
    check_coverage,
    expected_days,
    page_weekday,
)
from jaadah.models.kpis import KpiResult
from test_trends import ALL_SLOTS_SET, car, cycles, stored_day


FIRST, LAST = date(2026, 11, 3), date(2026, 11, 9)
WEEK = [FIRST + timedelta(days=n) for n in range(7)]
COMPUTED = {"value_computation", "replication_count", "is_shared_value"}


def week(losses=None, zone_end=None):
    """
    The stored week. losses gives each day's car time loss (default
    20 s + 5 s per day: 20, 25, ... 50); zone_end maps a day to a slot
    in which East's queue reaches its zone end.
    """

    losses = losses or {d: 20 + 5 * n for n, d in enumerate(WEEK)}
    zone_end = zone_end or {}
    stored = {}
    for d in WEEK:
        cut = {("APP_E", zone_end[d])} if d in zone_end else set()
        stored[d] = stored_day(
            d, cars=[car(d, 1, "07:31:00", losses[d], 5)],
            queues=cycles(d, ALL_SLOTS_SET, cut_approach_slots=cut),
        )
    return stored


@pytest.fixture(scope="module")
def full_week():
    return week()


@pytest.fixture(scope="module")
def trends_7_all(full_week):
    return build_trends(full_week, 7, "all")


def valid(result: dict) -> KpiResult:
    """Every result the page receives must be a valid KpiResult."""

    return KpiResult.model_validate({k: v for k, v in result.items() if k not in COMPUTED})


# ============================================================
# DAYS AND COVERAGE
# ============================================================

def test_expected_days_follow_the_day_type():
    assert expected_days(LAST, 7, "all") == WEEK
    assert expected_days(LAST, 7, "weekends") == [date(2026, 11, 6), date(2026, 11, 7)]
    assert len(expected_days(LAST, 7, "weekdays")) == 5


def test_page_weekdays_start_on_sunday():
    assert page_weekday(date(2026, 11, 8)) == 0        # Sunday
    assert page_weekday(date(2026, 11, 7)) == 6        # Saturday


def test_eighty_percent_of_days_with_every_weekday_is_enough():
    """30 days, 24 stored (80 %) with every weekday present."""

    expected = expected_days(date(2026, 11, 30), 30, "all")
    stored = set(expected[6:])                          # the first 6 days missing

    used, reason = check_coverage(expected, stored)

    assert HISTORY_MIN_DAY_SHARE == 0.8
    assert len(used) == 24
    assert reason is None


def test_fewer_than_eighty_percent_of_days_is_not_enough():
    expected = expected_days(date(2026, 11, 30), 30, "all")

    _, reason = check_coverage(expected, set(expected[7:]))     # 23 of 30

    assert reason == "not enough data: 23 of 30 days are stored (at least 24 are needed)"


def test_a_missing_weekday_is_not_enough():
    """
    A 7-day period needs one of each weekday. Without Thursday 5 Nov,
    6 of 7 days (86 %) passes the 80 % share, but the weekday rule stops it.
    """

    _, reason = check_coverage(WEEK, set(WEEK) - {date(2026, 11, 5)})

    assert reason == "not enough data: no Thursday is stored in the period"

    expected = expected_days(date(2026, 11, 30), 30, "all")
    thursdays = {d for d in expected if d.weekday() == 3}
    _, reason = check_coverage(expected, set(expected) - thursdays)   # 26 of 30, no Thursday

    assert reason == "not enough data: no Thursday is stored in the period"


def test_a_period_without_enough_days_says_why(full_week):
    trends = build_trends(full_week, 30, "all")

    assert trends["available"] is False
    assert trends["reason"] == "not enough data: 7 of 30 days are stored (at least 24 are needed)"
    assert trends["period"]["daysUsed"] == 7
    assert len(trends["period"]["missingDays"]) == 23


# ============================================================
# SUMMARY
# ============================================================

def test_the_period_and_its_views(trends_7_all):
    assert trends_7_all["available"] is True
    assert trends_7_all["period"]["start"] == "2026-11-03"
    assert trends_7_all["period"]["end"] == "2026-11-09"
    assert trends_7_all["period"]["daysUsed"] == 7
    assert set(trends_7_all["views"]) == {"all", "APP_E", "APP_N", "APP_S", "APP_W"}
    assert [a["label"] for a in trends_7_all["approaches"]] == ["East", "North", "South", "West"]


def test_summary_delay_is_the_mean_over_every_car(trends_7_all):
    """Seven cars, 20 to 50 s: (20 + 25 + ... + 50) / 7 = 35 s, LOS C (35 is at most 35)."""

    summary = trends_7_all["views"]["all"]["summary"]

    assert summary["control_delay"]["current"]["value"] == pytest.approx(35.0)
    assert summary["level_of_service"]["current"]["los_grade"] == "C"
    # 7 cars crossed in 7 x 96 intervals: mean 7 x 4 veh/h / 672 intervals
    assert summary["throughput"]["current"]["value"] == pytest.approx(7 * 4 / (7 * 96))


def test_every_result_combines_days_of_the_history_scenario(trends_7_all):
    delay = valid(trends_7_all["views"]["all"]["summary"]["control_delay"]["current"])

    assert delay.run_combination.value == "days"
    assert delay.scenario_id == HISTORY_SCENARIO_ID
    assert len(delay.run_ids) == 7
    assert delay.replication_count == 1
    assert delay.interval_start.date() == FIRST
    assert delay.interval_end.date() == LAST + timedelta(days=1)


def test_the_peak_window_is_the_slot_with_the_highest_delay(trends_7_all):
    """Only the 07:30 slot has cars, so it is the peak."""

    peak = trends_7_all["views"]["all"]["summary"]["peakWindow"]

    assert peak["status"] == "ok"
    assert peak["interval_start"].endswith("T07:30:00+03:00")
    assert peak["interval_end"].endswith("T07:45:00+03:00")


def test_the_peak_window_is_unknown_when_a_slot_is_unavailable():
    """East reaches its zone end at 17:00 on one day: that slot could be the peak."""

    trends = build_trends(week(zone_end={date(2026, 11, 4): 68}), 7, "all")
    peak = trends["views"]["all"]["summary"]["peakWindow"]

    assert peak["status"] == "unavailable"
    assert "17:00" in peak["reason"]
    assert peak["interval_start"] is None


# ============================================================
# TREND, WEEKDAYS AND WEEKENDS, HEATMAP
# ============================================================

def test_the_trend_has_one_value_per_day(trends_7_all):
    series = trends_7_all["views"]["all"]["trend"]["series"]["control_delay"]

    assert [p["date"] for p in series] == [d.isoformat() for d in WEEK]
    assert [p["result"]["value"] for p in series] == pytest.approx([20, 25, 30, 35, 40, 45, 50])


def test_the_trend_reference_lines_come_from_the_los_thresholds(trends_7_all):
    lines = trends_7_all["views"]["all"]["trend"]["referenceLines"]

    assert [(l["value"], l["label"]) for l in lines["control_delay"]] == [
        (10.0, "LOS A/B"), (20.0, "LOS B/C"), (35.0, "LOS C/D"), (55.0, "LOS D/E"), (80.0, "LOS E/F"),
    ]
    assert lines["volume_to_capacity_ratio"] == [{"value": 1.0, "label": "Capacity"}]


def test_weekdays_and_weekends_each_use_their_own_days(trends_7_all):
    """Weekends: Fri 6 (35 s) and Sat 7 (40 s) = 37.5 s; weekdays: the other five = 33 s."""

    pair = trends_7_all["views"]["all"]["weekdayWeekend"]["control_delay"]

    assert pair["weekends"]["value"] == pytest.approx(37.5)
    assert pair["weekdays"]["value"] == pytest.approx((20 + 25 + 30 + 45 + 50) / 5)


def test_heatmap_cells_outside_the_day_type_say_so(full_week):
    cells = build_trends(full_week, 7, "weekends")["views"]["all"]["heatmap"]

    assert len(cells) == 7 * 24
    tuesday_7am = next(c for c in cells if c["day"] == 2 and c["hour"] == 7)
    saturday_7am = next(c for c in cells if c["day"] == 6 and c["hour"] == 7)

    assert tuesday_7am["result"]["reason"] == "not part of the selected day type"
    assert saturday_7am["delay"]["value"] == pytest.approx(40.0)     # Sat 7 Nov's car


# ============================================================
# LOS DISTRIBUTION AND BREAKDOWN
# ============================================================

def test_unavailable_intervals_are_a_share_of_their_own():
    """
    East: 7 graded intervals (one car a day) and 1 unavailable interval
    (zone end at 08:00 on Wed 4 Nov); intervals without cars are not
    counted. Unavailable = 1 / 8 = 0.125; the 7 grades share the rest.
    """

    trends = build_trends(week(zone_end={date(2026, 11, 4): 32}), 7, "all")
    east = next(r for r in trends["losDistribution"] if r["element"]["id"] == "APP_E")

    assert east["intervals"] == 8
    assert east["shares"]["unavailable"] == pytest.approx(0.125)
    assert sum(v for v in east["shares"].values()) == pytest.approx(1.0, abs=0.002)


def test_the_breakdown_has_the_whole_day_and_every_hour(trends_7_all):
    breakdown = trends_7_all["breakdown"]

    assert list(breakdown)[:2] == ["whole-day", "hour-00"]
    assert len(breakdown) == 25
    seven = breakdown["hour-07"]
    east = next(a for a in seven["approaches"] if a["approach_id"] == "APP_E")
    through = next(m for m in east["movements"] if m["movement_id"] == "MOV_E_W")

    assert through["label"] == "Through"
    assert through["results"]["control_delay"]["value"] == pytest.approx(35.0)
    assert set(through["results"]) == {
        "control_delay", "level_of_service", "volume_to_capacity_ratio", "queue_length",
        "queue_storage_ratio", "queue_duration", "throughput",
    }


def test_every_breakdown_result_is_a_valid_kpi_result(trends_7_all):
    window = trends_7_all["breakdown"]["whole-day"]
    for approach in window["approaches"]:
        for result in approach["results"].values():
            valid(result)
        for movement in approach["movements"]:
            for result in movement["results"].values():
                valid(result)
    for result in window["intersection"]["results"].values():
        valid(result)

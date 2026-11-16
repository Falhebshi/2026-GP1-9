from datetime import datetime, timedelta, timezone

from analysis.rcrc_site_1444.gap_limit_evaluation import (
    evaluate,
    gap_limit,
    geh,
    past_slot_averages,
)


RIYADH = timezone(timedelta(hours=3))
STEP = timedelta(minutes=15)
START = datetime(2026, 7, 5, tzinfo=RIYADH)  # a Sunday


def row(position, error_plain, error_adjusted, geh_plain, geh_adjusted):
    return {
        "position": position,
        "error_plain": error_plain,
        "error_adjusted": error_adjusted,
        "geh_plain": geh_plain,
        "geh_adjusted": geh_adjusted,
        "cases": 1,
    }


def test_limit_is_the_last_position_better_on_both_measures():
    results = [
        row(1, 0.20, 0.15, 0.77, 0.87),
        row(2, 0.20, 0.18, 0.77, 0.80),
        row(3, 0.20, 0.21, 0.77, 0.78),  # error worse
        row(4, 0.20, 0.19, 0.77, 0.79),  # better again, but too late
    ]

    assert gap_limit(results) == 2


def test_no_limit_when_the_first_position_is_not_better():
    assert gap_limit([row(1, 0.20, 0.20, 0.77, 0.90)]) == 0


def test_geh_uses_hourly_flows():
    assert geh(10, 10) == 0
    assert geh(0, 0) == 0
    assert round(geh(30, 20), 3) == round(((2 * 40**2) / 200) ** 0.5, 3)


def test_slot_averages_use_earlier_days_only():
    counts = {
        START + timedelta(days=7 * week): value
        for week, value in enumerate([10, 20, 30, 40])
    }

    averages = past_slot_averages(counts)

    assert [averages[m] for m in sorted(counts)] == [None, None, None, 20.0]


def test_level_adjustment_helps_when_busy_days_stay_busy():
    """
    Every day alternates between busy (x2) and quiet (x1) for the whole
    day, so the hour before an outage predicts the outage.
    """

    counts = {"1": {}}

    for day in range(60):
        level = 2 if day % 2 else 1
        for step in range(96):
            moment = START + timedelta(days=day) + step * STEP
            counts["1"][moment] = 10 * level

    outages, results = evaluate(counts, every=7)

    assert outages > 0
    assert results[0]["error_adjusted"] < results[0]["error_plain"]


def test_deviation_persistence_of_steady_days_is_high():
    from analysis.rcrc_site_1444.gap_limit_evaluation import deviation_persistence

    counts = {"1": {}}

    for day in range(40):
        level = 2 if day % 2 else 1
        for step in range(96):
            counts["1"][START + timedelta(days=day) + step * STEP] = 10 * level

    assert deviation_persistence(counts, lags=(1,))[1] > 0.9

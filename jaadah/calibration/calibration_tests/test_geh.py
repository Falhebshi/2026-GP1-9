from datetime import datetime, timedelta, timezone

import pytest

from jaadah.calibration.geh import (
    HourlyComparison,
    compare_hours,
    geh,
    hourly_count,
    meets_target,
    pass_share,
)

RIYADH = timezone(timedelta(hours=3))
HOUR_END = datetime(2026, 9, 1, 8, 0, tzinfo=RIYADH)
Q = timedelta(minutes=15)


def counts(detector_id, values, hour_end=HOUR_END):
    """Four 15-minute counts, oldest first, ending at hour_end."""
    return {(detector_id, hour_end - (3 - i) * Q): value for i, value in enumerate(values)}


# ============================================================
# GEH
# ============================================================

@pytest.mark.parametrize(
    ("simulated", "observed", "expected"),
    [
        (660, 600, 2.390),   # 60 apart on 1,260 -> sqrt(7,200 / 1,260)
        (780, 600, 6.852),
        (600, 600, 0.0),
        (0, 0, 0.0),
        (10, 0, 4.472),      # sqrt(2 * 100 / 10)
    ],
)
def test_geh_values(simulated, observed, expected):
    assert geh(simulated, observed) == pytest.approx(expected, abs=1e-3)


def test_geh_is_symmetric():
    assert geh(500, 620) == pytest.approx(geh(620, 500))


def test_geh_rejects_negative_counts():
    with pytest.raises(ValueError):
        geh(-1, 10)


# ============================================================
# HOURLY COUNTS
# ============================================================

def test_hourly_count_sums_four_intervals():
    assert hourly_count(counts("D1", [100, 110, 120, 130]), "D1", HOUR_END) == 460


def test_hourly_count_is_none_when_an_interval_is_missing():
    data = counts("D1", [100, 110, 120, 130])
    del data[("D1", HOUR_END - Q)]
    assert hourly_count(data, "D1", HOUR_END) is None


def test_hourly_count_keeps_a_reported_zero():
    assert hourly_count(counts("D1", [0, 0, 0, 0]), "D1", HOUR_END) == 0


# ============================================================
# COMPARISONS
# ============================================================

def test_compare_hours_averages_seeds():
    observed = counts("D1", [150, 150, 150, 150])            # 600
    seeds = [counts("D1", [160, 160, 160, 160]),              # 640
             counts("D1", [170, 170, 170, 170])]              # 680
    [result] = compare_hours(observed, seeds, ["D1"], [HOUR_END])
    assert result.observed == 600
    assert result.simulated == 660
    assert result.geh == pytest.approx(2.390, abs=1e-3)
    assert result.matches


def test_compare_hours_skips_missing_observations_and_seeds():
    observed = {**counts("D1", [150] * 4), **counts("D2", [150] * 4)}
    del observed[("D2", HOUR_END)]
    full = {**counts("D1", [150] * 4), **counts("D2", [150] * 4)}
    partial = dict(full)
    del partial[("D1", HOUR_END)]

    assert [c.detector_id for c in compare_hours(observed, [full], ["D1", "D2"], [HOUR_END])] == ["D1"]
    assert compare_hours(observed, [full, partial], ["D1", "D2"], [HOUR_END]) == []


def test_compare_hours_needs_a_seed():
    with pytest.raises(ValueError):
        compare_hours({}, [], ["D1"], [HOUR_END])


# ============================================================
# PASS SHARE
# ============================================================

def comparison(observed, simulated):
    return HourlyComparison("D1", HOUR_END, observed, simulated)


def test_pass_share_and_target():
    passing = [comparison(600, 610)] * 17
    failing = [comparison(600, 800)] * 3
    assert pass_share(passing + failing) == pytest.approx(0.85)
    assert meets_target(passing + failing) is True
    assert meets_target(passing[:16] + failing) is False   # 16 / 19 = 0.842


def test_nothing_compared_is_not_a_pass():
    assert pass_share([]) is None
    assert meets_target([]) is None

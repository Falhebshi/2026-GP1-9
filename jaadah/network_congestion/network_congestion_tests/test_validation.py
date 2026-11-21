from datetime import date, datetime, timedelta

import numpy as np
import pytest

from jaadah.network_congestion.observed import speed_percent
from jaadah.network_congestion.storage import RIYADH
from jaadah.network_congestion.validation import (
    daily_shape_correlations,
    day_type,
    peak_hour,
    rank_agreement,
    speed_to_volume_to_capacity,
)

# Artificial series, not RCRC counts
DAY = datetime(2026, 9, 16, tzinfo=RIYADH)


def series(day, values):
    return {day + timedelta(minutes=15 * i): v for i, v in enumerate(values)}


def test_a_day_wide_factor_does_not_change_the_shape_score():
    shape = 1 + np.sin(np.linspace(0, 6, 96)) ** 2
    observed = series(DAY, shape)
    model = series(DAY, 1.3 * shape)

    assert daily_shape_correlations(observed, model)[DAY.date()] == pytest.approx(1.0)


def test_days_with_too_few_common_intervals_are_left_out():
    observed = series(DAY, np.arange(10.0))

    assert daily_shape_correlations(observed, observed) == {}


def test_peak_hour_is_the_busiest_four_quarter_hours():
    values = np.ones(96)
    values[17 * 4 + 1:17 * 4 + 5] = 5          # 17:15 to 18:15

    assert peak_hour(series(DAY, values), range(15, 19)) == pytest.approx(17.25)


def test_rank_agreement_scores_order_and_busiest_approach():
    observed = {"N": 0.9, "E": 0.5, "S": 0.3, "W": 0.7}

    assert rank_agreement(observed, observed) == (pytest.approx(1.0), True)
    rho, same = rank_agreement(observed, {"N": 0.3, "E": 0.5, "S": 0.9, "W": 0.7})
    assert rho < 0 and not same
    assert rank_agreement({"N": 1.0}, {"N": 1.0}) is None


def test_speed_back_to_v_c_inverts_the_bpr_speed():
    vc = np.array([0.5, 1.0, 1.5])

    back = speed_to_volume_to_capacity(speed_percent(vc))

    assert back == pytest.approx(vc, abs=0.05)


def test_day_types():
    assert day_type(date(2026, 9, 18)) == "Friday"
    assert day_type(date(2026, 9, 19)) == "Saturday"
    assert day_type(date(2026, 9, 16)) == "workday"

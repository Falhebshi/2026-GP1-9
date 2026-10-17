import pytest

from backend.analytics.kpi.parameters import (
    ANALYSIS_INTERVAL_S,
    BASE_SATURATION_FLOW_PC_H_LN,
    LOS_THRESHOLDS,
    VOLUME_TO_CAPACITY_LOS_F,
    level_of_service,
)
from jaadah.models.kpis import LevelOfServiceGrade


# ============================================================
# CONSTANTS
# ============================================================

def test_analysis_interval_is_15_minutes():
    assert ANALYSIS_INTERVAL_S == 900


def test_base_saturation_flow():
    assert BASE_SATURATION_FLOW_PC_H_LN == 1900


def test_los_thresholds_match_hcm():
    assert LOS_THRESHOLDS == (
        (10.0, LevelOfServiceGrade.A),
        (20.0, LevelOfServiceGrade.B),
        (35.0, LevelOfServiceGrade.C),
        (55.0, LevelOfServiceGrade.D),
        (80.0, LevelOfServiceGrade.E),
    )


def test_los_thresholds_increase():
    limits = [limit for limit, _ in LOS_THRESHOLDS]

    assert limits == sorted(limits)


def test_volume_to_capacity_limit():
    assert VOLUME_TO_CAPACITY_LOS_F == 1.0


# ============================================================
# GRADE FROM DELAY
# ============================================================

@pytest.mark.parametrize(
    "delay, expected",
    [
        (0, LevelOfServiceGrade.A),
        (5.0, LevelOfServiceGrade.A),
        (15.0, LevelOfServiceGrade.B),
        (27.5, LevelOfServiceGrade.C),
        (42.0, LevelOfServiceGrade.D),
        (70.0, LevelOfServiceGrade.E),
        (150.0, LevelOfServiceGrade.F),
    ],
)
def test_grade_inside_each_band(delay, expected):
    assert level_of_service(delay) == expected


@pytest.mark.parametrize(
    "delay, expected",
    [
        (10.0, LevelOfServiceGrade.A),
        (20.0, LevelOfServiceGrade.B),
        (35.0, LevelOfServiceGrade.C),
        (55.0, LevelOfServiceGrade.D),
        (80.0, LevelOfServiceGrade.E),
    ],
)
def test_delay_on_threshold_gets_better_grade(delay, expected):
    assert level_of_service(delay) == expected


@pytest.mark.parametrize(
    "delay, expected",
    [
        (10.01, LevelOfServiceGrade.B),
        (20.01, LevelOfServiceGrade.C),
        (35.01, LevelOfServiceGrade.D),
        (55.01, LevelOfServiceGrade.E),
        (80.01, LevelOfServiceGrade.F),
    ],
)
def test_delay_just_above_threshold_gets_next_grade(delay, expected):
    assert level_of_service(delay) == expected


def test_integer_delay_is_accepted():
    assert level_of_service(42) == LevelOfServiceGrade.D


# ============================================================
# VOLUME-TO-CAPACITY OVERRIDE
# ============================================================

def test_over_capacity_is_f_whatever_the_delay():
    assert level_of_service(5.0, volume_to_capacity=1.01) == (
        LevelOfServiceGrade.F
    )


@pytest.mark.parametrize("ratio", [0, 0.85, 1.0])
def test_at_or_below_capacity_grade_comes_from_delay(ratio):
    assert level_of_service(5.0, volume_to_capacity=ratio) == (
        LevelOfServiceGrade.A
    )


def test_without_ratio_grade_comes_from_delay():
    """Approach and intersection level: no v/c is passed."""

    assert level_of_service(5.0) == LevelOfServiceGrade.A


# ============================================================
# INVALID INPUT
# ============================================================

@pytest.mark.parametrize(
    "bad_value",
    [-0.1, float("nan"), float("inf"), True, False, "42", None],
)
def test_invalid_delay_rejected(bad_value):
    with pytest.raises(ValueError, match="control_delay_s"):
        level_of_service(bad_value)


@pytest.mark.parametrize(
    "bad_value",
    [-0.1, float("nan"), float("inf"), True, "1.2"],
)
def test_invalid_ratio_rejected(bad_value):
    with pytest.raises(ValueError, match="volume_to_capacity"):
        level_of_service(5.0, volume_to_capacity=bad_value)
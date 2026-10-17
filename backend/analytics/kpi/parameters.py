"""
Constants used by the KPI engine, and the level-of-service function.

Every value taken from the Highway Capacity Manual (HCM) 6th edition
or chosen for Jaadah is defined here once. Other engine files import
these names instead of writing the numbers themselves.
"""

import math

from jaadah.models.kpis import LevelOfServiceGrade


# ============================================================
# SATURATION FLOW
# ============================================================

# HCM 6th edition base saturation flow for metropolitan areas of
# 250,000 people or more (1,750 applies to smaller areas).
BASE_SATURATION_FLOW_PC_H_LN = 1900


# ============================================================
# LEVEL OF SERVICE
# ============================================================

# HCM 6th edition thresholds for signalized intersections: the
# highest control delay (s/veh) each grade allows, from best to
# worst. A delay exactly on a threshold gets the better grade.
# Any delay above the last threshold is LOS F.
LOS_THRESHOLDS: tuple[tuple[float, LevelOfServiceGrade], ...] = (
    (10.0, LevelOfServiceGrade.A),
    (20.0, LevelOfServiceGrade.B),
    (35.0, LevelOfServiceGrade.C),
    (55.0, LevelOfServiceGrade.D),
    (80.0, LevelOfServiceGrade.E),
)

# A lane group whose volume-to-capacity ratio is above this value is
# LOS F whatever its delay. Applies only at lane-group and movement
# level; approach and intersection LOS come from delay alone.
VOLUME_TO_CAPACITY_LOS_F = 1.0


def level_of_service(
    control_delay_s: float,
    volume_to_capacity: float | None = None,
) -> LevelOfServiceGrade:
    """
    Return the HCM level of service for a control delay (s/veh).

    volume_to_capacity is given only at lane-group and movement level:
    when it is above VOLUME_TO_CAPACITY_LOS_F the result is LOS F
    whatever the delay. At approach and intersection level it is left
    out, and the grade comes from the delay alone.

    Raises ValueError for a delay or ratio that is negative, not a
    finite number, or a boolean.
    """

    _check_non_negative_number(control_delay_s, "control_delay_s")

    if volume_to_capacity is not None:
        _check_non_negative_number(volume_to_capacity, "volume_to_capacity")

        if volume_to_capacity > VOLUME_TO_CAPACITY_LOS_F:
            return LevelOfServiceGrade.F

    for upper_limit, grade in LOS_THRESHOLDS:
        if control_delay_s <= upper_limit:
            return grade

    return LevelOfServiceGrade.F


def _check_non_negative_number(value: float, name: str) -> None:
    """Reject booleans, non-numbers, NaN, infinity and negative values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")

    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")

    if value < 0:
        raise ValueError(f"{name} must not be negative")
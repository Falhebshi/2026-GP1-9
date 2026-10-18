"""
Constants used by the KPI engine, and the level-of-service function.

Every value taken from the Highway Capacity Manual (HCM) 6th edition
or chosen for Jaadah is defined here once. Other engine files import
these names instead of writing the numbers themselves.
"""

import math

from jaadah.models.kpis import LevelOfServiceGrade


# ============================================================
# ANALYSIS INTERVALS
# ============================================================

# Length of one KPI reporting interval: 15 minutes, the HCM analysis
# period.
ANALYSIS_INTERVAL_S = 900


# ============================================================
# QUEUE
# ============================================================

# Percentile of the cycle maximum queues reported over the whole
# analysis period (nearest-rank method, see queue.py).
QUEUE_PERCENTILE = 95


# ============================================================
# SATURATION FLOW
# ============================================================

# HCM 6th edition base saturation flow for metropolitan areas of
# 250,000 people or more (1,750 applies to smaller areas).
BASE_SATURATION_FLOW_PC_H_LN = 1900


# Adjustment factors (HCM signalized intersections, to be verified
# against the HCM 7th edition). See docs/kpi_engine.md section 9.2.

# Lane width: below 10 ft the factor is 0.96, above 12.9 ft it is
# 1.04, in between 1.00. Applied to the average width of a lane group.
LANE_WIDTH_NARROW_LIMIT_M = 3.048   # 10 ft
LANE_WIDTH_WIDE_LIMIT_M = 3.932     # 12.9 ft
LANE_WIDTH_FACTOR_NARROW = 0.96
LANE_WIDTH_FACTOR_NORMAL = 1.00
LANE_WIDTH_FACTOR_WIDE = 1.04

# Lane utilisation by number of lanes in the group (HCM defaults for
# through lanes, also used for the North approach's three exclusive
# left-turn lanes until a verified value is available).
LANE_UTILIZATION_FACTORS = {1: 1.000, 2: 0.952, 3: 0.908}

# A protected left-turning vehicle counts as 1.05 through vehicles.
LEFT_TURN_EQUIVALENT = 1.05

# Factors that have no effect at the case-study intersection.
HEAVY_VEHICLE_FACTOR = 1.0       # passenger cars only (VehicleType)
GRADE_FACTOR = 1.0               # no grade data; 0 % assumed
PARKING_FACTOR = 1.0             # no on-street parking at stop lines
BUS_BLOCKAGE_FACTOR = 1.0        # buses are outside Jaadah's scope
AREA_TYPE_FACTOR = 1.0           # not a central business district
PEDESTRIAN_BICYCLE_FACTOR = 1.0  # few pedestrians on these approaches
CAV_FACTOR = 1.0                 # no connected or automated vehicles

# Lost time per phase (start-up plus clearance), in seconds.
LOST_TIME_PER_PHASE_S = 5.0


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
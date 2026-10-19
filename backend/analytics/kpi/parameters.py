"""
Constants used by the KPI engine, and the level-of-service function.

Every value taken from the Highway Capacity Manual (HCM) 7th edition
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
# SATURATION FLOW (HCM 7th edition, Chapter 19)
# ============================================================

# Base saturation flow for metropolitan areas of 250,000 people or
# more; 1,750 applies to smaller areas (Exhibit 19-11).
BASE_SATURATION_FLOW_PC_H_LN = 1900

# Adjustment factors of Equation 19-8. See docs/kpi_engine.md 9.2.

# Lane width (Exhibit 19-20): below 10.0 ft 0.96, above 12.9 ft 1.04,
# in between 1.00, applied to the average width of a lane group. The
# factor may not be used for an average width below 8.0 ft.
LANE_WIDTH_MINIMUM_M = 2.4384       # 8.0 ft
LANE_WIDTH_NARROW_LIMIT_M = 3.048   # 10.0 ft
LANE_WIDTH_WIDE_LIMIT_M = 3.932     # 12.9 ft
LANE_WIDTH_FACTOR_NARROW = 0.96
LANE_WIDTH_FACTOR_NORMAL = 1.00
LANE_WIDTH_FACTOR_WIDE = 1.04

# Default lane utilisation by movement type and number of lanes
# (Exhibit 19-15). For more lanes than listed, the smallest value of
# the same type is used (note to Exhibit 19-15). A lane group with one
# lane, exclusive or shared, has 1.0.
LANE_UTILIZATION_FACTORS = {
    "through": {1: 1.000, 2: 0.952, 3: 0.908},
    "left": {1: 1.000, 2: 0.971},
    "right": {1: 1.000, 2: 0.885},
}

# A protected left-turning vehicle counts as 1.05 through vehicles
# (Equation 19-14).
LEFT_TURN_EQUIVALENT = 1.05

# Critical merge headway for a lane change (Chapter 31, page 31-27);
# the maximum flow rate at which a lane change can occur is
# 3,600 / 3.7 = 973 veh/h/ln.
LANE_CHANGE_CRITICAL_HEADWAY_S = 3.7

# Factors that have no effect at the case-study intersection; each is
# 1.0 when the condition is absent (pages 19-45 to 19-49).
HEAVY_VEHICLE_GRADE_FACTOR = 1.0       # passenger cars only, 0 % grade
PARKING_FACTOR = 1.0                   # no on-street parking
BUS_BLOCKAGE_FACTOR = 1.0              # buses are outside Jaadah's scope
AREA_TYPE_FACTOR = 1.0                 # not a central business district
PEDESTRIAN_BICYCLE_FACTOR = 1.0        # few pedestrians on these approaches
WORK_ZONE_FACTOR = 1.0                 # no work zone
DOWNSTREAM_LANE_BLOCKAGE_FACTOR = 1.0  # no downstream lane closure
SUSTAINED_SPILLBACK_FACTOR = 1.0       # no spillback modelled
CAV_FACTOR = 1.0                       # no connected or automated vehicles


# ============================================================
# SIGNAL TIMING (HCM 7th edition, Chapter 19)
# ============================================================

# Start-up lost time l1 and extension of effective green e (Equations
# 19-2 and 19-3). Effective green g = G + Y + Rc - l1 - l2, with
# clearance lost time l2 = Y + Rc - e, so g = G - l1 + e; the phase
# lost time is l1 + l2.
START_UP_LOST_TIME_S = 2.0
EFFECTIVE_GREEN_EXTENSION_S = 2.0


# ============================================================
# CONTROL DELAY (HCM 7th edition, Chapter 19, Step 8)
# ============================================================

# Platoon ratio 1.0 = arrival type 3, random arrivals (Exhibit 19-13);
# arrival type 3 applies to isolated signals or signals more than
# 3,200 ft apart (Exhibit 19-14). It gives a progression factor of 1.
PLATOON_RATIO = 1.0

# Incremental delay factor k for pretimed phases (page 19-51).
INCREMENTAL_DELAY_FACTOR = 0.5

# Upstream filtering adjustment factor I for an isolated
# intersection (Exhibit 19-11).
UPSTREAM_FILTERING_FACTOR = 1.0


# ============================================================
# LEVEL OF SERVICE
# ============================================================

# HCM 7th edition thresholds for signalized intersections (Exhibit
# 19-8): the highest control delay (s/veh) each grade allows, from
# best to worst. A delay exactly on a threshold gets the better grade.
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
# level; approach and intersection LOS come from delay alone
# (note to Exhibit 19-8).
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
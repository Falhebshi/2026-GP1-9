"""
Constants for the network map, and the capacity and level functions.

Every value from the Highway Capacity Manual (HCM) 7th edition or
chosen for Jaadah is defined here once. Where each value comes from is
explained in Macro_Map_Implementation (sections 4.1, 4.2 and 4.4).
"""

from jaadah.models.network_congestion import (
    CongestionLevel,
    RoadClass,
    RoadSegment,
)


# ============================================================
# INTERVALS
# ============================================================

# One value per segment every 15 minutes, as the KPI engine
INTERVAL_S = 900
INTERVALS_PER_DAY = 96

# Days of history kept for the map (one weekly cycle)
HISTORY_DAYS = 7


# ============================================================
# CAPACITY (HCM 7th edition)
# ============================================================

# Segments ending at a signal: lanes x saturation flow x green share,
# as the KPI engine (Exhibit 19-11, Equation 19-16).
BASE_SATURATION_FLOW_VEH_H_LN = 1900

# Green share (green / cycle) used until a road's real timing plan is
# known: the average of the INT_001 and RCRC site 1028 timing plans,
# main-road approaches and side-road approaches.
GREEN_SHARE_MAIN = 0.26
GREEN_SHARE_SIDE = 0.13

MAIN_ROAD_CLASSES = {
    RoadClass.MOTORWAY,
    RoadClass.TRUNK,
    RoadClass.PRIMARY,
}

# Motorway and trunk segments without a signal at the end: capacity
# per lane of a basic freeway segment by free-flow speed (Chapter 12),
# highest speed first. Below the last speed the last capacity is used.
# HCM gives passenger cars; Jaadah has cars only, so cars = vehicles.
FREEWAY_CLASSES = {
    RoadClass.MOTORWAY,
    RoadClass.TRUNK,
}
FREEWAY_CAPACITY_VEH_H_LN = [
    (113, 2400),
    (105, 2350),
    (97, 2300),
    (0, 2250),
]

# Primary and secondary segments without a signal at the end are city
# streets that still meet other roads, so they get the base
# saturation flow per lane with no green share, not freeway capacity
CITY_STREET_CAPACITY_VEH_H_LN = BASE_SATURATION_FLOW_VEH_H_LN


# ============================================================
# LEVELS (team choice, not an HCM table)
# ============================================================

# v/c from which a segment is moderate, and from which it is high
MODERATE_FROM_VC = 0.60
HIGH_FROM_VC = 0.85


# ============================================================
# SYNTHETIC VOLUMES
# ============================================================

# v/c of a road at the busiest moment of the day, before its road
# factor (site 1028: busiest 15 minutes per approach gave a median of
# about 0.99, the 95th percentile a median of 0.81)
PEAK_VC = 0.95

# Every road is multiplied by a fixed factor in this range, so roads
# do not all peak at the same level
ROAD_FACTOR_RANGE = (0.7, 1.1)

# Random variation of a 15-minute count around its expected value
# (site 1028 workdays: standard deviation about 17 %), limited so a
# single interval cannot swing too far
NOISE_SD = 0.15
NOISE_LIMIT = 0.4

# Same seed as the baseline run: the same seed, segment and time
# always give the same value
SEED = 42


# ============================================================
# FUNCTIONS
# ============================================================

def segment_capacity(segment: RoadSegment) -> float:
    """Return a segment's capacity in vehicles per hour."""

    if segment.signal_at_end:
        green_share = (
            GREEN_SHARE_MAIN
            if segment.road_class in MAIN_ROAD_CLASSES
            else GREEN_SHARE_SIDE
        )

        return (
            segment.lane_count
            * BASE_SATURATION_FLOW_VEH_H_LN
            * green_share
        )

    if segment.road_class not in FREEWAY_CLASSES:
        return segment.lane_count * CITY_STREET_CAPACITY_VEH_H_LN

    for speed_kmh, capacity in FREEWAY_CAPACITY_VEH_H_LN:
        if segment.free_flow_speed_kmh >= speed_kmh:
            return segment.lane_count * capacity

    raise AssertionError("the capacity table ends at 0 km/h")


def congestion_level(volume_to_capacity: float) -> CongestionLevel:
    """Return the map level of a v/c ratio."""

    if volume_to_capacity < 0:
        raise ValueError("v/c must not be negative")

    if volume_to_capacity >= HIGH_FROM_VC:
        return CongestionLevel.HIGH

    if volume_to_capacity >= MODERATE_FROM_VC:
        return CongestionLevel.MODERATE

    return CongestionLevel.LOW

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
# LEVELS
# ============================================================

# v/c-based level of service bands for signalised intersections
# (City of Roseville, CA): A up to 0.60, B to 0.70, C to 0.81, D to
# 0.90, E to 1.00, F above. HCM grades intersections by delay, so it
# has no such table. Kept for roads with measured counts (RCRC); the
# map colours below use speed. Three groups:
#   low       LOS A and B  v/c up to 0.70
#   moderate  LOS C and D  above 0.70, up to 0.90
#   high      LOS E and F  above 0.90 (near or over capacity)
LOW_UP_TO_VC = 0.70
MODERATE_UP_TO_VC = 0.90


# Level by speed, used for the map colours: HCM urban street segment
# level of service by travel speed as a share of free-flow speed (HCM
# 2010, Urban Streets; to be checked against the HCM 7th edition
# copy): A above 85 %, B 67-85, C 50-67, D 40-50, E 30-40, F 30 or
# less. The same three groups as the v/c bands above:
#   low       LOS A and B  speed above 67 % of free flow
#   moderate  LOS C and D  above 40 %, up to 67 %
#   high      LOS E and F  40 % or less
LOW_ABOVE_SPEED_RATIO = 0.67
MODERATE_ABOVE_SPEED_RATIO = 0.40


# ============================================================
# CITY CONGESTION BY HOUR (TomTom Traffic Index)
# ============================================================

# Average time for a 10 km drive in Riyadh (city area), 2025, by day
# of the week and hour, from the public TomTom Traffic Index page
# (tomtom.com/traffic-index/city/riyadh, read 10 Nov 2026). TomTom
# measures it from drivers' trips over the whole road network. Values
# in seconds at 00:00, 02:00, ... 22:00.
TOMTOM_HOURS = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22)


def _s(text: str) -> tuple[int, ...]:
    """Turn "12:40 13:10 ..." (minutes:seconds) into seconds."""

    return tuple(
        int(m) * 60 + int(sec)
        for m, sec in (value.split(":") for value in text.split())
    )


# Monday = 0 ... Sunday = 6, as date.weekday()
TOMTOM_TRAVEL_TIME_10KM_S = {
    0: _s("12:40 11:40 10:20 14:30 17:50 17:40 "
          "17:10 20:30 24:10 21:50 17:20 15:30"),
    1: _s("13:10 11:50 10:20 14:20 17:40 17:30 "
          "17:10 20:20 23:20 21:40 17:40 15:40"),
    2: _s("13:10 12:00 10:20 14:20 17:10 17:00 "
          "17:10 20:10 23:20 21:50 17:50 16:00"),
    3: _s("13:10 11:50 10:20 13:50 16:00 16:40 "
          "17:20 20:40 23:40 21:10 18:50 18:20"),
    4: _s("16:00 12:50 11:00 10:20 10:50 11:00 "
          "12:00 12:40 14:10 15:20 17:10 17:00"),
    5: _s("15:00 12:10 10:50 11:20 11:30 12:50 "
          "13:20 14:20 16:50 17:10 17:00 15:30"),
    6: _s("12:40 11:40 10:20 14:20 17:40 17:10 "
          "16:50 20:00 23:20 21:30 16:30 15:00"),
}

# Free flow: the quickest time in the table (early morning), so the
# extra time at any hour is the delay caused by traffic
TOMTOM_FREE_FLOW_10KM_S = min(
    min(values) for values in TOMTOM_TRAVEL_TIME_10KM_S.values()
)


# ============================================================
# SYNTHETIC TRAFFIC
# ============================================================

# How the delay differs between roads, how much it varies and how much
# of that carries into the next 15 minutes are not written here: they
# are measured from the private RCRC profiles each time the generator
# runs (synthetic.py, SampleMeasures), so no RCRC-derived value is
# stored in the repository.

# Morning trips go from homes to activities, evening trips back; the
# road demand of the two directions is blended between these hours
# (project assumption)
MORNING_DEMAND_UNTIL_HOUR = 11
EVENING_DEMAND_FROM_HOUR = 13

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

    if volume_to_capacity > MODERATE_UP_TO_VC:
        return CongestionLevel.HIGH

    if volume_to_capacity > LOW_UP_TO_VC:
        return CongestionLevel.MODERATE

    return CongestionLevel.LOW


def speed_level(speed_ratio: float) -> CongestionLevel:
    """Return the map level of a speed as a share of free flow."""

    if speed_ratio < 0:
        raise ValueError("speed ratio must not be negative")

    if speed_ratio > LOW_ABOVE_SPEED_RATIO:
        return CongestionLevel.LOW

    if speed_ratio > MODERATE_ABOVE_SPEED_RATIO:
        return CongestionLevel.MODERATE

    return CongestionLevel.HIGH


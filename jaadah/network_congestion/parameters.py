"""
Constants for the network map, and the capacity and level functions.

Every value from the Highway Capacity Manual (HCM) 7th edition or
chosen for Jaadah is defined here once. Where each value comes from is
explained in Macro_Map_Implementation (sections 4.1, 4.2 and 4.4).
"""

from datetime import date, datetime, timedelta, timezone

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


# Level by speed, used for the map colours.
#
# HCM criteria (HCM 7th edition, 2022, Chapter 18, Urban Street
# Segments, LOS criteria for the motorized vehicle mode; exhibit and
# page to be added from the manual): LOS by average travel speed, given
# in mi/h for each base free-flow speed from 25 to 55 mi/h. Those speeds
# are about these shares of the base free-flow speed: A above 80 %
# (85 % in HCM 2010; lowered in the 6th edition), B 67-80, C 50-67,
# D 40-50, E 30-40, F 30 or less; also F, at any speed, when the
# through movement at the downstream boundary intersection has v/c
# above 1.0. Urban street facilities (Chapter 16) use the same speed
# thresholds over a whole facility; the map rates segments.
#
# The map's three groups, at the HCM B/C and D/E boundaries:
#   low       LOS A and B  speed above 67 % of free flow
#   moderate  LOS C and D  above 40 %, up to 67 %
#   high      LOS E and F  40 % or less
#
# Project simplifications (not HCM):
#   - speed only: the v/c above 1.0 rule for LOS F is not applied;
#   - free-flow speed is the OSM speed limit, not the HCM base
#     free-flow speed estimate;
#   - motorway and trunk segments use these urban street speed
#     criteria, not the HCM freeway method (Chapter 12, by density).
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

# Congestion level in Riyadh (city area), 2025, by day of the week and
# hour, in percent: how much longer trips took than in free-flow
# conditions, as TomTom measures it from drivers' trips. Same page and
# grid as the travel times above (Congestion level tab, read 18 Nov
# 2026). The network map is calibrated against these values.
TOMTOM_CONGESTION_LEVEL_PERCENT = {
    0: (14, 7, 0, 27, 50, 49, 44, 67, 89, 77, 47, 34),
    1: (18, 8, 0, 26, 49, 48, 44, 65, 84, 76, 49, 36),
    2: (19, 10, 0, 26, 45, 44, 43, 64, 84, 77, 51, 39),
    3: (19, 8, 0, 23, 37, 41, 45, 68, 86, 73, 58, 56),
    4: (40, 17, 3, 0, 0, 0, 4, 13, 25, 33, 47, 46),
    5: (33, 13, 3, 5, 5, 14, 17, 25, 42, 46, 45, 34),
    6: (15, 8, 0, 27, 49, 45, 42, 63, 83, 74, 41, 30),
}

# Free flow: the quickest time in the table (early morning), so the
# extra time at any hour is the delay caused by traffic
TOMTOM_FREE_FLOW_10KM_S = min(
    min(values) for values in TOMTOM_TRAVEL_TIME_10KM_S.values()
)


# ============================================================
# ROAD CONGESTION FROM THE STUDY INTERSECTION (observed.py)
# ============================================================

# How much busier busy roads are than quiet ones (observed.py). A
# stated assumption: measured at the intersection's 4 approaches it
# came out much larger, but from 4 approaches ranked close together, so
# it was not used. With the city following TomTom, 0.5 made nearly
# every road the same level (no high congestion even at the weekday
# evening peak) and 1.5 or more only made more roads low; 1.0 gave high
# congestion on the main roads at the evening peak. Checked by face
# validity (Macro_Map_Implementation).
NETWORK_SPREAD = 1.0

# The weeks that give the study intersection's usual v/c for each day
# of the week and 15 minutes: the first 5 whole weeks of the RCRC
# replay data, Monday 13 July to Sunday 16 August 2026. Fixed, so the
# usual values and the stored speeds do not change each time the server
# starts.
CALIBRATION_START = datetime(2026, 7, 13, tzinfo=timezone(timedelta(hours=3)))
CALIBRATION_WEEKS = 5

# How far one intersection can move the city's congestion away from
# TomTom's usual value (project assumption), so a quiet or busy day at
# the intersection shows on the map without turning the whole city green
# or red. One factor for the whole day (averaged over the day so far,
# observed.day_factors), so TomTom's pattern within the day, its evening
# above its morning, is kept. The factor still settles during the day,
# so the limits are narrow enough that even the extremes (morning at the
# top, evening at the bottom) can't reverse the peaks: 0.8 / 1.25 = 0.64
# is above TomTom's largest morning-to-evening ratio of extra travel time
# on any day (Sunday, about 0.60 against the map's free-flow time).
DAY_FACTOR_LIMITS = (0.8, 1.25)

# The timeline's bar for each 15 minutes shows the speed that the
# slowest share of the road length is at or below (length-weighted), so
# a bar turns high when at least this share of the roads is in the high
# level, as a driver crossing the city would meet it. A city average
# would never reach the high level, even at the weekday evening peak
# (project choice, for the timeline only; the segments are unchanged).
TIMELINE_SLOWEST_SHARE = 0.20

# Days of counts before a window used to estimate missing detectors,
# as the baseline runner for RCRC (simulation/scripts/run_baseline.py)
IMPUTATION_HISTORY_DAYS = 35


# ============================================================
# TRIP MODEL: ZONES AND DESTINATIONS (zones.py)
# ============================================================

# Zones are squares of this size in degrees (about 2.2 km north to
# south and 2.0 km east to west in Riyadh)
ZONE_DEGREES = 0.02

# Trip purposes (Macro Map Synthetic Data Methodology, Table 2)
PURPOSES = (
    "private_work",
    "government_work",
    "school",
    "university",
    "shopping_leisure",
    "health",
    "other",
)

# Attraction is counted in one unit for every kind of place: vehicle
# trips arriving on a weekday. Each kind's own size measure (floor
# area, leasable area, students, beds, passengers, visits) is turned
# into trips with the rate for that land use, so different measures
# are never added directly. Rates: ITE Trip Generation Manual, 11th
# edition, which the Saudi traffic impact study guide prescribes
# (MOMAH, Traffic Impact Study Guide for Urban Projects, 2025); taken
# from public tables that reproduce the manual (Palm Beach County,
# 2022; City of Portland). ITE rates come from mostly suburban US
# sites; since the network total is later scaled to TomTom, only the
# rates relative to each other matter.
TRIP_RATES = {
    # code: (daily vehicle trip ends per unit, unit, source)
    "office_710": (10.84, "1000 sq ft", "ITE 710 General Office, 11th ed."),
    "government_730": (22.59, "1000 sq ft", "ITE 730 Government Office, 11th ed."),
    "strip_retail_822": (54.45, "1000 sq ft", "ITE 822 Strip Retail Plaza, 11th ed."),
    "school_520_525": (2.0, "student", "ITE 520 and 525 (2.27 and 1.94), 11th ed., rounded"),
    "university_540_550": (1.36, "student", "ITE 540 and 550 average, City of Portland on ITE 11th ed."),
    "hospital_610": (10.94, "bed", "ITE 610 Hospital per bed, 8th ed. (11th ed. per-bed rate not public)"),
}

# Shopping centres: the trip rate falls as the centre gets larger, so
# ITE 820 uses a curve: ln(T) = 0.65 ln(X) + 5.83, X in 1000 sq ft of
# gross leasable area, T daily vehicle trip ends (ITE 820 fitted curve,
# as published in Lake County FL traffic worksheets).
SHOPPING_820_CURVE = (0.65, 5.83)

# Share of daily trip ends that arrive (the rest leave): ITE trip ends
# count both directions
ARRIVING_SHARE = 0.5

# Car share of trips in Riyadh: 87.2% (KAPSARC dp00524, Table 2,
# modelled baseline). Used only where a measure counts people, not
# vehicles (visitors, airport employees).
CAR_SHARE = 0.872

# People per car for leisure visitors, who come in family groups
# (project assumption, tested 1.5 to 3.5)
VISITOR_PEOPLE_PER_CAR = 2.5

# King Khalid International Airport: vehicles arriving at the airport,
# built from passengers, employees and other vehicles so each movement
# is counted once. Counted per passenger, not per passenger movement:
# the daily figure (112,000, GACA 2025) already counts arrivals and
# departures, so half the origin-destination passengers depart and half
# arrive. A departing passenger's car arrives at the airport; an
# arriving passenger's car also arrives (to pick up), except when the
# passenger parked there on the way out, since that car already arrived
# then. Project assumptions with test ranges:
AIRPORT = {
    # share of passengers changing planes, who never use the roads
    # (not published for KKIA; tested 0 to 0.25)
    "transfer_share": 0.10,
    # share of origin-destination passengers reaching the airport by road
    # (car, taxi, ride-hailing, bus); the rest use the metro (Line 4,
    # opened 2025; tested 0.85 to 0.98)
    "road_share": 0.95,
    # passengers per vehicle (one travel party; tested 1.3 to 2.5)
    "passengers_per_vehicle": 1.8,
    # share of departing road passengers who park at the airport
    # (tested 0.05 to 0.30)
    "park_share": 0.15,
    # share of the airport's workers on site on a weekday, after shifts
    # and days off (tested 0.5 to 0.8)
    "employees_on_site": 0.65,
    # workers per car (commuters; tested 1.1 to 1.4)
    "employees_per_vehicle": 1.2,
    # freight, delivery, service, crew and other vehicles, as a share of
    # passenger and employee vehicles (tested 0.05 to 0.20)
    "other_vehicle_share": 0.10,
}

# Attraction of seasonal places (Riyadh Season, October to March)
# outside their season, as a share of the in-season value (project
# assumption)
OFF_SEASON_SHARE = 0.1

# Every OpenStreetMap activity place that is not a major centre: OSM
# gives no size for these, so each kind gets a relative size and a
# land-use category, turned into trips with its rate and split between
# purposes. Kinds not listed (for example military land) attract no
# trips. Schools are not taken from OSM, which maps only a few hundred
# of Riyadh's schools: school trips follow population instead
# (SCHOOL_STUDENTS_PER_PERSON).
PLACE_TYPICAL = {
    # kind: (rate, relative size, size unit, category, purpose shares)
    "office": ("office_710", 5000, "m2", "office_floor_area", {"private_work": 1.0}),
    "government_office": ("government_730", 10000, "m2", None, {"government_work": 1.0}),
    "diplomatic": ("government_730", 2000, "m2", None, {"government_work": 1.0}),
    "commercial_area": ("strip_retail_822", 4000, "m2", "retail_area",
                        {"shopping_leisure": 0.7, "private_work": 0.3}),
    "retail_area": ("strip_retail_822", 4000, "m2", "retail_area",
                    {"shopping_leisure": 0.85, "private_work": 0.15}),
    "mall": ("shopping_820", 30000, "m2", "retail_area",
             {"shopping_leisure": 0.9, "private_work": 0.1}),
    "marketplace": ("strip_retail_822", 2000, "m2", "retail_area", {"shopping_leisure": 1.0}),
    "college": ("university_540_550", 2000, "students", "university_students",
                {"university": 0.85, "government_work": 0.15}),
    "university": ("university_540_550", 5000, "students", "university_students",
                   {"university": 0.85, "government_work": 0.15}),
    "hospital": ("hospital_610", 200, "beds", "hospital_beds",
                 {"health": 0.6, "government_work": 0.4}),
    "clinic": ("hospital_610", 20, "beds", None, {"health": 1.0}),
}

# How much of each land use Riyadh has in total (control totals). The
# major centres keep their own published sizes; the other OSM places of
# the category share the rest in proportion to their relative sizes,
# so OSM decides where a land use is and the published total decides
# how much there is. Categories without a total (government offices,
# embassies, clinics) keep their relative sizes as typical sizes
# (project assumption).
CONTROL_TOTALS = {
    # category: (total, unit, source)
    "office_floor_area": (8_100_000, "m2",
                          "JLL Saudi office market, Q2 2025 (Knight Frank: 5.5 million, narrower definition)"),
    "retail_area": (4_170_000, "m2",
                    "Knight Frank, The Saudi Report 2025, quality retail GLA end-H1 2025"),
    "university_students": (250_637, "students",
                            "Riyadh city, public and private, 1438 AH / 2017 (Saudipedia citing official statistics); "
                            "the only city-level total found, tested at +10 and +20 percent"),
    "hospital_beds": (20_457, "beds",
                      "Ministry of Health Statistical Yearbook 2022, Riyadh region, all sectors"),
}

# School students per resident, for school trips by zone (project
# assumption, tested 0.12 to 0.25): school trips stay close to home, so
# they are attracted where people live
SCHOOL_STUDENTS_PER_PERSON = 0.18

# Employment check (not a control total): official employment converted
# to commuting cars arriving in Riyadh city, to compare with the work
# trips the in-scope places attract. Neighbourhood jobs are outside the
# project scope, so private work is not scaled up to this figure (that
# would load jobs located elsewhere onto the major centres).
#   Region to city: Census 2022 population ratios by nationality,
#   Saudis 3.35 / 4.44 million = 0.75, non-Saudis 3.66 / 4.15 = 0.88,
#   all 7.01 / 8.59 = 0.82.
#   Weekday attendance 0.9; government, health and education workers
#   0.727 cars each (87.2% by car at 1.2 per car); assumptions.
EMPLOYMENT_CHECK = {
    # private: GASTAT register Q4 2023 (via GLMM), 1,724,737 Saudi and
    # 3,759,074 non-Saudi employed in the region, scaled to the city
    # (4.61 million), less government; 1.30 to 2.83 million arriving cars
    # depending on company buses and car sharing
    "private_work": (1_300_000, 2_830_000),
    # government: civil service 433,288 (DataSaudi Q2 2026) x 0.75, plus
    # 70% public share of health workers 157,809 (MoH 2023) x 0.82 and of
    # teachers 121,516 (Ministry of Education 2026): about 500,600 workers,
    # 327,400 arriving cars (243,200 to 396,600 over the ranges)
    "government_work": (243_200, 396_600),
}

# Riyadh city workers, without domestic workers and the military: GASTAT
# register for the region (Saudis 1,830,000, Q1 2025; non-Saudis without
# domestic workers 4,220,000, 2024) x Census 2022 city shares (0.75 and
# 0.88)
CITY_WORKERS = {"saudi": 1_372_500, "non_saudi": 3_713_600}

# From workers to vehicles arriving on a weekday (project assumptions,
# Macro Map employment research, November 2026), in three cases for
# sensitivity tests. Non-Saudi workers are split into skilled (managers,
# professionals, technicians, clerks, sales) and other (elementary,
# craft, operators: 52% of all workers, GASTAT register Q3 2025). Other
# workers who don't live on site go by shared car or by company bus;
# the rest walk, take the metro or ride-hailing.
EMPLOYMENT_CASES = {
    "low": {
        "attendance": 0.85, "saudi_by_car": 0.85, "saudi_per_car": 1.25,
        "skilled_share": 0.25, "skilled_by_car": 0.65, "skilled_per_car": 1.5,
        "on_site": 0.20, "other_by_car": 0.15, "other_per_car": 2.5,
        "other_by_bus": 0.60, "per_bus": 30,
    },
    "central": {
        "attendance": 0.90, "saudi_by_car": 0.92, "saudi_per_car": 1.15,
        "skilled_share": 0.30, "skilled_by_car": 0.80, "skilled_per_car": 1.3,
        "on_site": 0.10, "other_by_car": 0.25, "other_per_car": 2.0,
        "other_by_bus": 0.50, "per_bus": 25,
    },
    "high": {
        "attendance": 0.92, "saudi_by_car": 0.96, "saudi_per_car": 1.08,
        "skilled_share": 0.35, "skilled_by_car": 0.90, "skilled_per_car": 1.15,
        "on_site": 0.05, "other_by_car": 0.35, "other_per_car": 1.6,
        "other_by_bus": 0.40, "per_bus": 20,
    },
}
EMPLOYMENT_CASE = "central"

# Workers of industrial centres: 15% Saudi, and 15% of the non-Saudis
# skilled (project assumption; industry is mostly non-Saudi)
INDUSTRY_WORKER_MIX = {"saudi": 0.15, "skilled_share": 0.15}

# Company buses: a separate heavy-vehicle layer, never added to the car
# trips. One bus counts as two cars on the road (passenger car
# equivalent; HCM uses about 2 for buses on level roads). Where the
# labour housing is isn't published, so buses leave from where people
# live; they go to the in-scope work places, the industrial centres
# taking their own buses first. Distance decay per km: flatter than for
# commuting cars, since labour housing is often far from the sites
# (assumption).
COMPANY_BUS_PCE = 2.0
COMPANY_BUS_DECAY = 0.15

# Sensitivity test only, never part of the map: work trips to jobs
# outside the major centres (street retail and food, workshops,
# construction, small offices), the gap between official employment and
# the in-scope work trips. Placed half by population and half by
# commercial activity, split by sector (GASTAT structural business
# statistics 2025, rounded) into the timings below.
DISTRIBUTED_WORK_MIX = {"retail": 0.45, "site": 0.40, "office": 0.15}

# Sensitivity test only: workers living in Riyadh region outside the city
# who drive in (no official commuting data: 10 to 20 percent of about
# 0.9 million such workers), entering on the main roads at the edge of
# the city box. Corridor shares are assumptions.
EXTERNAL_COMMUTERS = {"low": 50_000, "central": 85_000, "high": 120_000}
EXTERNAL_GATEWAYS = {
    # corridor: (lon, lat on the city box edge, share)
    "Al-Kharj road": (46.93, 24.53, 0.40),
    "south (Al-Hair, Dirab)": (46.75, 24.52, 0.15),
    "Makkah road": (46.52, 24.62, 0.15),
    "Qassim road": (46.60, 24.99, 0.15),
    "Dammam road": (46.93, 24.80, 0.15),
}

# Merging OSM features that are one place, before computing attraction
# (Macro Map attraction research, section 7). Features of the same kind
# merge when they are within the threshold and their names are
# compatible: same name, one name contains the other, the same complex
# name before " - ", or one of them unnamed (within the shorter unnamed
# threshold). Two features with different, unrelated names never merge.
# Being close is not evidence of one complex: unnamed commercial and
# retail outlines (independent shops along a street) never merge, and
# unnamed mall buildings, each tagged shop=mall, merge only in a tight
# cluster.
MERGE_THRESHOLDS_M = {
    # kind: (names matching, one unnamed)
    "mall": (150, 60),
    "hospital": (200, 100),
    "college": (300, 100),
    "university": (300, 100),
    "office": (30, 30),
    "government_office": (50, 50),
    "diplomatic": (30, 30),
    "commercial_area": (50, 0),
    "retail_area": (50, 0),
    "clinic": (30, 30),
    "marketplace": (100, 100),
}

# A point and an outline of the same kind this close are one place even
# when their names differ (often one Arabic, one English); not for
# offices, where one building holds several tenants
POINT_IN_OUTLINE_M = 25
POINT_IN_OUTLINE_EXCEPT = {"office"}

# The major activity centres, with their published size measures,
# sources, dates and confidence: data/processed/network/
# activity_centres.csv (Macro Map attraction research, November 2026).
# A centre replaces its own OSM place (osm_element), so it is not
# counted twice, and absorbs the OSM places of its campus (campus_kinds
# within campus_radius_m), whose size its published figure already
# includes. The government centre and the Diplomatic Quarter have
# no published size; their ministries and embassies are counted
# through their OSM places above.
ACTIVITY_CENTRES_FILE = "activity_centres.csv"


# ============================================================
# TRIP MODEL: GENERATION AND DISTRIBUTION (trips.py)
# ============================================================

# Trip length between zones: straight-line distance times a circuity
# factor, an approximation of the distance actually driven, not a road
# distance. The network holds only
# motorway to secondary roads, so a short trip measured on it takes long
# detours that local streets avoid (road / straight-line distance is
# 2.4 for zone pairs under 5 km apart, 1.6 at 10 to 20 km, 1.25 over
# 40 km). Typical urban road circuity is 1.2 to 1.4 (Ballou, Rahardja
# and Sakai 2002, Transportation Research Part A 36(9); project value
# 1.3, tested 1.2 to 1.4).
CIRCUITY = 1.3

# Mean trip length the gravity model is fitted to, by purpose, in km.
# A purpose without a target, or whose target can't be reached with the
# in-scope destinations, uses the private-work decay instead
# (SHARED_DECAY_PURPOSE), and its resulting mean length is reported.
TRIP_LENGTH_KM = {
    # mean home-to-work network distance in Riyadh, 11.6 km (Chodrow et
    # al. 2016, PLOS ONE, estimated from 2.2 million phone users)
    "private_work": 11.6,
    "government_work": 11.6,
    # no Riyadh evidence: school trips stay near home (project
    # assumption, configurable: trips.py --school-km; to be tested 3 to
    # 8 km)
    "school": 5.0,
    # average car trip in Riyadh, 12.6 km (KAPSARC dp00524, Table 2,
    # modelled baseline), used where no purpose-specific value exists
    # (project assumption, tested 8 to 16 km)
    "shopping_leisure": 12.6,
    "health": 12.6,
    # no target: three large campuses (King Saud, Imam, Princess Nourah:
    # 72% of university trips) draw students from the whole city, so
    # trips are long whatever the decay
    "university": None,
}
# Government work: its 11.6 km target can't be reached. Government
# places are concentrated (Murabba, the Diplomatic Quarter, the medical
# cities: 139 of 550 zones), so even the steepest decay searched leaves
# a mean of about 13 km; with the private-work decay it is 13.9 km.
SHARED_DECAY_PURPOSE = "private_work"

# Trips inside one zone (about 2 km across), in km (project assumption)
INTRA_ZONE_KM = 1.0

# Furness balancing of the doubly constrained gravity model
FURNESS_ITERATIONS = 200
FURNESS_TOLERANCE = 1e-4


# ============================================================
# TRIP MODEL: TIME OF DAY, DIRECTION AND CALENDAR (timing.py)
# ============================================================

# When trips leave, by purpose: one or more bell curves (share, mean
# hour, spread in hours) for trips from home (outbound) and back home
# (return). Sources: government work starts at 07:30 and lasts 7 hours
# (civil service regulation, Ministry of Human Resources); schools start
# at 06:15 to 07:00 (Riyadh school timetables, 2025); flexible start in
# six business hubs from 2 June 2026 (RCRC). Everything else is a
# project assumption (Macro Map Methodology, Table 6).
#
# DEPARTURES_STEP3 are the times first approved in step 3, kept for
# comparison; DEPARTURES are the corrected times used from step 4 on
# (Macro Map Step 4 review, November 2026). The trips themselves (the OD
# matrices) are the same in both: only their times differ.
DEPARTURES = {
    # drop-offs staggered by school level, 06:00 to 07:30: secondary,
    # intermediate, primary, kindergarten (shares roughly by years of
    # schooling, assumption); pick-ups staggered the same way. The empty
    # trips back after a drop-off and the pick-up runs follow from these
    # (SCHOOL_TRAVEL, timing.school_legs)
    "school": {"outbound": [(0.22, 6.0, 0.2), (0.22, 6.25, 0.2), (0.45, 6.6, 0.25), (0.11, 7.15, 0.25)],
               "return": [(0.11, 11.5, 0.3), (0.45, 12.25, 0.3), (0.22, 12.75, 0.3), (0.22, 13.25, 0.3)]},
    # 60% on fixed hours (07:30 to 14:30, official), leaving 14:30 to
    # 14:50; 40% with a later, flexible start leaving about 7 hours after
    # it, 15:00 to 15:30 (ASSUMPTION: flexible share and times unverified)
    "government_work": {"outbound": [(0.6, 7.0, 0.4), (0.4, 7.75, 0.6)],
                        "return": [(0.6, 14.65, 0.2), (0.4, 15.25, 0.4)]},
    # ASSUMPTION, no Riyadh finishing-time data found: private-sector
    # employees leave later and at more varied times than government
    # staff, from about 16:00 to 19:30, each group starting about 9 hours
    # earlier (an 8-hour day under the Labour Law plus a break)
    "private_work": {"outbound": [(0.25, 7.25, 0.4), (0.35, 8.25, 0.5), (0.25, 9.25, 0.5), (0.15, 10.25, 0.6)],
                     "return": [(0.25, 16.25, 0.4), (0.35, 17.25, 0.5), (0.25, 18.25, 0.5), (0.15, 19.25, 0.6)]},
    # flexible-hours hubs: later and wider (ASSUMPTION)
    "private_work_flexible": {"outbound": [(0.5, 8.5, 0.8), (0.5, 9.5, 0.8)],
                              "return": [(0.5, 17.5, 0.8), (0.5, 18.5, 0.8)]},
    "university": {"outbound": [(1.0, 8.0, 0.8)], "return": [(1.0, 14.5, 1.5)]},
    # evening-weighted: dinner 18:00 to 22:00 (delivery-order and card
    # spending peaks), some after Asr, a little before noon (assumption)
    "shopping_leisure": {"outbound": [(0.15, 11.5, 1.5), (0.25, 17.0, 1.2), (0.60, 20.0, 1.5)],
                         "return": [(0.15, 13.5, 1.5), (0.25, 19.0, 1.2), (0.60, 22.5, 1.5)]},
    # evening clinics (assumption)
    "health": {"outbound": [(0.7, 10.0, 2.0), (0.3, 18.5, 1.5)], "return": [(0.7, 11.5, 2.0), (0.3, 20.0, 1.5)]},
    "other": {"outbound": "uniform", "return": "uniform"},
    "private_work_industry": {"outbound": [(0.75, 6.5, 0.4), (0.125, 14.5, 0.4), (0.125, 22.5, 0.4)],
                              "return": [(0.75, 15.5, 0.5), (0.125, 23.0, 0.4), (0.125, 7.0, 0.4)]},
    "company_bus": {"outbound": [(1.0, 5.9, 0.4)], "return": [(0.6, 15.75, 0.5), (0.4, 17.0, 0.6)]},
}

# School trips leg by leg, instead of one car trip per student each way:
# a car takes 1.4 children on average and does the drop-off, an empty
# trip back home for most cars, a pick-up run and the ride home.
SCHOOL_TRAVEL = {
    # Rafed (Ministry of Education transport): about 736,000 to 779,000
    # students nationally in 2025, of about 6 million
    "bus_share": 0.12,
    # no Riyadh evidence of walking to school; private cars are by far
    # the most common way (Children's mobility in Riyadh, PMC 6429590),
    # so walking is kept minimal (assumption)
    "walk_share": 0.02,
    # siblings sharing a car, limited by separate boys' and girls'
    # schools and levels (assumption; households of 5, KAPSARC survey)
    "children_per_car": 1.4,
    # drop-off cars that go back home empty (household drivers, parents
    # not going to work); the rest go on to work, counted as work trips
    # (assumption). The same share drive out again for the pick-up.
    "empty_return": 0.6,
    "children_per_bus": 40,
    # hours between the drop-off and the empty trip back, and before the
    # ride home for the pick-up run
    "return_after_h": 0.25,
    "pickup_before_h": 0.33,
    "bus_before_h": 0.25,
}

DEPARTURES_STEP3 = {
    "school": {"outbound": [(1.0, 6.5, 0.25)], "return": [(1.0, 12.75, 0.5)]},
    "government_work": {"outbound": [(1.0, 7.0, 0.33)], "return": [(1.0, 14.75, 0.4)]},
    "private_work": {"outbound": [(1.0, 8.0, 0.6)], "return": [(1.0, 17.5, 0.8)]},
    # employers in the flexible-hours hubs: a wider morning window
    "private_work_flexible": {"outbound": [(1.0, 8.75, 1.1)], "return": [(1.0, 17.75, 1.1)]},
    "university": {"outbound": [(1.0, 8.0, 0.8)], "return": [(1.0, 14.5, 1.5)]},
    # some daytime shopping, most in the evening
    "shopping_leisure": {"outbound": [(0.25, 11.0, 1.5), (0.75, 18.5, 2.0)],
                         "return": [(0.25, 13.0, 1.5), (0.75, 21.5, 1.8)]},
    "health": {"outbound": [(1.0, 10.0, 3.0)], "return": [(1.0, 12.0, 3.0)]},
    # the airport works around the clock
    "other": {"outbound": "uniform", "return": "uniform"},
    # industrial centres: three quarters on a day shift (06:30 to 15:30),
    # the rest on afternoon and night shifts
    "private_work_industry": {"outbound": [(0.75, 6.5, 0.4), (0.125, 14.5, 0.4), (0.125, 22.5, 0.4)],
                              "return": [(0.75, 15.5, 0.5), (0.125, 23.0, 0.4), (0.125, 7.0, 0.4)]},
    # company buses reach the sites before the shift starts
    "company_bus": {"outbound": [(1.0, 5.9, 0.4)], "return": [(0.6, 15.75, 0.5), (0.4, 17.0, 0.6)]},
}

# Timings of the sensitivity tests (distributed work and external
# commuters; never part of the map)
TEST_DEPARTURES = {
    "retail": {"outbound": [(0.5, 9.5, 0.5), (0.5, 16.5, 0.4)],
               "return": [(0.5, 13.0, 0.4), (0.5, 22.5, 0.7)]},
    "site": {"outbound": [(1.0, 6.25, 0.4)], "return": [(1.0, 16.0, 0.6)]},
    "office": {"outbound": [(1.0, 8.0, 0.6)], "return": [(0.6, 17.0, 0.6), (0.4, 18.0, 0.8)]},
    "external": {"outbound": [(1.0, 6.4, 0.5)], "return": [(0.5, 15.0, 0.5), (0.5, 17.25, 0.7)]},
}

# Business hubs with flexible working hours (RCRC, 2 June 2026): private
# work trips to these centres follow private_work_flexible. Only the
# hubs among the major centres are listed (Digital City, Roshn Front
# and Listen Valley aren't in the centre list).
FLEXIBLE_HUBS = ("KAFD", "Granada")

# Share of a weekday's trips made on each kind of day (project
# assumptions; Riyadh's weekend is Friday and Saturday)
DAY_FACTORS = {
    # purpose: (Sunday to Wednesday, Thursday, Friday, Saturday)
    "school": (1.0, 1.0, 0.0, 0.0),
    "government_work": (1.0, 1.0, 0.0, 0.0),
    "private_work": (1.0, 1.0, 0.15, 0.4),
    "private_work_flexible": (1.0, 1.0, 0.05, 0.1),
    "university": (1.0, 1.0, 0.0, 0.0),
    "shopping_leisure": (1.0, 1.2, 1.3, 1.2),
    "health": (1.0, 1.0, 0.3, 0.6),
    "other": (1.0, 1.05, 1.05, 1.0),
    "private_work_industry": (1.0, 1.0, 0.2, 0.8),
    "company_bus": (1.0, 1.0, 0.2, 0.8),
}

# School and university terms. 2026-27: students return Sunday 23 August
# 2026 (Ministry of Education calendar for 1448 AH, as reported; Riyadh's
# calendar lists 23 August as preparation and the first semester from
# 30 August). University terms are assumed to follow the school calendar.
# The 2025-26 year ran 24 August 2025 to the summer break (end date
# assumed 25 June 2026).
TERMS = (
    (date(2025, 8, 24), date(2026, 6, 25)),
    (date(2026, 8, 23), date(2027, 6, 24)),
)

# Public holidays with no school or government work, and half the usual
# private work (project assumption): Saudi National Day, 23 September
PUBLIC_HOLIDAYS = (date(2025, 9, 23), date(2026, 9, 23))
HOLIDAY_PRIVATE_WORK = 0.5

# Riyadh Season, when the seasonal places (Boulevard City) attract
# trips: 2025-26 from 10 October 2025 (about five months); 2026 from 21
# October 2026 for about ten weeks (GEA chairman, via Gulf News and
# Saudi Gazette). End dates are approximate.
RIYADH_SEASONS = (
    (date(2025, 10, 10), date(2026, 3, 15)),
    (date(2026, 10, 21), date(2026, 12, 31)),
)


# ============================================================
# TRIP MODEL: ASSIGNMENT TO THE ROADS (assignment.py)
# ============================================================

# Each zone joins the network at up to this many junctions on primary
# or secondary roads within this distance of its centre (the nearest
# junction when none is that close); its trips are split equally between
# them (assumption, standard practice in zone models)
ZONE_CONNECTORS = 4
CONNECTOR_RADIUS_KM = 2.0

# Zone pairs closer than this (straight line) travel on local streets,
# which the network doesn't hold: for such trips the main-road route is
# 2.4 times the straight distance (assumption)
LOCAL_STREETS_KM = 3.0

# Minutes to and from the network, both ends together, added to the
# free-flow network time when a trip is spread over the hours it spends
# on the road (assumption)
ACCESS_MINUTES = 4.0

# Capacity per lane, vehicles an hour (assumption, typical urban values;
# primary and secondary roads have signals)
CAPACITY_PER_LANE = {"motorway": 1900, "trunk": 1600, "primary": 900, "secondary": 700}

# Travel time against traffic: t = t0 (1 + a (v/c)^b), the BPR curve
# with its standard values
BPR_ALPHA = 0.15
BPR_BETA = 4.0

# Each hour's trips are loaded in rounds of these shares; after each
# round travel times are updated and later rounds take the new fastest
# routes (incremental assignment)
ASSIGNMENT_ROUNDS = (0.4, 0.3, 0.2, 0.1)


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


"""
Calibration constants.

These are the acceptance criteria agreed on 19 Nov 2026 (see
docs/calibration.md). If they change, change the values here, and only
here.
"""

# GEH below this value counts as a match (FHWA 2004, Dowling et al.).
GEH_THRESHOLD = 5.0

# Share of eligible detector-hours that must match for the model to pass.
REQUIRED_PASS_SHARE = 0.85

# Detector output period: one value per 15-minute interval, like the source.
E1_PERIOD_S = 900

# Intervals summed into one hourly count.
INTERVALS_PER_HOUR = 4

# Test hours: the two busiest hours of each day type, at least 3 hours
# apart, taken from the calibration weeks (all 12 detectors summed).
# Start times in Riyadh time; each test lasts one hour. Friday and
# Saturday 00:00-01:00 is the previous night's traffic continuing past
# midnight.
TEST_HOUR_STARTS = {
    "workday": ("07:15", "13:45"),
    "friday": ("21:00", "00:00"),
    "saturday": ("17:00", "00:00"),
}

# SUMO vehicle-type attributes the calibration may change. Anything else
# (length, vClass, the type ID) describes the vehicle, not the driver,
# and stays as the demand writer sets it.
TUNABLE_VEHICLE_ATTRIBUTES = (
    "tau",
    "sigma",
    "minGap",
    "accel",
    "decel",
    "speedFactor",
    "speedDev",
    "lcStrategic",
    "lcCooperative",
    "lcSpeedGain",
    "lcKeepRight",
)

# A result based on fewer eligible detector-hours than this is reported
# as indicative.
INDICATIVE_BELOW = 100

# Shared-lane sensitivity check: the left-turn movements of the shared
# lanes (LANE_W_2, LANE_E_2) whose share the demand transformation's
# share_adjustments shifts. The team's agreed runs shift them by -0.2 and
# +0.2 (docs/traffic_demand_transformation.md, Sensitivity Runs).
SHARED_LANE_LEFT_MOVEMENTS = ("MOV_W_N", "MOV_E_S")

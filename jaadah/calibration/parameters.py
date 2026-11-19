"""
Calibration constants.

These are the proposed acceptance criteria (19 Nov 2026), not yet
approved by the team and supervisor. If they change, change the values
here, and only here.
"""

# GEH below this value counts as a match (FHWA 2004, Dowling et al.).
GEH_THRESHOLD = 5.0

# Share of eligible detector-hours that must match for the model to pass.
REQUIRED_PASS_SHARE = 0.85

# Detector output period: one value per 15-minute interval, like the source.
E1_PERIOD_S = 900

# Intervals summed into one hourly count.
INTERVALS_PER_HOUR = 4

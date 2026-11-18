"""
When the trips happen: time of day, direction and calendar.

Step 3 of the Macro Map synthetic traffic. The OD matrices of step 2
(trips.py) count a weekday's trips from home to each activity. This
module says how they spread over the 96 quarter hours of a given date:

- direction: every outbound trip (home to activity) has a return trip
  (activity to home), the transposed matrix, later in the day;
- time of day: each purpose leaves at its own times (DEPARTURES): schools
  early, government work at 07:00, private work around 08:00, shopping
  mostly in the evening, the airport around the clock. Private work at
  the flexible-hours hubs (FLEXIBLE_HUBS) uses a wider morning window,
  and private work at the industrial centres follows their shifts
  (private_work_industry); company buses (in buses) reach the sites
  before the shift starts;
- kind of day: Sunday to Wednesday, Thursday, Friday and Saturday each
  have their own share of a weekday's trips (DAY_FACTORS);
- calendar: school and university trips only in term (TERMS), no school
  or government work on public holidays (PUBLIC_HOLIDAYS), and trips to
  seasonal places only during Riyadh Season (RIYADH_SEASONS).

A trip is placed in the quarter hour it leaves; the routes and the time
spent on them come in step 4. Only project assumptions and published
calendars are used, no RCRC data.
"""

import math
from datetime import date

import numpy as np

from jaadah.network_congestion.parameters import (
    DAY_FACTORS,
    DEPARTURES,
    FLEXIBLE_HUBS,
    HOLIDAY_PRIVATE_WORK,
    INTERVALS_PER_DAY,
    OFF_SEASON_SHARE,
    PUBLIC_HOLIDAYS,
    RIYADH_SEASONS,
    TERMS,
    TEST_DEPARTURES,
)
from jaadah.network_congestion.trips import BUS_PURPOSE, SEASONAL_PURPOSE

DIRECTIONS = ("outbound", "return")
SLOT_HOURS = 24 / INTERVALS_PER_DAY

# purposes whose trips follow another purpose's times
TIMES_OF = {SEASONAL_PURPOSE: "shopping_leisure"}


# ============================================================
# CALENDAR
# ============================================================

def day_type(day: date) -> int:
    """0 Sunday to Wednesday, 1 Thursday, 2 Friday, 3 Saturday."""

    return {6: 0, 0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3}[day.weekday()]


def within(day: date, periods: tuple) -> bool:
    return any(start <= day <= end for start, end in periods)


def in_term(day: date) -> bool:
    return within(day, TERMS)


def in_season(day: date) -> bool:
    return within(day, RIYADH_SEASONS)


def is_holiday(day: date) -> bool:
    return day in PUBLIC_HOLIDAYS


def day_factor(purpose: str, day: date) -> float:
    """Share of a weekday's trips of this purpose made on this date."""

    if purpose == SEASONAL_PURPOSE:
        factor = DAY_FACTORS["shopping_leisure"][day_type(day)]
        return factor * (1.0 if in_season(day) else OFF_SEASON_SHARE)

    factor = DAY_FACTORS[purpose][day_type(day)]

    if purpose in ("school", "university") and not in_term(day):
        return 0.0

    if is_holiday(day):
        if purpose in ("school", "university", "government_work"):
            return 0.0
        if purpose.startswith("private_work") or purpose == BUS_PURPOSE:
            return factor * HOLIDAY_PRIVATE_WORK

    return factor


# ============================================================
# TIME OF DAY
# ============================================================

def normal_cdf(x: np.ndarray, mean: float, spread: float) -> np.ndarray:
    return 0.5 * (1 + np.vectorize(math.erf)((x - mean) / (spread * math.sqrt(2))))


def departure_shares(curves) -> np.ndarray:
    """
    Share of a purpose's trips leaving in each quarter hour (adding up
    to 1): the bell curves' mass in each quarter hour, the part falling
    before midnight or after the next midnight wrapped around the day.
    """

    if curves == "uniform":
        return np.full(INTERVALS_PER_DAY, 1 / INTERVALS_PER_DAY)

    edges = np.arange(INTERVALS_PER_DAY + 1) * SLOT_HOURS
    shares = np.zeros(INTERVALS_PER_DAY)

    for weight, mean, spread in curves:
        for shift in (-24, 0, 24):
            mass = np.diff(normal_cdf(edges + shift, mean, spread))
            shares += weight * mass

    return shares / shares.sum()


def slot_shares(purpose: str, direction: str, day: date) -> np.ndarray:
    """
    Share of a weekday's trips of this purpose and direction made in each
    quarter hour of this date (adding up to the day factor).
    """

    curves = DEPARTURES[TIMES_OF.get(purpose, purpose)][direction]

    return day_factor(purpose, day) * departure_shares(curves)


def sensitivity_shares(test: str, direction: str) -> np.ndarray:
    """
    Departure shares of an employment sensitivity test (distributed work
    by sector, external commuters), on a working day.
    """

    return departure_shares(TEST_DEPARTURES[test][direction])


# ============================================================
# MATRICES BY TIMING
# ============================================================

def flexible_zones(zones: list[dict], centres: list) -> set[int]:
    """Indexes of the zones holding a flexible-hours hub."""

    from jaadah.network_congestion.zones import zone_key

    ids = {f"Z{zone_key(c.lon, c.lat)[0]}_{zone_key(c.lon, c.lat)[1]}"
           for c in centres if c.centre in FLEXIBLE_HUBS}

    return {i for i, z in enumerate(zones) if z["zone_id"] in ids}


def industry_zones(zones: list[dict], centres: list) -> set[int]:
    """Indexes of the zones holding an industrial centre."""

    from jaadah.network_congestion.zones import zone_key

    ids = {f"Z{zone_key(c.lon, c.lat)[0]}_{zone_key(c.lon, c.lat)[1]}"
           for c in centres if c.rate == "industry_workers"}

    return {i for i, z in enumerate(zones) if z["zone_id"] in ids}


def timed_matrices(
    od: dict[str, np.ndarray],
    flexible: set[int],
    industry: set[int] = frozenset(),
) -> dict[str, np.ndarray]:
    """
    The OD matrices by timing: private work to the flexible-hours hubs
    becomes private_work_flexible, private work to the industrial
    centres private_work_industry; every other purpose keeps its matrix.
    """

    result = dict(od)
    private = od["private_work"]
    rest = np.ones(private.shape[1], dtype=bool)

    for name, chosen in (("private_work_flexible", flexible), ("private_work_industry", industry)):
        columns = np.zeros(private.shape[1], dtype=bool)
        columns[list(chosen)] = True
        result[name] = private * columns[None, :]
        rest &= ~columns

    result["private_work"] = private * rest[None, :]

    return result


def departures_by_slot(totals: dict[str, float], day: date) -> np.ndarray:
    """
    Trips leaving in each quarter hour of a date, outbound and return,
    for the whole city: totals are each timing purpose's weekday trips.
    Cars only: company buses are counted apart (bus_departures_by_slot).
    """

    if BUS_PURPOSE in totals:
        raise ValueError("company buses are counted apart from cars: use bus_departures_by_slot")

    return sum(
        total * slot_shares(purpose, direction, day)
        for purpose, total in totals.items()
        for direction in DIRECTIONS
    )


def bus_departures_by_slot(buses: float, day: date) -> np.ndarray:
    """Company buses (in buses, not cars) leaving in each quarter hour of a date."""

    return sum(buses * slot_shares(BUS_PURPOSE, direction, day) for direction in DIRECTIONS)

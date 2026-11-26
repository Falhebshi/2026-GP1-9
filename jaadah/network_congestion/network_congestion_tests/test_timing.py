from datetime import date

import numpy as np
import pytest

from jaadah.network_congestion.parameters import (
    DAY_FACTORS,
    DEPARTURES,
    DEPARTURES_STEP3,
    HOLIDAY_PRIVATE_WORK,
    OFF_SEASON_SHARE,
    PURPOSES,
    SCHOOL_TRAVEL,
    TEST_DEPARTURES,
)
from jaadah.network_congestion.timing import (
    DIRECTIONS,
    bus_departures_by_slot,
    day_factor,
    day_type,
    departure_shares,
    departures_by_slot,
    in_season,
    in_term,
    school_legs,
    sensitivity_shares,
    slot_shares,
    timed_matrices,
)
from jaadah.network_congestion.trips import BUS_PURPOSE, SEASONAL_PURPOSE

SUMMER_WEDNESDAY = date(2026, 7, 15)
TERM_WEDNESDAY = date(2026, 9, 16)
TERM_THURSDAY = date(2026, 9, 17)
FRIDAY = date(2026, 9, 18)
SATURDAY = date(2026, 9, 19)
NATIONAL_DAY = date(2026, 9, 23)


def test_day_types_follow_the_friday_saturday_weekend():
    assert day_type(date(2026, 9, 13)) == 0     # Sunday
    assert day_type(TERM_WEDNESDAY) == 0
    assert day_type(TERM_THURSDAY) == 1
    assert day_type(FRIDAY) == 2
    assert day_type(SATURDAY) == 3


def test_departure_shares_add_up_to_one_and_peak_at_the_mean():
    shares = departure_shares([(1.0, 8.0, 0.5)])

    assert shares.sum() == pytest.approx(1)
    assert shares.argmax() in (31, 32)          # 07:45 or 08:00


def test_a_curve_near_midnight_wraps_around_the_day():
    shares = departure_shares([(1.0, 23.75, 1.0)])

    assert shares.sum() == pytest.approx(1)
    assert shares[0] > 0.01                     # just after midnight


def test_uniform_departures_spread_over_the_whole_day():
    assert departure_shares("uniform") == pytest.approx(np.full(96, 1 / 96))


def test_school_and_university_only_in_term():
    assert not in_term(SUMMER_WEDNESDAY)
    assert in_term(TERM_WEDNESDAY)
    assert day_factor("school", SUMMER_WEDNESDAY) == 0
    assert day_factor("university", SUMMER_WEDNESDAY) == 0
    assert day_factor("school", TERM_WEDNESDAY) == 1
    # the school year starts on Sunday 23 August 2026
    assert day_factor("school", date(2026, 8, 22)) == 0
    assert day_factor("school", date(2026, 8, 23)) == 1


def test_weekend_and_holiday_factors():
    assert day_factor("government_work", FRIDAY) == 0
    assert day_factor("private_work", SATURDAY) == DAY_FACTORS["private_work"][3]
    assert day_factor("government_work", NATIONAL_DAY) == 0
    assert day_factor("school", NATIONAL_DAY) == 0
    assert day_factor("private_work", NATIONAL_DAY) == pytest.approx(HOLIDAY_PRIVATE_WORK)
    assert day_factor("shopping_leisure", NATIONAL_DAY) == 1


def test_seasonal_places_attract_only_in_riyadh_season():
    assert not in_season(date(2026, 10, 13))
    assert in_season(date(2026, 10, 21))
    assert day_factor(SEASONAL_PURPOSE, date(2026, 10, 13)) == pytest.approx(OFF_SEASON_SHARE)
    assert day_factor(SEASONAL_PURPOSE, date(2026, 10, 21)) == 1


def test_slot_shares_add_up_to_the_day_factor():
    for purpose in ("school", "private_work", "shopping_leisure", "other",
                    "private_work_industry", "company_bus"):
        for direction in DIRECTIONS:
            shares = slot_shares(purpose, direction, TERM_THURSDAY)
            assert shares.sum() == pytest.approx(day_factor(purpose, TERM_THURSDAY))


def test_return_trips_come_after_outbound_trips():
    outbound = slot_shares("government_work", "outbound", TERM_WEDNESDAY)
    back = slot_shares("government_work", "return", TERM_WEDNESDAY)

    assert outbound.argmax() < back.argmax()


def test_private_work_to_the_flexible_hubs_is_split_off_without_losing_trips():
    od = {"private_work": np.arange(16, dtype=float).reshape(4, 4), "school": np.ones((4, 4))}

    timed = timed_matrices(od, flexible={2})

    assert timed["private_work_flexible"][:, 2] == pytest.approx(od["private_work"][:, 2])
    assert timed["private_work"][:, 2] == pytest.approx(0)
    assert timed["private_work"].sum() + timed["private_work_flexible"].sum() == pytest.approx(
        od["private_work"].sum())
    assert timed["school"] is od["school"]


def test_the_city_total_leaves_twice_a_day():
    totals = {"government_work": 1000.0, "school": 500.0}

    trips = departures_by_slot(totals, TERM_WEDNESDAY)

    assert trips.sum() == pytest.approx(2 * 1500)
    assert departures_by_slot(totals, FRIDAY).sum() == pytest.approx(0)


def test_private_work_to_the_industrial_centres_is_split_off_without_losing_trips():
    od = {"private_work": np.arange(16, dtype=float).reshape(4, 4)}

    timed = timed_matrices(od, flexible={1}, industry={3})

    assert timed["private_work_industry"][:, 3] == pytest.approx(od["private_work"][:, 3])
    assert timed["private_work_flexible"][:, 1] == pytest.approx(od["private_work"][:, 1])
    assert timed["private_work"][:, [1, 3]] == pytest.approx(0)
    assert sum(timed[k].sum() for k in ("private_work", "private_work_flexible", "private_work_industry")) \
        == pytest.approx(od["private_work"].sum())


def test_company_buses_arrive_before_the_morning_peak_and_work_on_holidays_like_private_work():
    shares = slot_shares("company_bus", "outbound", TERM_WEDNESDAY)

    assert shares[:28].sum() > 0.9               # before 07:00
    assert day_factor("company_bus", NATIONAL_DAY) == pytest.approx(HOLIDAY_PRIVATE_WORK)


def test_company_buses_are_never_added_to_the_car_departures():
    with pytest.raises(ValueError):
        departures_by_slot({"private_work": 100.0, BUS_PURPOSE: 10.0}, TERM_WEDNESDAY)

    buses = bus_departures_by_slot(10.0, TERM_WEDNESDAY)
    assert buses.sum() == pytest.approx(2 * 10.0)
    assert BUS_PURPOSE not in PURPOSES


def test_sensitivity_tests_have_no_map_timing():
    # distributed work and external commuters can't be timed as map purposes
    for test in TEST_DEPARTURES:
        assert test not in DEPARTURES
        assert test not in PURPOSES
    with pytest.raises(KeyError):
        slot_shares("external_central", "outbound", TERM_WEDNESDAY)


def test_school_trips_are_counted_leg_by_leg():
    students = np.full((2, 2), 100.0)
    s = SCHOOL_TRAVEL
    cars = (1 - s["bus_share"] - s["walk_share"]) / s["children_per_car"]

    legs = school_legs(students, TERM_WEDNESDAY)
    car_trips = sum(m.sum() * shares.sum() for m, shares, bus in legs if not bus)
    bus_trips = sum(m.sum() * shares.sum() for m, shares, bus in legs if bus)

    # drop-off and ride home for every car, the empty trip back and the
    # pick-up run for empty_return of them
    assert car_trips == pytest.approx(400 * cars * 2 * (1 + s["empty_return"]))
    assert bus_trips == pytest.approx(400 * 2 * s["bus_share"] / s["children_per_bus"])
    assert school_legs(students, SUMMER_WEDNESDAY)[0][1].sum() == 0


def test_government_staff_leave_earlier_than_private_sector_staff():
    government = slot_shares("government_work", "return", TERM_WEDNESDAY)
    private = slot_shares("private_work", "return", TERM_WEDNESDAY)
    mean_hour = lambda shares: (np.arange(96) * shares).sum() / shares.sum() / 4

    assert mean_hour(government) < 15.5 < 16.0 < mean_hour(private)
    # the step 3 times are kept for comparison, the trips are the same
    assert set(DEPARTURES_STEP3) <= set(DEPARTURES)


def test_sensitivity_timings_add_up_to_one():
    for test in TEST_DEPARTURES:
        for direction in DIRECTIONS:
            assert sensitivity_shares(test, direction).sum() == pytest.approx(1)

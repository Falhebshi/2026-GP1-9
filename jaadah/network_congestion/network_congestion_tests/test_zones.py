import math

import pytest

from jaadah.network_congestion.parameters import (
    AIRPORT,
    ARRIVING_SHARE,
    CAR_SHARE,
    CITY_WORKERS,
    EMPLOYMENT_CASES,
    INDUSTRY_WORKER_MIX,
    PLACE_TYPICAL,
    PURPOSES,
    SCHOOL_STUDENTS_PER_PERSON,
    TRIP_RATES,
)
from jaadah.network_congestion.segments import CITY_BOX, inside_box
from jaadah.network_congestion.zones import (
    DEFAULT_CENTRES,
    CentreComponent,
    airport_arriving_vehicles,
    arriving_trips,
    build_zones,
    daily_trip_ends,
    industry_vehicles,
    merge_places,
    names_match,
    parse_purposes,
    place_kind,
    read_centres,
    typical_sizes,
    work_vehicles,
)

# Artificial cells, places and centres, not from WorldPop or OSM
LON, LAT = 46.6500, 24.7300


def centre(rate="office_710", value=100000.0, unit="m2", element="", seasonal=False,
           purposes=None):
    return CentreComponent(
        centre="Test centre", component="part", lon=LON, lat=LAT, osm_element=element,
        rate=rate, value=value, unit=unit, purposes=purposes or {"private_work": 1.0},
        seasonal=seasonal,
    )


# ============================================================
# FROM SIZE TO TRIPS
# ============================================================

def test_office_trips_use_the_ite_rate_per_1000_sq_ft():
    # 1000 sq ft is 92.903 m2
    assert daily_trip_ends("office_710", 92.903, "m2") == pytest.approx(10.84, rel=1e-3)


def test_floor_area_rates_refuse_other_units():
    with pytest.raises(ValueError):
        daily_trip_ends("office_710", 500, "students")


def test_saudi_workers_to_cars():
    c = EMPLOYMENT_CASES["central"]
    cars, buses = work_vehicles(1000, 0, "central")

    assert cars == pytest.approx(1000 * c["attendance"] * c["saudi_by_car"] / c["saudi_per_car"])
    assert buses == 0


def test_company_buses_are_counted_apart_from_cars():
    c = EMPLOYMENT_CASES["central"]
    cars, buses = work_vehicles(0, 1000, "central", skilled_share=0.0)
    other = 1000 * c["attendance"] * (1 - c["on_site"])

    assert cars == pytest.approx(other * c["other_by_car"] / c["other_per_car"])
    assert buses == pytest.approx(other * c["other_by_bus"] / c["per_bus"])


def test_employment_cases_go_from_low_to_high():
    cars = [work_vehicles(CITY_WORKERS["saudi"], CITY_WORKERS["non_saudi"], case)[0]
            for case in ("low", "central", "high")]

    assert cars == sorted(cars)
    # about 1.87 million work cars in the central case (employment research)
    assert cars[1] == pytest.approx(1_868_430, rel=1e-3)


def test_industrial_workers_use_their_own_mix():
    expected = work_vehicles(
        1000 * INDUSTRY_WORKER_MIX["saudi"], 1000 * (1 - INDUSTRY_WORKER_MIX["saudi"]),
        skilled_share=INDUSTRY_WORKER_MIX["skilled_share"],
    )

    assert industry_vehicles(1000) == pytest.approx(expected)
    # trip ends are twice the cars arriving; buses are not trip ends
    assert daily_trip_ends("industry_workers", 1000, "workers") == pytest.approx(2 * expected[0])


def test_per_student_and_per_bed_rates():
    assert daily_trip_ends("university_540_550", 1000, "students") == pytest.approx(1360)
    assert daily_trip_ends("hospital_610", 100, "beds") == pytest.approx(1094)


def test_larger_malls_attract_fewer_trips_per_square_metre():
    small = daily_trip_ends("shopping_820", 20000, "m2") / 20000
    large = daily_trip_ends("shopping_820", 120000, "m2") / 120000

    assert large < small


def test_people_are_turned_into_vehicles_with_car_share_and_occupancy():
    trips = daily_trip_ends("visitor_trips", 2500, "visits")

    # 2,500 visits, 87.2% by car, 2.5 people per car, there and back
    assert trips == pytest.approx(2500 * CAR_SHARE / 2.5 * 2)


def test_arriving_trips_are_split_by_purpose():
    trips = arriving_trips("office_710", 92.903, "m2", {"private_work": 0.75, "health": 0.25})

    assert sum(trips.values()) == pytest.approx(10.84 * ARRIVING_SHARE, rel=1e-3)
    assert trips["private_work"] == pytest.approx(3 * trips["health"])


def test_purpose_shares_must_be_known_and_add_up_to_one():
    assert parse_purposes("private_work:0.9;shopping_leisure:0.1") == {
        "private_work": 0.9, "shopping_leisure": 0.1,
    }
    with pytest.raises(ValueError):
        parse_purposes("private_work:0.5")
    with pytest.raises(ValueError):
        parse_purposes("tourism:1.0")


# ============================================================
# THE AIRPORT
# ============================================================

NO_EXTRAS = dict(AIRPORT, transfer_share=0.0, road_share=1.0, park_share=0.0,
                 passengers_per_vehicle=1.0, other_vehicle_share=0.0)


def test_each_airport_passenger_brings_one_arriving_vehicle_without_extras():
    # 1,000 passengers a day, arrivals and departures together: 500
    # departing cars arrive to drop off, 500 cars arrive to pick up
    vehicles = airport_arriving_vehicles(1000, 0, NO_EXTRAS)

    assert vehicles["departing passengers"] == 500
    assert vehicles["picking up arriving passengers"] == 500
    assert sum(vehicles.values()) == 1000


def test_a_car_parked_on_the_way_out_does_not_arrive_again():
    parked = airport_arriving_vehicles(1000, 0, dict(NO_EXTRAS, park_share=0.2))

    assert parked["departing passengers"] == 500
    assert parked["picking up arriving passengers"] == 400


def test_transfers_metro_and_party_size_reduce_vehicles():
    params = dict(NO_EXTRAS, transfer_share=0.1, road_share=0.9, passengers_per_vehicle=2.0)

    vehicles = airport_arriving_vehicles(1000, 0, params)

    assert sum(vehicles.values()) == pytest.approx(1000 * 0.9 * 0.9 / 2.0)


def test_employees_and_other_vehicles_are_added_once():
    params = dict(NO_EXTRAS, employees_on_site=0.5, employees_per_vehicle=1.0,
                  other_vehicle_share=0.1)

    vehicles = airport_arriving_vehicles(0, 1000, params)

    assert vehicles["employees"] == pytest.approx(1000 * 0.5 * CAR_SHARE)
    assert vehicles["freight, service and other"] == pytest.approx(0.1 * vehicles["employees"])


def test_fewer_passengers_per_vehicle_means_more_vehicles():
    totals = [
        sum(airport_arriving_vehicles(112000, 18000, dict(AIRPORT, passengers_per_vehicle=p)).values())
        for p in (1.3, 1.8, 2.5)
    ]

    assert totals[0] > totals[1] > totals[2]


# ============================================================
# THE CENTRES FILE AND THE PLACE KINDS
# ============================================================

def test_every_centre_row_is_usable():
    components = read_centres()

    assert len({c.centre for c in components}) >= 15
    for component in components:
        assert inside_box((component.lon, component.lat), CITY_BOX)
        assert component.rate in TRIP_RATES or component.rate in (
            "shopping_820", "airport_passengers", "airport_employees", "visitor_trips", "industry_workers",
        )
        assert component.value > 0


def test_the_second_industrial_city_attracts_work_trips():
    industrial = [c for c in read_centres() if c.rate == "industry_workers"]

    assert [c.centre for c in industrial] == ["Riyadh Second Industrial City"]
    assert industrial[0].value == 120_000
    assert industrial[0].purposes == {"private_work": 1.0}
    assert inside_box((industrial[0].lon, industrial[0].lat), CITY_BOX)


def test_rows_waiting_for_a_location_are_left_out():
    import csv

    with DEFAULT_CENTRES.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    pending = {r["centre"] for r in rows if r["status"] != "active"}
    assert pending
    assert not pending & {c.centre for c in read_centres()}
    for row in rows:
        assert row["status"] in ("active", "pending_location", "osm_places_only")
        assert row["confidence"] in ("high", "medium", "low")


def test_every_place_kind_has_a_known_rate_and_purposes():
    for rate, size, _unit, _category, purposes in PLACE_TYPICAL.values():
        assert rate in TRIP_RATES or rate == "shopping_820"
        assert size > 0
        assert set(purposes) <= set(PURPOSES)
        assert sum(purposes.values()) == pytest.approx(1)


@pytest.mark.parametrize("tags, kind", [
    ({"amenity": "university"}, "university"),
    ({"amenity": "college"}, "college"),
    ({"amenity": "school"}, "school"),
    ({"healthcare": "hospital"}, "hospital"),
    ({"amenity": "clinic"}, "clinic"),
    ({"shop": "mall", "building": "yes"}, "mall"),
    ({"office": "government"}, "government_office"),
    ({"government": "ministry"}, "government_office"),
    ({"office": "diplomatic"}, "diplomatic"),
    ({"office": "company"}, "office"),
    ({"landuse": "commercial"}, "commercial_area"),
    ({"landuse": "retail"}, "retail_area"),
    ({"landuse": "military"}, None),
    ({"building": "yes"}, None),
])
def test_place_kind(tags, kind):
    assert place_kind(tags) == kind


# ============================================================
# CONTROL TOTALS AND ZONES
# ============================================================

def test_osm_places_share_what_the_named_centres_leave_of_the_total():
    places = [(LON, LAT, "office", "node/1"), (LON, LAT, "office", "node/2")]
    named = [centre(value=100000)]
    totals = {"office_floor_area": (500000, "m2", "test")}

    sizes = typical_sizes(places, named, totals)

    assert sizes["office"] == pytest.approx(200000)


def test_centres_larger_than_the_total_are_an_error():
    places = [(LON, LAT, "office", "node/1")]
    totals = {"office_floor_area": (50000, "m2", "test")}

    with pytest.raises(ValueError):
        typical_sizes(places, [centre(value=100000)], totals)


def test_a_centre_replaces_its_own_osm_place():
    places = [(LON, LAT, "mall", "way/7")]
    named = [centre(rate="shopping_820", value=50000, element="way/7",
                    purposes={"shopping_leisure": 1.0})]

    zones = build_zones([], places, named, totals={})

    expected = daily_trip_ends("shopping_820", 50000, "m2") * ARRIVING_SHARE
    assert zones[0].attraction["shopping_leisure"] == pytest.approx(expected, abs=0.1)


def test_school_trips_follow_population():
    zones = build_zones([(LON, LAT, 1000.0)], [(LON, LAT, "school", "node/3")], [], totals={})

    students = 1000 * SCHOOL_STUDENTS_PER_PERSON
    assert zones[0].attraction["school"] == pytest.approx(
        daily_trip_ends("school_520_525", students, "students") * ARRIVING_SHARE, abs=0.1,
    )


def test_seasonal_centres_are_kept_apart():
    named = [centre(rate="visitor_trips", value=10000, unit="visits", seasonal=True,
                    purposes={"shopping_leisure": 1.0})]

    zones = build_zones([], [], named, totals={})

    assert zones[0].attraction["shopping_leisure"] == 0
    assert zones[0].seasonal_attraction["shopping_leisure"] > 0


def test_the_zone_centre_leans_towards_where_people_live():
    zones = build_zones([(LON, LAT, 100.0), (LON + 0.001, LAT, 300.0)], [], [], totals={})

    assert len(zones) == 1
    assert zones[0].lon == pytest.approx(LON + 0.00075, abs=1e-5)
    assert math.isclose(zones[0].population, 400.0)


# ============================================================
# MERGING FEATURES THAT ARE ONE PLACE
# ============================================================

# about 10 m east per 0.0001 degree of longitude in Riyadh
def at(metres_east):
    return LON + metres_east / 101_000


def place(kind, element, metres_east=0.0, *names):
    return (at(metres_east), LAT, kind, element, tuple(names))


def kept(places, centres=()):
    return {p[3] for p in merge_places(places, list(centres))}


def test_names_match_across_spelling_and_complex_parts():
    assert names_match(("Dr. Sulaiman Al Habib Hospital",), ("Dr Sulaiman Al Habib Hospital",))
    assert names_match(("وزارة الخارجية",), ("تصديقات وزارة الخارجية",))
    assert names_match(("مجمع الحبيب - النساء والولادة",), ("مجمع الحبيب - العظام",))
    assert not names_match(("Ministry of Transport",), ("Security Patrols Directorate",))


def test_a_tight_cluster_of_unnamed_mall_buildings_is_one_mall():
    buildings = [place("mall", f"way/{i}", 40 * i) for i in range(4)]

    assert len(kept(buildings)) == 1


def test_scattered_mall_buildings_stay_separate():
    buildings = [place("mall", "way/1"), place("mall", "way/2", 120)]

    assert len(kept(buildings)) == 2


def test_independent_shop_units_along_a_street_stay_separate():
    units = [place("commercial_area", f"way/{i}", 25 * i) for i in range(14)]

    assert len(kept(units)) == 14


def test_commercial_outlines_with_the_same_name_merge():
    units = [place("commercial_area", "way/1", 0, "Souq Test"),
             place("commercial_area", "way/2", 40, "Souq Test")]

    assert len(kept(units)) == 1


def test_different_names_never_merge_however_close():
    offices = [place("government_office", "node/1", 0, "Ministry of Transport"),
               place("government_office", "node/2", 10, "Security Patrols Directorate")]

    assert len(kept(offices)) == 2


def test_two_tenants_in_one_building_stay_separate():
    offices = [place("office", "node/1", 0, "Mobily Service Centre"),
               place("office", "way/2", 6, "Zain Service Centre")]

    assert len(kept(offices)) == 2


def test_a_hospital_point_inside_its_outline_is_one_hospital_even_in_two_languages():
    hospital = [place("hospital", "node/1", 0, "Hammadi Suwaidi"),
                place("hospital", "way/2", 5, "مستشفى الحمادي")]

    assert len(kept(hospital)) == 1


def test_an_unnamed_neighbour_does_not_join_two_different_names():
    chain = [place("hospital", "node/1", 0, "Hospital One"),
             place("hospital", "node/2", 60),
             place("hospital", "node/3", 120, "Hospital Two")]

    remaining = kept(chain)

    assert {"node/1", "node/3"} <= remaining


def test_campus_parts_belong_to_their_centre_and_others_do_not():
    campus = centre(rate="university_540_550", value=1000, unit="students", element="way/9",
                    purposes={"university": 1.0})
    campus = CentreComponent(**{**campus.__dict__, "campus_kinds": frozenset({"college"}),
                                "campus_radius_m": 500.0})
    places = [place("university", "way/9"), place("college", "node/1", 300, "College of Science"),
              place("college", "node/2", 900, "Other College"), place("office", "node/3", 100)]

    remaining = kept(places, [campus])

    assert remaining == {"way/9", "node/2", "node/3"}


def test_build_zones_counts_a_merged_complex_once():
    cluster = [place("mall", f"way/{i}", 40 * i) for i in range(4)]
    single = [place("mall", "way/0")]

    merged = build_zones([], cluster, [], totals={})[0].attraction["shopping_leisure"]
    one = build_zones([], single, [], totals={})[0].attraction["shopping_leisure"]

    assert merged == pytest.approx(one)

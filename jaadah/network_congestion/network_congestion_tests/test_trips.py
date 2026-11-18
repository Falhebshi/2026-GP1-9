import numpy as np
import pytest

from jaadah.network_congestion.parameters import (
    CIRCUITY,
    INTRA_ZONE_KM,
    PURPOSES,
    TRIP_LENGTH_KM,
)
from jaadah.network_congestion.trips import (
    build_od,
    fastest,
    fit_beta,
    gravity,
    main_network,
    mean_length,
    productions,
    trip_lengths,
)

# Artificial zones, not from WorldPop or OSM: four zones along a line, 2 km apart
LAT = 24.70


def zone(i, population, **attraction):
    return {
        "zone_id": f"Z{i}", "lon": 46.60 + i * 2 / (111.32 * np.cos(np.radians(LAT))),
        "lat": LAT, "population": population,
        "attraction": {p: float(attraction.get(p, 0.0)) for p in PURPOSES},
    }


ZONES = [
    zone(0, 1000, school=100, private_work=10, shopping_leisure=50, health=5, other=0),
    zone(1, 2000, school=200, private_work=50, shopping_leisure=50, health=5, other=0),
    zone(2, 500, school=50, private_work=300, shopping_leisure=100, health=20, other=0),
    zone(3, 0, school=0, private_work=40, government_work=60, university=80,
         shopping_leisure=10, health=0, other=30),
]


def test_trip_length_is_straight_line_times_circuity():
    km = trip_lengths(ZONES)

    assert trip_lengths(ZONES, circuity=1.2)[0, 1] == pytest.approx(2 * 1.2, rel=1e-3)

    assert km[0, 1] == pytest.approx(2 * CIRCUITY, rel=1e-3)
    assert km[0, 3] == pytest.approx(6 * CIRCUITY, rel=1e-3)
    assert np.all(np.diag(km) == INTRA_ZONE_KM)


def test_trips_leaving_homes_follow_population_and_match_the_attraction():
    produced = productions(ZONES, "private_work")

    assert produced.sum() == pytest.approx(400)
    assert produced[1] == pytest.approx(2 * produced[0])
    assert produced[3] == 0


def test_gravity_sends_and_receives_every_zone_total():
    produced = np.array([100.0, 200.0, 50.0, 0.0])
    attracted = np.array([10.0, 50.0, 250.0, 40.0])

    trips = gravity(produced, attracted, trip_lengths(ZONES), beta=0.2)

    assert trips.sum(axis=1) == pytest.approx(produced, rel=1e-3)
    assert trips.sum(axis=0) == pytest.approx(attracted, rel=1e-3)


def test_a_steeper_decay_gives_shorter_trips():
    produced = np.array([100.0, 200.0, 50.0, 0.0])
    attracted = np.array([10.0, 50.0, 250.0, 40.0])
    km = trip_lengths(ZONES)

    gentle = mean_length(gravity(produced, attracted, km, 0.05), km)
    steep = mean_length(gravity(produced, attracted, km, 0.8), km)

    assert steep < gentle


def test_fit_beta_reaches_a_reachable_target():
    produced = np.array([100.0, 200.0, 50.0, 0.0])
    attracted = np.array([100.0, 100.0, 100.0, 50.0])
    km = trip_lengths(ZONES)

    beta = fit_beta(produced, attracted, km, 2.0)

    assert mean_length(gravity(produced, attracted, km, beta), km) == pytest.approx(2.0, rel=1e-3)


def test_fit_beta_admits_an_unreachable_target():
    produced = np.array([100.0, 200.0, 50.0, 0.0])
    km = trip_lengths(ZONES)

    # every destination is in the empty zone 3, at least 2.6 km from any home
    assert fit_beta(produced, np.array([0.0, 0.0, 0.0, 350.0]), km, 1.0) is None
    # no trip in these four zones is anywhere near 50 km long
    assert fit_beta(produced, np.array([100.0, 100.0, 100.0, 50.0]), km, 50.0) is None


def test_purposes_without_a_reachable_target_use_the_work_decay():
    # these four zones are only a few km apart: a reachable work target
    targets = dict(TRIP_LENGTH_KM, private_work=3.0)

    od = build_od(ZONES, trip_lengths(ZONES), targets)

    assert od["private_work"][2] == "fitted"
    for purpose in ("government_work", "university", "other"):
        assert od[purpose][2] == "shared"
        assert od[purpose][1] == od["private_work"][1]
    # no trips are lost
    for purpose, (trips, _beta, _how) in od.items():
        assert trips.sum() == pytest.approx(sum(z["attraction"][purpose] for z in ZONES), rel=1e-3)


def test_an_unreachable_work_target_is_an_error():
    # 11.6 km can't be reached in four zones 2 km apart
    with pytest.raises(ValueError):
        build_od(ZONES, trip_lengths(ZONES))


def test_main_network_leaves_out_dead_ends():
    # a two-way loop A-B-C, and a one-way spur C -> D that can't come back
    graph = {
        "A": [("B", 10, "s1")], "B": [("C", 10, "s2"), ("A", 10, "s3")],
        "C": [("A", 10, "s4"), ("D", 10, "s5")],
    }
    positions = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (5, 5)}

    assert main_network(graph, positions) == {"A", "B", "C"}


def test_fastest_route_time_and_distance():
    graph = {"A": [("B", 60, "s1"), ("C", 300, "s2")], "B": [("C", 60, "s3")]}
    lengths = {"s1": 1000, "s2": 2000, "s3": 1000}

    seconds, metres = fastest(graph, lengths, "A")

    assert seconds["C"] == 120
    assert metres["C"] == 2000

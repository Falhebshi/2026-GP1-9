import numpy as np
import pytest

from jaadah.network_congestion.employment import (
    city_vehicles,
    company_buses,
    distributed_work,
    external_commuters,
    gateway_zones,
    to_sites,
)
from jaadah.network_congestion.parameters import (
    DISTRIBUTED_WORK_MIX,
    EXTERNAL_COMMUTERS,
    EXTERNAL_GATEWAYS,
    PURPOSES,
)
from jaadah.network_congestion.trips import trip_lengths
from jaadah.network_congestion.zones import CentreComponent, industry_vehicles, zone_key

# Artificial zones, not from WorldPop or OSM: a row of zones across the city


def zone(lon, lat, population, **attraction):
    key = zone_key(lon, lat)
    return {
        "zone_id": f"Z{key[0]}_{key[1]}", "lon": lon, "lat": lat, "population": population,
        "attraction": {p: float(attraction.get(p, 0.0)) for p in PURPOSES},
    }


ZONES = [
    zone(46.53, 24.62, 50_000, private_work=1000, shopping_leisure=500),
    zone(46.65, 24.71, 200_000, private_work=20_000, government_work=10_000, shopping_leisure=5000),
    zone(46.75, 24.80, 100_000, private_work=5000, shopping_leisure=2000),
    zone(46.899, 24.545, 1000, private_work=30_000),
]
KM = trip_lengths(ZONES)
INDUSTRY = CentreComponent(
    centre="Test industrial city", component="industry", lon=46.899, lat=24.545, osm_element="",
    rate="industry_workers", value=120_000, unit="workers", purposes={"private_work": 1.0},
    seasonal=False,
)


def test_sites_draw_their_totals_from_nearby_homes():
    population = np.array([z["population"] for z in ZONES], dtype=float)
    sites = np.array([0, 0, 0, 500.0])

    trips = to_sites(population, sites, KM, 0.3)

    assert trips.sum(0) == pytest.approx(sites)
    assert trips[0, 3] < trips[2, 3]          # the far western zone sends fewer


def test_company_buses_match_the_city_total_and_serve_the_industrial_centre():
    buses = company_buses(ZONES, [INDUSTRY], KM, "central")
    _cars, total = city_vehicles("central")
    _c, own = industry_vehicles(INDUSTRY.value, "central")

    assert buses.sum() == pytest.approx(total)
    # the industrial centre takes its own buses, the rest go to the other work places
    assert buses[:, 3].sum() == pytest.approx(own)


def test_distributed_work_fills_the_gap_to_official_employment():
    beta = 0.3
    tests = distributed_work(ZONES, KM, beta, "central")
    cars, _buses = city_vehicles("central")
    in_scope = sum(z["attraction"]["private_work"] + z["attraction"]["government_work"] for z in ZONES)

    assert set(tests) == set(DISTRIBUTED_WORK_MIX)
    assert sum(t.sum() for t in tests.values()) == pytest.approx(cars - in_scope)


def test_external_commuters_enter_only_through_the_gateways():
    trips = external_commuters(ZONES, "low")
    gateways = set(gateway_zones(ZONES).values())

    assert trips.sum() == pytest.approx(EXTERNAL_COMMUTERS["low"])
    assert all(trips[i].sum() == 0 for i in range(len(ZONES)) if i not in gateways)
    assert sum(share for _x, _y, share in EXTERNAL_GATEWAYS.values()) == pytest.approx(1)

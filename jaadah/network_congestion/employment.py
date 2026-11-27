"""
Work traffic beyond the commuting cars of the major centres.

- company buses (company_buses): a heavy-vehicle layer of its own, part
  of the map, never added to the car trips. Their number comes from the
  city's workers (CITY_WORKERS, EMPLOYMENT_CASES); the industrial
  centres' own buses go there, the rest to the other in-scope work
  places;
- two sensitivity tests, never part of the map:
  - distributed_work: car trips to jobs outside the major centres, the
    gap between official employment and the in-scope work trips;
  - external_commuters: cars driving in from Riyadh region outside the
    city, through gateway zones on the main roads.

Only official statistics and project assumptions are used, no RCRC
data (Macro Map employment research and scope scenarios, November
2026).
"""

import numpy as np

from jaadah.network_congestion.parameters import (
    CITY_WORKERS,
    COMPANY_BUS_DECAY,
    DISTRIBUTED_WORK_MIX,
    EMPLOYMENT_CASE,
    EXTERNAL_COMMUTERS,
    EXTERNAL_GATEWAYS,
)
from jaadah.network_congestion.trips import gravity
from jaadah.network_congestion.zones import industry_vehicles, work_vehicles, zone_key

KM_PER_DEGREE_LAT = 110.54
KM_PER_DEGREE_LON = 101.2       # at Riyadh's latitude


def zone_index(zones: list[dict], lon: float, lat: float) -> int | None:
    key = zone_key(lon, lat)
    zone_id = f"Z{key[0]}_{key[1]}"
    return next((i for i, z in enumerate(zones) if z["zone_id"] == zone_id), None)


def city_vehicles(case: str = EMPLOYMENT_CASE) -> tuple[float, float]:
    """Work cars and company buses the city's workers imply."""

    return work_vehicles(CITY_WORKERS["saudi"], CITY_WORKERS["non_saudi"], case)


def to_sites(population: np.ndarray, sites: np.ndarray, km: np.ndarray, beta: float) -> np.ndarray:
    """
    Trips from homes to a few work sites, each site drawing its total
    from the homes around it (attraction constrained), so a lone site
    isn't forced to draw evenly from the whole city.
    """

    pull = population[:, None] * np.exp(-beta * km)

    return pull / pull.sum(0, keepdims=True) * sites[None, :]


def company_buses(zones: list[dict], centres: list, km: np.ndarray, case: str = EMPLOYMENT_CASE) -> np.ndarray:
    """Weekday company buses from where people live to the work places."""

    population = np.array([z["population"] for z in zones], dtype=float)
    work = np.array([z["attraction"]["private_work"] for z in zones], dtype=float)
    _cars, total = city_vehicles(case)

    sites = np.zeros(len(zones))
    for centre in centres:
        if centre.rate == "industry_workers":
            _c, buses = industry_vehicles(centre.value, case)
            sites[zone_index(zones, centre.lon, centre.lat)] += buses

    rest = max(total - sites.sum(), 0.0)
    elsewhere = work.copy()
    elsewhere[sites > 0] = 0.0
    sites += rest * elsewhere / elsewhere.sum()

    return to_sites(population, sites, km, COMPANY_BUS_DECAY)


def distributed_work(zones: list[dict], km: np.ndarray, beta: float, case: str = EMPLOYMENT_CASE) -> dict:
    """
    Sensitivity test: car trips to jobs outside the major centres, by
    sector timing (DISTRIBUTED_WORK_MIX), half placed by population and
    half by commercial activity.
    """

    population = np.array([z["population"] for z in zones], dtype=float)
    shops = np.array([z["attraction"]["shopping_leisure"] for z in zones], dtype=float)
    in_scope = sum(z["attraction"]["private_work"] + z["attraction"]["government_work"] for z in zones)
    cars, _buses = city_vehicles(case)
    gap = max(cars - in_scope, 0.0)

    weights = 0.5 * population / population.sum() + 0.5 * shops / shops.sum()
    matrix = gravity(population / population.sum() * gap, weights * gap, km, beta)

    return {sector: matrix * share for sector, share in DISTRIBUTED_WORK_MIX.items()}


def gateway_zones(zones: list[dict]) -> dict[str, int]:
    """The zone nearest each entry road's point on the city box edge."""

    lon = np.array([z["lon"] for z in zones])
    lat = np.array([z["lat"] for z in zones])

    return {
        name: int(np.argmin(np.hypot((lon - x) * KM_PER_DEGREE_LON, (lat - y) * KM_PER_DEGREE_LAT)))
        for name, (x, y, _share) in EXTERNAL_GATEWAYS.items()
    }


def external_commuters(zones: list[dict], case: str = EMPLOYMENT_CASE) -> np.ndarray:
    """Sensitivity test: cars entering for work, from the gateway zones to the work places."""

    work = np.array([z["attraction"]["private_work"] + z["attraction"]["government_work"] for z in zones])
    matrix = np.zeros((len(zones), len(zones)))

    for name, zone in gateway_zones(zones).items():
        matrix[zone] += EXTERNAL_COMMUTERS[case] * EXTERNAL_GATEWAYS[name][2] * work / work.sum()

    return matrix

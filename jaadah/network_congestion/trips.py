"""
Trip generation and distribution: origin-destination (OD) matrices.

Step 2 of the Macro Map synthetic traffic (Macro Map Synthetic Data
Methodology). From the zones (zones.py) it builds, for each trip
purpose, a weekday matrix of trips from home zones to activity zones:

1. Trip length between zones: straight-line distance times CIRCUITY
   (INTRA_ZONE_KM inside a zone), an approximation of the distance
   driven, not a road distance. The distance along our network is
   kept for reference, but not used: the network has only main roads,
   so short trips would look far longer than they are. The routes
   themselves are found on the network in step 4.
2. Trip generation: trips start from homes in proportion to population
   and end at activity places in proportion to their attraction (vehicle
   trips arriving on a weekday). Each purpose's trips leaving homes
   equal the trips its in-scope places attract, so trips to places
   outside the project scope are not loaded onto the major centres.
3. Trip distribution: a doubly constrained gravity model,

       T(i, j) = a(i) P(i) b(j) A(j) exp(-beta x length(i, j)),

   with a and b balanced so every zone sends its productions and
   receives its attractions (Furness method), and beta chosen for each
   purpose so the mean trip length matches TRIP_LENGTH_KM. A purpose
   without a target, or whose target the in-scope destinations can't
   reach, uses the private-work beta.

The matrices are outbound trips (home to activity); the return trips
and the time of day come in step 3. The company buses (employment.py)
get a matrix of their own, in buses, never added to the cars. With
--sensitivity the employment tests (distributed work and external
commuters, low, central and high) are written to a separate file, never
used for the map. Only open data and project assumptions are used, no
RCRC data.

    python -m jaadah.network_congestion.trips
"""

import argparse
import heapq
import json
import math
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.demand import NearestJunction, road_graph
from jaadah.network_congestion.parameters import (
    CIRCUITY,
    COMPANY_BUS_PCE,
    EMPLOYMENT_CASE,
    EMPLOYMENT_CASES,
    FURNESS_ITERATIONS,
    FURNESS_TOLERANCE,
    INTRA_ZONE_KM,
    PURPOSES,
    SHARED_DECAY_PURPOSE,
    TRIP_LENGTH_KM,
)
from jaadah.network_congestion.segments import DEFAULT_OUTPUT_DIR, line_length_m
from jaadah.network_congestion.zones import DEFAULT_CENTRES, DEFAULT_ZONES, read_centres

DEFAULT_SEGMENTS = DEFAULT_OUTPUT_DIR / "road_segments.json"
DEFAULT_MAPPINGS = DEFAULT_OUTPUT_DIR / "segment_mappings.json"
# rebuilt from the code when needed (about 10 seconds), not committed
DEFAULT_OD = DEFAULT_OUTPUT_DIR / "od_matrices.npz"
DEFAULT_OD_SUMMARY = DEFAULT_OUTPUT_DIR / "od_summary.json"
# employment sensitivity tests, written only with --sensitivity, not committed
DEFAULT_SENSITIVITY = DEFAULT_OUTPUT_DIR / "od_sensitivity.npz"

# trips to seasonal places (Riyadh Season), apart from all-year shopping
SEASONAL_PURPOSE = "shopping_leisure_season"

# company buses: their own matrix, in buses
BUS_PURPOSE = "company_bus"


# ============================================================
# 1. TRAVEL BETWEEN ZONES
# ============================================================

def reachable(graph: dict, start) -> set:
    """Junctions reachable from start."""

    seen, stack = {start}, [start]

    while stack:
        for following, _seconds, _segment in graph.get(stack.pop(), ()):
            if following not in seen:
                seen.add(following)
                stack.append(following)

    return seen


def main_network(graph: dict, positions: dict) -> set:
    """
    The junctions that can both reach and be reached from the city's main
    network (its largest strongly connected part, found from the junction
    nearest the network's centre of gravity).
    """

    lon = sum(p[0] for p in positions.values()) / len(positions)
    lat = sum(p[1] for p in positions.values()) / len(positions)
    reverse = defaultdict(list)
    for junction, exits in graph.items():
        for following, seconds, segment_id in exits:
            reverse[following].append((junction, seconds, segment_id))

    best = None
    for junction in sorted(positions, key=lambda j: (positions[j][0] - lon) ** 2 + (positions[j][1] - lat) ** 2)[:50]:
        both = reachable(graph, junction) & reachable(reverse, junction)
        if best is None or len(both) > len(best):
            best = both

    return best


def fastest(graph: dict, lengths: dict, start) -> tuple[dict, dict]:
    """Fastest-route time (s) and distance (m) from one junction to all others."""

    seconds = {start: 0.0}
    metres = {start: 0.0}
    queue = [(0.0, start)]
    done = set()

    while queue:
        now, junction = heapq.heappop(queue)
        if junction in done:
            continue
        done.add(junction)

        for following, travel, segment_id in graph.get(junction, ()):
            arrival = now + travel
            if arrival < seconds.get(following, math.inf):
                seconds[following] = arrival
                metres[following] = metres[junction] + lengths[segment_id]
                heapq.heappush(queue, (arrival, following))

    return seconds, metres


def trip_lengths(zones: list[dict], circuity: float = CIRCUITY) -> np.ndarray:
    """
    Trip length (km) between every pair of zones: straight line x
    circuity, an approximation of the distance driven.
    """

    lon = np.array([z["lon"] for z in zones])
    lat = np.array([z["lat"] for z in zones])
    east = (lon[:, None] - lon[None, :]) * 111.32 * np.cos(np.radians(lat.mean()))
    north = (lat[:, None] - lat[None, :]) * 110.54
    km = np.hypot(east, north) * circuity
    np.fill_diagonal(km, INTRA_ZONE_KM)

    return np.maximum(km, INTRA_ZONE_KM)


def zone_travel(
    zones: list[dict],
    segments: list[RoadSegment],
    mappings: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Free-flow time (minutes) and distance (km) along the network between
    every pair of zones, for reference.
    """

    graph, positions = road_graph(segments, mappings)
    usable = main_network(graph, positions)
    nearest = NearestJunction({j: positions[j] for j in usable})
    lengths = {s.segment_id: line_length_m(s.geometry) for s in segments}
    connectors = [nearest.find(z["lon"], z["lat"]) for z in zones]

    n = len(zones)
    minutes = np.zeros((n, n))
    km = np.zeros((n, n))
    by_junction = defaultdict(list)
    for i, junction in enumerate(connectors):
        by_junction[junction].append(i)

    for junction, origins in by_junction.items():
        seconds, metres = fastest(graph, lengths, junction)
        to_minutes = np.array([seconds[c] / 60 for c in connectors])
        to_km = np.array([metres[c] / 1000 for c in connectors])
        for i in origins:
            minutes[i] = to_minutes
            km[i] = to_km

    return minutes, km


# ============================================================
# 2 AND 3. GENERATION AND DISTRIBUTION
# ============================================================

def productions(zones: list[dict], purpose: str) -> np.ndarray:
    """
    Trips leaving home for a purpose, by zone: in proportion to
    population, adding up to the trips the purpose's places attract.
    """

    population = np.array([z["population"] for z in zones], dtype=float)
    attracted = sum(z["attraction"][purpose] for z in zones)

    return attracted * population / population.sum()


def gravity(
    produced: np.ndarray,
    attracted: np.ndarray,
    km: np.ndarray,
    beta: float,
) -> np.ndarray:
    """Doubly constrained gravity model, balanced with the Furness method."""

    deterrence = np.exp(-beta * km)
    trips = np.outer(produced, attracted) * deterrence

    for _ in range(FURNESS_ITERATIONS):
        rows = trips.sum(axis=1)
        trips *= np.divide(produced, rows, out=np.zeros_like(rows), where=rows > 0)[:, None]
        columns = trips.sum(axis=0)
        trips *= np.divide(attracted, columns, out=np.zeros_like(columns), where=columns > 0)[None, :]

        if np.allclose(trips.sum(axis=1), produced, rtol=FURNESS_TOLERANCE, atol=1e-6):
            break

    return trips


def mean_length(trips: np.ndarray, km: np.ndarray) -> float:
    total = trips.sum()
    return float((trips * km).sum() / total) if total > 0 else 0.0


BETA_SEARCH = (1e-4, 2.0)


def fit_beta(
    produced: np.ndarray,
    attracted: np.ndarray,
    km: np.ndarray,
    target_km: float,
) -> float | None:
    """
    The beta (per km) whose trips have the target mean length
    (bisection), or None when the target is out of reach: even the
    steepest decay searched leaves trips longer than the target (the
    destinations are too few or too far apart), or even the gentlest
    leaves them shorter.
    """

    low, high = BETA_SEARCH
    if not (mean_length(gravity(produced, attracted, km, high), km)
            <= target_km
            <= mean_length(gravity(produced, attracted, km, low), km)):
        return None

    for _ in range(40):
        middle = math.sqrt(low * high)
        if mean_length(gravity(produced, attracted, km, middle), km) > target_km:
            low = middle
        else:
            high = middle

    return math.sqrt(low * high)


def build_od(zones: list[dict], km: np.ndarray, targets: dict = TRIP_LENGTH_KM) -> dict:
    """
    The OD matrix of every purpose, with its beta and how the beta was
    set ("fitted", or "shared" when there is no reachable target).
    """

    inputs = {
        purpose: (
            productions(zones, purpose),
            np.array([z["attraction"][purpose] for z in zones], dtype=float),
        )
        for purpose in PURPOSES
    }
    betas = {}
    for purpose in PURPOSES:
        target = targets.get(purpose)
        if target:
            betas[purpose] = fit_beta(*inputs[purpose], km, target)

    shared = betas.get(SHARED_DECAY_PURPOSE)
    if shared is None:
        raise ValueError(
            f"the {SHARED_DECAY_PURPOSE} trip length can't be reached with these zones, "
            "so there is no decay to share"
        )
    result = {}
    for purpose, (produced, attracted) in inputs.items():
        beta, how = betas.get(purpose), "fitted"
        if beta is None:
            beta, how = shared, "shared"
        result[purpose] = (gravity(produced, attracted, km, beta), beta, how)

    # seasonal places (Riyadh Season): their own matrix with the shopping
    # decay, used by timing.py only in season
    seasonal = np.array([z.get("seasonal_attraction", {}).get("shopping_leisure", 0.0) for z in zones])
    if seasonal.sum() > 0:
        population = np.array([z["population"] for z in zones], dtype=float)
        beta = result["shopping_leisure"][1]
        result[SEASONAL_PURPOSE] = (
            gravity(seasonal.sum() * population / population.sum(), seasonal, km, beta),
            beta, "shared (shopping)",
        )

    return result


def summary(zones: list[dict], od: dict, km: np.ndarray, targets: dict = TRIP_LENGTH_KM) -> dict:
    """Totals, mean trip lengths and the largest flows, for review."""

    content = {"built": date.today().isoformat(), "purposes": {}}

    for purpose, (trips, beta, how) in od.items():
        diagonal = float(np.trace(trips))
        top = np.dstack(np.unravel_index(np.argsort(trips, axis=None)[::-1][:10], trips.shape))[0]
        content["purposes"][purpose] = {
            "trips": round(float(trips.sum())),
            "beta_per_km": round(beta, 5),
            "beta_set": how,
            "target_km": targets.get(purpose),
            "mean_km": round(mean_length(trips, km), 2),
            "inside_zone_share": round(diagonal / trips.sum(), 3) if trips.sum() else 0,
            "largest_flows": [
                [zones[i]["zone_id"], zones[j]["zone_id"], round(float(trips[i, j]))] for i, j in top
            ],
        }

    total = sum(t.sum() for t, _b, _h in od.values())
    content["all_purposes_mean_km"] = round(
        sum(mean_length(t, km) * t.sum() for t, _b, _h in od.values()) / total, 2,
    )
    content["circuity"] = CIRCUITY

    return content


def main() -> None:
    """Command line entry point."""

    parser = argparse.ArgumentParser(description="Build the OD matrices.")
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OD)
    parser.add_argument("--summary", type=Path, default=DEFAULT_OD_SUMMARY)
    parser.add_argument("--school-km", type=float, default=TRIP_LENGTH_KM["school"],
                        help="mean school trip length (assumption, for sensitivity tests)")
    parser.add_argument("--circuity", type=float, default=CIRCUITY,
                        help="road circuity factor (approximation, for sensitivity tests)")
    parser.add_argument("--centres", type=Path, default=DEFAULT_CENTRES)
    parser.add_argument("--employment-case", choices=sorted(EMPLOYMENT_CASES), default=EMPLOYMENT_CASE,
                        help="workers to vehicles case for the company buses (sensitivity tests)")
    parser.add_argument("--sensitivity", action="store_true",
                        help="also write the employment tests (distributed work, external commuters)")
    parser.add_argument("--sensitivity-out", type=Path, default=DEFAULT_SENSITIVITY)
    args = parser.parse_args()

    from jaadah.network_congestion import employment

    started = time.perf_counter()
    zones = json.loads(args.zones.read_text(encoding="utf-8"))["zones"]
    segments = [RoadSegment(**r) for r in json.loads(args.segments.read_text(encoding="utf-8"))["segments"]]
    mappings = {r["segment_id"]: r for r in json.loads(args.mappings.read_text(encoding="utf-8"))["mappings"]}

    network_minutes, network_km = zone_travel(zones, segments, mappings)
    km = trip_lengths(zones, args.circuity)
    targets = dict(TRIP_LENGTH_KM, school=args.school_km)
    od = build_od(zones, km, targets)
    buses = employment.company_buses(zones, read_centres(args.centres), km, args.employment_case)

    np.savez_compressed(
        args.out,
        zone_ids=np.array([z["zone_id"] for z in zones]),
        trip_km=km.astype(np.float32),
        network_minutes=network_minutes.astype(np.float32),
        network_km=network_km.astype(np.float32),
        **{purpose: trips.astype(np.float32) for purpose, (trips, _b, _h) in od.items()},
        **{BUS_PURPOSE: buses.astype(np.float32)},
    )
    content = summary(zones, od, km, targets)
    content["circuity"] = args.circuity
    content[BUS_PURPOSE] = {
        "buses": round(float(buses.sum())),
        "mean_km": round(mean_length(buses, km), 2),
        "car_equivalent": COMPANY_BUS_PCE,
        "employment_case": args.employment_case,
    }

    if args.sensitivity:
        beta = od[SHARED_DECAY_PURPOSE][1]
        tests = {}
        for case in EMPLOYMENT_CASES:
            for sector, trips in employment.distributed_work(zones, km, beta, case).items():
                tests[f"distributed_{sector}_{case}"] = trips.astype(np.float32)
            tests[f"external_{case}"] = employment.external_commuters(zones, case).astype(np.float32)
        np.savez_compressed(args.sensitivity_out, **tests)
        content["sensitivity"] = {name: round(float(t.sum())) for name, t in tests.items()}
    args.summary.write_text(json.dumps(content, indent=1), encoding="utf-8")

    for purpose, values in content["purposes"].items():
        print(f"{purpose:17s} {values['trips']:>10,} trips  mean {values['mean_km']:5.2f} km "
              f"(target {values['target_km']}, beta {values['beta_per_km']} {values['beta_set']})  "
              f"inside zone {values['inside_zone_share']:.0%}")
    bus = content[BUS_PURPOSE]
    print(f"company buses {bus['buses']:>10,} buses  mean {bus['mean_km']:5.2f} km ({args.employment_case} case)")
    print(f"all purposes mean {content['all_purposes_mean_km']} km; "
          f"written {args.out} in {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()

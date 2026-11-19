"""
Putting the trips on the roads: assignment with congestion.

Step 4 of the Macro Map synthetic traffic. From the OD matrices (step 2)
and their times (step 3) it finds, for every hour of a date, how many
vehicles use each road segment and how long the segment takes:

1. Connections: each zone joins the network at up to ZONE_CONNECTORS
   junctions on primary or secondary roads near its centre, its trips
   split equally between them, so no trip is copied or lost.
2. Local streets: trips between zones closer than LOCAL_STREETS_KM stay
   on local streets, which the network doesn't hold.
3. Time on the road: a trip counts in each hour it spends driving, in
   proportion to the time it spends there (free-flow network time plus
   ACCESS_MINUTES), not only in the hour it leaves.
4. Routes with congestion: each hour's trips are loaded in rounds
   (ASSIGNMENT_ROUNDS); after each round every segment's travel time
   follows the BPR curve, t0 (1 + a (v/c)^b), and later rounds take the
   new fastest routes.

Company and school buses count as COMPANY_BUS_PCE cars on the road. The
model's own congestion (vehicle travel time against the same travel at
free flow) is reported for each hour. For the map display, each quarter
hour is then scaled to TomTom's city congestion level (tomtom_calibration):
that is calibration to TomTom, not an independent validation, and the
model's evening is known to be lighter than TomTom's (Macro Map Step 4
review: commuting and school alone can't make the evening the busiest
period).

The OD matrices are used as they are; only the times of step 3 and the
assumptions above shape the result. Open data and project assumptions
only, no RCRC data.

    python -m jaadah.network_congestion.assignment --date 2026-09-16
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
    ACCESS_MINUTES,
    ASSIGNMENT_ROUNDS,
    BPR_ALPHA,
    BPR_BETA,
    CAPACITY_PER_LANE,
    CIRCUITY,
    COMPANY_BUS_PCE,
    CONNECTOR_RADIUS_KM,
    INTERVALS_PER_DAY,
    LOCAL_STREETS_KM,
    ZONE_CONNECTORS,
)
from jaadah.network_congestion.segments import DEFAULT_OUTPUT_DIR, line_length_m
from jaadah.network_congestion.timing import (
    BUS_PURPOSE,
    flexible_zones,
    industry_zones,
    school_legs,
    slot_shares,
    timed_matrices,
)
from jaadah.network_congestion.trips import DEFAULT_MAPPINGS, DEFAULT_OD, DEFAULT_SEGMENTS, main_network
from jaadah.network_congestion.zones import DEFAULT_ZONES, read_centres

# rebuilt from the code when needed, not committed
DEFAULT_ASSIGNED = DEFAULT_OUTPUT_DIR / "assigned_flows.json"

KM_PER_DEGREE_LAT = 110.54
KM_PER_DEGREE_LON = 101.2       # at Riyadh's latitude
SLOTS_PER_HOUR = INTERVALS_PER_DAY // 24
NOT_MATRICES = ("zone_ids", "trip_km", "network_minutes", "network_km", BUS_PURPOSE)


# ============================================================
# NETWORK
# ============================================================

class Network:
    """The main road network as arrays: one edge per junction pair (the faster segment)."""

    def __init__(self, segments: list[RoadSegment], mappings: dict):
        graph, positions = road_graph(segments, mappings)
        usable = main_network(graph, positions)
        self.positions = positions
        self.junctions = sorted(usable)
        self.index = {j: k for k, j in enumerate(self.junctions)}
        by_id = {s.segment_id: s for s in segments}

        pairs = {}
        for a in self.junctions:
            for b, seconds, sid in graph.get(a, ()):
                if b in self.index and ((a, b) not in pairs or seconds < pairs[(a, b)][0]):
                    pairs[(a, b)] = (seconds, sid)

        self.edge_from = np.array([self.index[a] for a, _b in pairs])
        self.edge_to = np.array([self.index[b] for _a, b in pairs])
        self.segment = [sid for _s, sid in pairs.values()]
        self.free_seconds = np.array([seconds for seconds, _sid in pairs.values()])
        self.capacity = np.array([
            CAPACITY_PER_LANE[by_id[sid].road_class] * max(by_id[sid].lane_count, 1) for sid in self.segment
        ], dtype=float)
        self.edge_of = {(u, v): e for e, (u, v) in enumerate(zip(self.edge_from, self.edge_to))}
        self.out = defaultdict(list)
        for e, (u, v) in enumerate(zip(self.edge_from, self.edge_to)):
            self.out[u].append((v, e))

        local = set()
        for s in segments:
            if s.road_class in ("primary", "secondary"):
                local.update((mappings[s.segment_id]["from_node_id"], mappings[s.segment_id]["to_node_id"]))
        self.connectable = [j for j in self.junctions if j in local]

    def __len__(self):
        return len(self.junctions)


def connector_weights(zones: list[dict], network: Network) -> np.ndarray:
    """
    Zones x junctions: each zone's share of trips at each of its
    connections. Every row adds up to 1, so no trip is copied or lost.
    """

    lon = np.array([network.positions[j][0] for j in network.connectable])
    lat = np.array([network.positions[j][1] for j in network.connectable])
    weights = np.zeros((len(zones), len(network)))

    for i, z in enumerate(zones):
        km = np.hypot((lon - z["lon"]) * KM_PER_DEGREE_LON, (lat - z["lat"]) * KM_PER_DEGREE_LAT)
        near = [k for k in np.argsort(km)[:ZONE_CONNECTORS] if km[k] <= CONNECTOR_RADIUS_KM]
        if not near:
            near = [int(np.argmin(km))]
        for k in near:
            weights[i, network.index[network.connectable[k]]] += 1.0 / len(near)

    return weights


# ============================================================
# DEMAND BY HOUR
# ============================================================

def slot_departures(od: dict, buses: np.ndarray, zones: list[dict], centres: list, day: date) -> list[np.ndarray]:
    """
    Vehicles leaving in each quarter hour of a date, zone to zone, in car
    equivalents (company and school buses count COMPANY_BUS_PCE cars).
    """

    timed = timed_matrices(od, flexible_zones(zones, centres), industry_zones(zones, centres))
    students = timed.pop("school")
    legs = [(m * (COMPANY_BUS_PCE if bus else 1.0), shares) for m, shares, bus in school_legs(students, day)]
    for purpose, trips in timed.items():
        legs.append((trips, slot_shares(purpose, "outbound", day)))
        legs.append((trips.T, slot_shares(purpose, "return", day)))
    legs.append((buses * COMPANY_BUS_PCE, slot_shares(BUS_PURPOSE, "outbound", day)))
    legs.append((buses.T * COMPANY_BUS_PCE, slot_shares(BUS_PURPOSE, "return", day)))

    return [sum(m * shares[s] for m, shares in legs) for s in range(INTERVALS_PER_DAY)]


def hourly_on_road(departures: list[np.ndarray], network_minutes: np.ndarray) -> list[np.ndarray]:
    """
    Vehicles on the road in each hour: each trip leaves in the middle of
    its quarter hour and counts in each hour in proportion to the time it
    spends there; the day wraps around midnight, so every trip counts
    exactly once in total.
    """

    n = departures[0].shape[0]
    hours = [np.zeros((n, n)) for _ in range(24)]
    duration = (network_minutes + ACCESS_MINUTES) / 60.0

    for slot, trips in enumerate(departures):
        start = (slot + 0.5) / SLOTS_PER_HOUR
        end = start + duration
        for h in range(int(start), int(np.floor(end.max())) + 1):
            overlap = np.clip(np.minimum(end, h + 1) - np.maximum(start, h), 0, None) / duration
            hours[h % 24] += trips * overlap

    return hours


def on_local_streets(trip_km: np.ndarray) -> np.ndarray:
    """Zone pairs whose trips stay on local streets (straight line under LOCAL_STREETS_KM)."""

    return trip_km / CIRCUITY < LOCAL_STREETS_KM


# ============================================================
# ASSIGNMENT
# ============================================================

def shortest_trees(network: Network, cost: np.ndarray, origins: np.ndarray):
    """(distance, previous junction) from each origin; SciPy when installed, else Dijkstra here."""

    try:
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra
    except ImportError:
        csr_matrix = None

    if csr_matrix is not None:
        matrix = csr_matrix((cost, (network.edge_from, network.edge_to)), shape=(len(network), len(network)))
        for chunk in np.array_split(origins, max(1, len(origins) // 200)):
            distance, previous = dijkstra(matrix, directed=True, indices=chunk, return_predecessors=True)
            yield from zip(chunk, distance, previous)
        return

    for origin in origins:
        distance = np.full(len(network), math.inf)
        previous = np.full(len(network), -9999)
        distance[origin] = 0.0
        queue = [(0.0, origin)]
        while queue:
            d, u = heapq.heappop(queue)
            if d > distance[u]:
                continue
            for v, e in network.out[u]:
                if d + cost[e] < distance[v]:
                    distance[v] = d + cost[e]
                    previous[v] = u
                    heapq.heappush(queue, (distance[v], v))
        yield origin, distance, previous


def load(network: Network, trips: np.ndarray, cost: np.ndarray) -> np.ndarray:
    """Every trip on its fastest route at the given costs (junction to junction trips)."""

    flow = np.zeros(len(network.free_seconds))
    origins = np.where(trips.sum(1) > 0)[0]

    for origin, distance, previous in shortest_trees(network, cost, origins):
        arriving = trips[origin].copy()
        arriving[origin] = 0.0
        for v in np.argsort(-distance):
            a = arriving[v]
            if a == 0 or v == origin or previous[v] < 0:
                continue
            u = previous[v]
            arriving[u] += a
            flow[network.edge_of[(u, v)]] += a

    return flow


def bpr_seconds(network: Network, flow: np.ndarray) -> np.ndarray:
    return network.free_seconds * (1 + BPR_ALPHA * (flow / network.capacity) ** BPR_BETA)


def assign(network: Network, trips: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Incremental assignment: (vehicles an hour on each edge, its travel time in seconds)."""

    flow = np.zeros(len(network.free_seconds))
    cost = network.free_seconds.copy()

    for share in ASSIGNMENT_ROUNDS:
        flow += load(network, trips * share, cost)
        cost = bpr_seconds(network, flow)

    return flow, cost


def congestion_index(network: Network, flow: np.ndarray, seconds: np.ndarray) -> float:
    """Extra vehicle travel time against free flow, as TomTom measures the city (0 when empty)."""

    free = (flow * network.free_seconds).sum()

    return float((flow * seconds).sum() / free - 1) if free > 0 else 0.0


# ============================================================
# DISPLAY CALIBRATION TO TOMTOM
# ============================================================

def tomtom_calibration(model_index: list[float], tomtom_index: list[float]) -> list[float]:
    """
    For the map display only: the factor on each quarter hour's model
    delay that brings the city congestion to TomTom's level (TomTom's
    index is 1 + congestion level). Calibration, not validation; a factor
    far from 1 shows where the model's own pattern differs from TomTom.
    """

    factors = []

    for model, tomtom in zip(model_index, tomtom_index):
        target = tomtom - 1
        factors.append(target / model if model > 0 else 1.0)

    return factors


# ============================================================
# COMMAND LINE
# ============================================================

def main() -> None:
    """Command line entry point."""

    parser = argparse.ArgumentParser(description="Assign a date's trips to the main roads.")
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 9, 16))
    parser.add_argument("--hours", type=int, nargs="*", default=list(range(24)))
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--od", type=Path, default=DEFAULT_OD)
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--out", type=Path, default=DEFAULT_ASSIGNED)
    args = parser.parse_args()

    zones = json.loads(args.zones.read_text(encoding="utf-8"))["zones"]
    stored = np.load(args.od)
    od = {k: stored[k].astype(float) for k in stored.files if k not in NOT_MATRICES}
    segments = [RoadSegment(**r) for r in json.loads(args.segments.read_text(encoding="utf-8"))["segments"]]
    mappings = {r["segment_id"]: r for r in json.loads(args.mappings.read_text(encoding="utf-8"))["mappings"]}

    network = Network(segments, mappings)
    weights = connector_weights(zones, network)
    departures = slot_departures(od, stored[BUS_PURPOSE].astype(float), zones, read_centres(), args.date)
    hours = hourly_on_road(departures, stored["network_minutes"].astype(float))
    local = on_local_streets(stored["trip_km"].astype(float))

    content = {"date": args.date.isoformat(), "vehicles_day": float(sum(d.sum() for d in departures)), "hours": {}}
    if args.out.exists():
        earlier = json.loads(args.out.read_text(encoding="utf-8"))
        if earlier.get("date") == content["date"]:
            content["hours"] = earlier["hours"]          # hours assigned in an earlier run of the same date
    for h in args.hours:
        started = time.perf_counter()
        trips = weights.T @ (hours[h] * ~local) @ weights
        flow, seconds = assign(network, trips)
        content["hours"][str(h)] = {
            "vehicles": float(hours[h].sum()),
            "local_streets": float((hours[h] * local).sum()),
            "congestion_index": round(congestion_index(network, flow, seconds), 4),
            "segments": {network.segment[e]: [round(float(flow[e]), 1), round(float(seconds[e]), 2)]
                         for e in np.nonzero(flow)[0]},
        }
        print(f"{h:02d}:00 {hours[h].sum():>10,.0f} vehicles, congestion {content['hours'][str(h)]['congestion_index']:.2f}, "
              f"{time.perf_counter() - started:.0f} s", flush=True)
        args.out.write_text(json.dumps(content), encoding="utf-8")


if __name__ == "__main__":
    main()

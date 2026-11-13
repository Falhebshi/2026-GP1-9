"""
Score how much traffic each road segment is likely to carry.

The synthetic generator needs to know which roads are busy: the ring
roads and main corridors, not quiet roads on the edge of the city.
This script estimates it with weighted network centrality: trips are
sent from where people live to where they go, along the fastest roads,
and a segment's demand is the share of those trips that use it.
Centrality of this kind is shown to follow measured traffic volumes
closely (e.g. the Colombo AADT study, validation R^2 = 0.93; Lowry,
Journal of Transport Geography, 2014).

Inputs, all open data (data/raw/network/, not committed):

- road_segments.json and segment_mappings.json (segments.py);
- riyadh_population.csv: WorldPop population density, Saudi Arabia,
  1 km, 2020, UN-adjusted, ASCII XYZ (CC BY 4.0, WorldPop, University
  of Southampton, DOI 10.5258/SOTON/WP00675);
- riyadh_activities.osm.json: universities, colleges, schools,
  hospitals, clinics, malls, offices and commercial or retail areas in
  the city box (OpenStreetMap contributors, ODbL).

Method:

1. The segments form a directed road graph; a segment's travel time is
   its length at its free-flow speed.
2. Every populated 1 km cell is joined to its nearest road junction:
   trips start there, in proportion to the cell's population.
3. Every activity place is joined to its nearest road junction: trips
   end there, one share per place.
4. From each starting junction, the fastest routes to all junctions
   are found, and each destination gets population x activities
   trips; every segment on the route counts them.
5. A segment's demand is its count divided by the largest count, so
   0 is unused and 1 is the busiest segment.
6. The same is done the other way, from activity places back to
   homes, since evening trips run in the opposite direction: a road
   into a busy area carries the morning trips, the road out of it the
   evening ones.

Output: data/processed/network/segment_demand.json. It holds only
Jaadah segment IDs and scores from open data, no RCRC data, so it is
committed.
"""

import argparse
import csv
import heapq
import json
import math
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.segments import (
    CITY_BOX,
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    inside_box,
    line_length_m,
)

RAW_DIR = REPO_ROOT / "data/raw/network"
DEFAULT_POPULATION = RAW_DIR / "riyadh_population.csv"
DEFAULT_ACTIVITIES = RAW_DIR / "riyadh_activities.osm.json"
DEFAULT_SEGMENTS = DEFAULT_OUTPUT_DIR / "road_segments.json"
DEFAULT_MAPPINGS = DEFAULT_OUTPUT_DIR / "segment_mappings.json"
DEFAULT_DEMAND = DEFAULT_OUTPUT_DIR / "segment_demand.json"

# Size of the grid used to find the nearest junction quickly
GRID_DEGREES = 0.01


# ============================================================
# READING THE INPUTS
# ============================================================

def read_population(path: Path, box: tuple = CITY_BOX) -> list[tuple]:
    """
    Return the populated cells inside the box: (lon, lat, people).

    WorldPop's ASCII XYZ file has one line per 1 km cell: longitude,
    latitude and people per km2 (cells are about 1 km2, so the value
    is used as the cell's weight).
    """

    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found: download the WorldPop Saudi Arabia 1 km "
            "population density (ASCII XYZ) and save it there"
        )

    cells = []

    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.reader(file):
            try:
                lon, lat, people = (float(value) for value in row[:3])
            except ValueError:
                continue    # the header line

            if people > 0 and inside_box((lon, lat), box):
                cells.append((lon, lat, people))

    if not cells:
        raise ValueError(f"{path}: no populated cell inside the city box")

    return cells


def read_activities(path: Path, box: tuple = CITY_BOX) -> list[tuple]:
    """Return the activity places inside the box: (lon, lat)."""

    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found: export the activities query from "
            "overpass-turbo (raw OSM data) and save it there"
        )

    elements = json.loads(path.read_text(encoding="utf-8")).get("elements")

    if not elements:
        raise ValueError(f"{path}: no OpenStreetMap elements in the file")

    places = []

    for element in elements:
        # nodes have lon/lat; ways and relations have a center
        point = element if "lon" in element else element.get("center")

        if not point or not element.get("tags"):
            continue

        lon_lat = (point["lon"], point["lat"])

        if inside_box(lon_lat, box):
            places.append(lon_lat)

    if not places:
        raise ValueError(f"{path}: no activity place inside the city box")

    return places


# ============================================================
# ROAD GRAPH
# ============================================================

def road_graph(
    segments: list[RoadSegment],
    mappings: dict[str, dict],
) -> tuple[dict, dict]:
    """
    Return the road graph and the position of every junction.

    graph: junction -> [(next junction, travel time in s, segment)]
    positions: junction -> (lon, lat)
    """

    graph = defaultdict(list)
    positions = {}

    for segment in segments:
        mapping = mappings[segment.segment_id]
        start, end = mapping["from_node_id"], mapping["to_node_id"]
        seconds = (
            line_length_m(segment.geometry)
            / (segment.free_flow_speed_kmh / 3.6)
        )

        graph[start].append((end, seconds, segment.segment_id))
        positions[start] = segment.geometry[0]
        positions[end] = segment.geometry[-1]

    return graph, positions


class NearestJunction:
    """Find the junction nearest to a point, using a coarse grid."""

    def __init__(self, positions: dict):
        self.positions = positions
        self.cells = defaultdict(list)

        for junction, (lon, lat) in positions.items():
            self.cells[self.cell(lon, lat)].append(junction)

    @staticmethod
    def cell(lon: float, lat: float) -> tuple[int, int]:
        return int(lon // GRID_DEGREES), int(lat // GRID_DEGREES)

    def find(self, lon: float, lat: float):
        """Return the nearest junction, looking in growing rings."""

        x, y = self.cell(lon, lat)
        scale = math.cos(math.radians(lat))

        for ring in range(0, 50):
            candidates = [
                junction
                for dx in range(-ring, ring + 1)
                for dy in range(-ring, ring + 1)
                if max(abs(dx), abs(dy)) == ring
                for junction in self.cells.get((x + dx, y + dy), [])
            ]

            if candidates:
                # one more ring, so a closer junction just across the
                # cell edge is not missed
                candidates += [
                    junction
                    for dx in range(-ring - 1, ring + 2)
                    for dy in range(-ring - 1, ring + 2)
                    if max(abs(dx), abs(dy)) == ring + 1
                    for junction in self.cells.get((x + dx, y + dy), [])
                ]

                return min(
                    candidates,
                    key=lambda j: (
                        ((self.positions[j][0] - lon) * scale) ** 2
                        + (self.positions[j][1] - lat) ** 2
                    ),
                )

        return None


# ============================================================
# TRIPS AND DEMAND
# ============================================================

def fastest_routes(graph: dict, start) -> tuple[dict, list]:
    """
    Return the fastest-route tree from one junction (Dijkstra).

    previous: junction -> (junction before it, segment used)
    order: junctions in the order they were reached (nearest first)
    """

    best = {start: 0.0}
    previous = {}
    order = []
    queue = [(0.0, start)]
    done = set()

    while queue:
        seconds, junction = heapq.heappop(queue)

        if junction in done:
            continue

        done.add(junction)
        order.append(junction)

        for following, travel, segment_id in graph.get(junction, ()):
            arrival = seconds + travel

            if arrival < best.get(following, math.inf):
                best[following] = arrival
                previous[following] = (junction, segment_id)
                heapq.heappush(queue, (arrival, following))

    return previous, order


def segment_demand(
    graph: dict,
    origins: dict,
    destinations: dict,
) -> dict[str, float]:
    """
    Return every segment's demand, from 0 (unused) to 1 (busiest).

    origins and destinations: junction -> weight (population, places).
    From each origin, every reachable destination gets origin weight x
    destination weight trips, counted on each segment of its fastest
    route. Trips are added from the farthest junctions back to the
    origin, so every segment is counted once per origin.
    """

    counts = defaultdict(float)

    for origin, people in origins.items():
        previous, order = fastest_routes(graph, origin)
        arriving = {
            junction: people * destinations.get(junction, 0.0)
            for junction in order
        }

        for junction in reversed(order):
            if junction == origin or arriving[junction] == 0:
                continue

            before, segment_id = previous[junction]
            counts[segment_id] += arriving[junction]
            arriving[before] += arriving[junction]

    busiest = max(counts.values(), default=0.0)

    if busiest == 0:
        raise ValueError("no trip reached any destination")

    return {
        segment_id: count / busiest
        for segment_id, count in counts.items()
    }


def junction_weights(
    points: list[tuple],
    nearest: NearestJunction,
) -> dict:
    """Add up point weights on their nearest junctions."""

    weights = defaultdict(float)

    for point in points:
        lon, lat = point[0], point[1]
        weight = point[2] if len(point) > 2 else 1.0
        junction = nearest.find(lon, lat)

        if junction is not None:
            weights[junction] += weight

    return dict(weights)


# ============================================================
# COMMAND LINE
# ============================================================

def main() -> None:
    """Command line entry point."""

    parser = argparse.ArgumentParser(
        description="Score the travel demand of every road segment.",
    )
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--population", type=Path,
                        default=DEFAULT_POPULATION)
    parser.add_argument("--activities", type=Path,
                        default=DEFAULT_ACTIVITIES)
    parser.add_argument("--out", type=Path, default=DEFAULT_DEMAND)
    args = parser.parse_args()

    started = time.perf_counter()

    content = json.loads(args.segments.read_text(encoding="utf-8"))
    segments = [RoadSegment(**record) for record in content["segments"]]
    mappings = {
        record["segment_id"]: record
        for record in json.loads(
            args.mappings.read_text(encoding="utf-8")
        )["mappings"]
    }
    cells = read_population(args.population)
    places = read_activities(args.activities)

    graph, positions = road_graph(segments, mappings)
    nearest = NearestJunction(positions)
    origins = junction_weights(cells, nearest)
    destinations = junction_weights(places, nearest)

    print(f"{len(cells)} populated cells -> {len(origins)} junctions")
    print(f"{len(places)} activity places -> {len(destinations)} junctions")

    def rounded(demand):
        return {
            segment.segment_id: round(demand.get(segment.segment_id, 0.0), 5)
            for segment in segments
        }

    to_activities = rounded(segment_demand(graph, origins, destinations))
    to_homes = rounded(segment_demand(graph, destinations, origins))
    used = sum(
        1 for segment_id in to_activities
        if to_activities[segment_id] > 0 or to_homes[segment_id] > 0
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "source": {
                    "built": date.today().isoformat(),
                    "method": "weighted network centrality: population "
                              "to activity places, fastest routes",
                    "population": args.population.name,
                    "activities": args.activities.name,
                },
                # morning: homes to activities; evening: back home
                "to_activities": to_activities,
                "to_homes": to_homes,
            },
            indent=1,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"{used} of {len(segments)} segments carry trips")
    print(f"Written to {args.out} in "
          f"{time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()

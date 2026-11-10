"""
Cut Riyadh's main roads from an OpenStreetMap download into segments.

Network Overview colours every main road by congestion. A road in
OpenStreetMap (a "way") can run through many intersections and carry
both directions, so it is cut into segments: one direction of a road,
from one intersection or signal to the next.

Input: the Overpass download of motorway, trunk, primary and secondary
roads in the city box, with their points (data/raw/network/, not
committed; the query is in docs and the README).

Rules applied, and why:

- Cut points: a road is cut where it shares a point with another kept
  road (an intersection) and at every traffic signal, so each segment
  runs between two decision points.
- Direction: oneway=yes gives one segment along the road, oneway=-1 one
  against it, and anything else two segments, one per direction.
  Motorways and roundabouts are one-way unless tagged otherwise, as
  OpenStreetMap assumes.
- Lanes per direction: lanes on a one-way road, lanes:forward or
  lanes:backward on a two-way road, otherwise half of lanes. When
  nothing is tagged, the median of the same road class in this
  download is used.
- Names: name:en and name:ar, and name filled into whichever of the
  two it is written in. A road with no name keeps both empty; the
  website shows its road class instead.
- Speed limit: maxspeed in km/h (mph converted). When it is missing,
  the median of the same road class in this download is used, and
  only if a class has none, a default per class.
- Signal at the end: true when a traffic signal lies on the last 50 m
  of the segment, in its driving direction.
- Box: segments with no point inside the city box are dropped, and
  the parts of a segment that run outside the box at either end are
  trimmed.
- Identity: segments get stable IDs (SEG_00001 ...) in a fixed order
  (OSM way ID, position, direction). The OSM IDs are kept only in the
  mapping file, never in the segment records the website reads.

Output, in data/processed/network/:

- road_segments.json: the segments;
- segment_mappings.json: each segment's OSM way and end points.
"""

import argparse
import json
import math
import re
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT = REPO_ROOT / "data/raw/network/riyadh_roads.osm.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/processed/network"

ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary")

# The city box: west, south, east, north (CITY_BOUNDS in networkService.js)
CITY_BOX = (46.51, 24.51, 46.94, 25.0)

# Used only when no road of a class has a tagged speed limit
DEFAULT_SPEED_KMH = {
    "motorway": 120,
    "trunk": 100,
    "primary": 80,
    "secondary": 60,
}

SIGNAL_DISTANCE_M = 50
EARTH_RADIUS_M = 6_371_000


# ============================================================
# READING TAGS
# ============================================================

def parse_lanes(value: str | None) -> int | None:
    """Return a lane count from an OSM lanes tag, or None."""

    if value is None:
        return None

    match = re.match(r"\s*(\d+)", value)

    if not match or int(match.group(1)) < 1:
        return None

    return int(match.group(1))


def parse_speed(value: str | None) -> float | None:
    """Return a speed limit in km/h from an OSM maxspeed tag, or None."""

    if value is None:
        return None

    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph)?", value)

    if not match:
        return None

    speed = float(match.group(1))

    if match.group(2):
        speed *= 1.609344

    return speed if speed > 0 else None


def road_names(tags: dict) -> tuple[str | None, str | None]:
    """Return the English and Arabic names of a road, when tagged."""

    name = tags.get("name")
    name_en = tags.get("name:en")
    name_ar = tags.get("name:ar")

    if name and re.search(r"[؀-ۿ]", name):
        name_ar = name_ar or name
    elif name:
        name_en = name_en or name

    return name_en, name_ar


def directions(tags: dict) -> list[str]:
    """Return the driving directions of a road: forward and/or backward."""

    oneway = tags.get("oneway")

    if oneway in ("yes", "true", "1"):
        return ["forward"]

    if oneway == "-1":
        return ["backward"]

    # motorways and roundabouts are one-way unless tagged otherwise
    if oneway is None and (
        tags.get("highway") == "motorway"
        or tags.get("junction") in ("roundabout", "circular")
    ):
        return ["forward"]

    return ["forward", "backward"]


def lanes_in_direction(
    tags: dict,
    direction: str,
    one_way: bool,
) -> int | None:
    """Return the tagged lane count for one direction, or None."""

    if one_way:
        return parse_lanes(tags.get("lanes"))

    directed = parse_lanes(tags.get(f"lanes:{direction}"))

    if directed is not None:
        return directed

    total = parse_lanes(tags.get("lanes"))

    if total is None:
        return None

    return max(1, total // 2)


# ============================================================
# GEOMETRY
# ============================================================

def distance_m(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    """Return the distance in metres between two (lon, lat) points."""

    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)

    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )

    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def line_length_m(points: list[tuple[float, float]]) -> float:
    """Return the length in metres of a line of (lon, lat) points."""

    return sum(
        distance_m(points[index], points[index + 1])
        for index in range(len(points) - 1)
    )


def inside_box(point: tuple[float, float], box: tuple) -> bool:
    """Return True when a (lon, lat) point lies inside a box."""

    west, south, east, north = box

    return west <= point[0] <= east and south <= point[1] <= north


# ============================================================
# CUTTING
# ============================================================

def read_osm(path: Path) -> tuple[list[dict], dict[int, dict]]:
    """Return the kept roads and every point of an Overpass JSON file."""

    data = json.loads(path.read_text(encoding="utf-8"))
    elements = data.get("elements")

    if not elements:
        raise ValueError(f"{path}: no OpenStreetMap elements in the file")

    nodes = {
        element["id"]: element
        for element in elements
        if element["type"] == "node"
    }
    ways = [
        element
        for element in elements
        if element["type"] == "way"
        and element.get("tags", {}).get("highway") in ROAD_CLASSES
    ]

    missing = sum(
        1
        for way in ways
        for node_id in way["nodes"]
        if node_id not in nodes
    )

    if missing:
        raise ValueError(f"{path}: {missing} road points are missing")

    return ways, nodes


def cut_points(ways: list[dict], nodes: dict[int, dict]) -> set[int]:
    """Return the points where roads are cut: shared points and signals."""

    uses = Counter(node_id for way in ways for node_id in set(way["nodes"]))

    shared = {node_id for node_id, count in uses.items() if count > 1}
    signals = {
        node_id
        for node_id, node in nodes.items()
        if node.get("tags", {}).get("highway") == "traffic_signals"
    }

    return shared | signals


def split_way(node_ids: list[int], cuts: set[int]) -> list[list[int]]:
    """Split a road's points into pieces that end at cut points."""

    pieces = []
    current = [node_ids[0]]

    for node_id in node_ids[1:]:
        current.append(node_id)

        if node_id in cuts and node_id != node_ids[-1]:
            pieces.append(current)
            current = [node_id]

    pieces.append(current)

    return [piece for piece in pieces if len(piece) >= 2]


def signal_at_end(
    points: list[tuple[float, float]],
    node_ids: list[int],
    signal_ids: set[int],
) -> bool:
    """Return True when a signal lies on the last 50 m of a segment."""

    travelled = 0.0

    for index in range(len(node_ids) - 1, -1, -1):
        if node_ids[index] in signal_ids:
            return True

        if index == 0:
            break

        travelled += distance_m(points[index], points[index - 1])

        if travelled > SIGNAL_DISTANCE_M:
            break

    return False


def build_segments(
    ways: list[dict],
    nodes: dict[int, dict],
    box: tuple = CITY_BOX,
) -> tuple[list[dict], list[dict]]:
    """
    Cut the roads into directed segments.

    Returns the segment records and their OSM mapping records, in the
    same order. Lanes and speed limits that are not tagged are left as
    None here and filled by fill_defaults.
    """

    cuts = cut_points(ways, nodes)
    signal_ids = {
        node_id
        for node_id, node in nodes.items()
        if node.get("tags", {}).get("highway") == "traffic_signals"
    }

    drafts = []

    for way in sorted(ways, key=lambda item: item["id"]):
        tags = way.get("tags", {})
        way_directions = directions(tags)
        one_way = len(way_directions) == 1
        name_en, name_ar = road_names(tags)
        speed = parse_speed(tags.get("maxspeed"))

        for position, piece in enumerate(split_way(way["nodes"], cuts)):
            for direction in way_directions:
                node_ids = piece if direction == "forward" else piece[::-1]
                points = [
                    (nodes[node_id]["lon"], nodes[node_id]["lat"])
                    for node_id in node_ids
                ]

                inside = [
                    index
                    for index, point in enumerate(points)
                    if inside_box(point, box)
                ]

                if not inside:
                    continue

                # trim the parts that run outside the box at either end
                first, last = inside[0], inside[-1]

                if first == last:
                    first, last = max(first - 1, 0), min(
                        last + 1,
                        len(points) - 1,
                    )

                node_ids = node_ids[first:last + 1]
                points = points[first:last + 1]

                drafts.append(
                    {
                        "osm_way_id": way["id"],
                        "position": position,
                        "direction": direction,
                        "node_ids": node_ids,
                        "points": points,
                        "road_class": tags["highway"],
                        "name_en": name_en,
                        "name_ar": name_ar,
                        "lane_count": lanes_in_direction(
                            tags,
                            direction,
                            one_way,
                        ),
                        "free_flow_speed_kmh": speed,
                        "signal_at_end": signal_at_end(
                            points,
                            node_ids,
                            signal_ids,
                        ),
                    }
                )

    segments = []
    mappings = []

    for number, draft in enumerate(drafts, start=1):
        segment_id = f"SEG_{number:05d}"

        segments.append(
            {
                "segment_id": segment_id,
                "name_en": draft["name_en"],
                "name_ar": draft["name_ar"],
                "road_class": draft["road_class"],
                "lane_count": draft["lane_count"],
                "free_flow_speed_kmh": draft["free_flow_speed_kmh"],
                "signal_at_end": draft["signal_at_end"],
                "geometry": [
                    [round(lon, 6), round(lat, 6)]
                    for lon, lat in draft["points"]
                ],
            }
        )
        mappings.append(
            {
                "segment_id": segment_id,
                "osm_way_id": draft["osm_way_id"],
                "direction": draft["direction"],
                "from_node_id": draft["node_ids"][0],
                "to_node_id": draft["node_ids"][-1],
            }
        )

    return segments, mappings


def fill_defaults(segments: list[dict]) -> dict:
    """
    Fill untagged lanes, speeds and names in place.

    Lanes and speeds use the median of the same road class among the
    tagged segments; a class with no tagged speed uses
    DEFAULT_SPEED_KMH. Returns how many values were tagged and filled,
    for the report.
    """

    counts = {
        "lanes_tagged": 0,
        "lanes_filled": 0,
        "speed_tagged": 0,
        "speed_filled": 0,
        "unnamed": 0,
    }
    medians = {}

    for road_class in ROAD_CLASSES:
        of_class = [s for s in segments if s["road_class"] == road_class]
        lanes = [s["lane_count"] for s in of_class if s["lane_count"]]
        speeds = [
            s["free_flow_speed_kmh"]
            for s in of_class
            if s["free_flow_speed_kmh"]
        ]
        medians[road_class] = (
            round(statistics.median(lanes)) if lanes else 1,
            statistics.median(speeds)
            if speeds
            else DEFAULT_SPEED_KMH[road_class],
        )

    for segment in segments:
        median_lanes, median_speed = medians[segment["road_class"]]

        if segment["lane_count"] is None:
            segment["lane_count"] = median_lanes
            counts["lanes_filled"] += 1
        else:
            counts["lanes_tagged"] += 1

        if segment["free_flow_speed_kmh"] is None:
            segment["free_flow_speed_kmh"] = median_speed
            counts["speed_filled"] += 1
        else:
            counts["speed_tagged"] += 1

        segment["free_flow_speed_kmh"] = round(
            segment["free_flow_speed_kmh"],
            1,
        )

        if not segment["name_en"] and not segment["name_ar"]:
            counts["unnamed"] += 1

    counts["medians"] = medians

    return counts


# ============================================================
# WRITING AND REPORT
# ============================================================

def write_json(path: Path, content: dict) -> None:
    """Write JSON with UTF-8 and "\\n" line endings."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, ensure_ascii=False, indent=1) + "\n"
    path.write_bytes(text.encode("utf-8"))


def segment_box(segments: list[dict]) -> tuple[float, float, float, float]:
    """Return the west, south, east, north box of all segments."""

    lons = [point[0] for s in segments for point in s["geometry"]]
    lats = [point[1] for s in segments for point in s["geometry"]]

    return min(lons), min(lats), max(lons), max(lats)


def report(segments: list[dict], counts: dict) -> str:
    """Return a short text report of the segments."""

    by_class = Counter(segment["road_class"] for segment in segments)
    length_km = {
        road_class: sum(
            line_length_m(
                [tuple(point) for point in segment["geometry"]]
            )
            for segment in segments
            if segment["road_class"] == road_class
        ) / 1000
        for road_class in ROAD_CLASSES
    }
    west, south, east, north = segment_box(segments)
    total = len(segments)

    lines = [
        f"Segments: {total}",
        "",
        "By road class (segments, km of directed road):",
    ]

    for road_class in ROAD_CLASSES:
        lines.append(
            f"  {road_class:<10} {by_class[road_class]:>6}"
            f"   {length_km[road_class]:>8.1f} km"
        )

    lines += [
        "",
        f"Lanes:  {counts['lanes_tagged']} from OSM, "
        f"{counts['lanes_filled']} filled with the class median",
        f"Speed:  {counts['speed_tagged']} from OSM, "
        f"{counts['speed_filled']} filled with the class median",
        f"Names:  {counts['unnamed']} without any name",
        f"Ending at a signal: "
        f"{sum(segment['signal_at_end'] for segment in segments)}",
        "",
        "Class medians used for filling (lanes, km/h):",
    ]

    for road_class, (lanes, speed) in counts["medians"].items():
        lines.append(f"  {road_class:<10} {lanes} lanes, {speed:g} km/h")

    lines += [
        "",
        f"Box of the segments (west, south, east, north): "
        f"[{west:.4f}, {south:.4f}], [{east:.4f}, {north:.4f}]",
    ]

    return "\n".join(lines)


def main() -> None:
    """Command line entry point."""

    parser = argparse.ArgumentParser(
        description="Cut the OSM main roads into road segments.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="Overpass JSON download of the main roads",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="folder for road_segments.json and segment_mappings.json",
    )
    args = parser.parse_args()

    ways, nodes = read_osm(args.input)
    segments, mappings = build_segments(ways, nodes)
    counts = fill_defaults(segments)

    source = {
        "input": args.input.name,
        "built": date.today().isoformat(),
        "city_box": list(CITY_BOX),
    }

    write_json(
        args.out / "road_segments.json",
        {"source": source, "segments": segments},
    )
    write_json(
        args.out / "segment_mappings.json",
        {"source": source, "mappings": mappings},
    )

    print(report(segments, counts))
    print(f"\nWritten to {args.out}")


if __name__ == "__main__":
    main()

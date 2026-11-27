"""
Build the trip model's zones: where people live and where they go.

The synthetic traffic of the wider network starts from trips between
zones (Macro Map Synthetic Data Methodology, step 1). Each zone is a
square of about 2 km (ZONE_DEGREES) holding:

- its population: WorldPop, the same 1 km grid as demand.py, added
  up over the zone;
- its attraction for each trip purpose, in vehicle trips arriving on a
  weekday. Every place is measured by its own size measure and turned
  into trips with the trip rate for its land use (TRIP_RATES), so
  floor area, students, beds and passengers are never added directly:
  - the major activity centres use their published size measures
    (activity_centres.csv: source, date, evidence type, confidence);
  - every other OpenStreetMap activity place shares what is left of
    the city's published total for its land use (CONTROL_TOTALS), in
    proportion to its kind's relative size (PLACE_TYPICAL): OSM decides
    where a land use is, the published total how much there is;
  - school trips follow population (SCHOOL_STUDENTS_PER_PERSON), since
    OSM maps only part of Riyadh's schools;
  - industrial centres are measured in workers, turned into commuting
    cars (work_vehicles); their company buses are counted apart;
- OSM features that are one place (a hospital mapped as a point and an
  outline, a mall complex mapped building by building, a campus mapped
  college by college) are merged first (merge_places), so each place
  counts once;
- the attraction of seasonal places (Riyadh Season), kept apart so the
  trip model can use it only in season;
- its centre: the population-weighted centre, or the centre of its
  places when nobody lives there.

Inputs, all open data: the WorldPop population and the OSM activities
file (data/raw/network/, not committed, as for demand.py) and
activity_centres.csv (committed).

Output: data/processed/network/zones.json. It holds only open data and
project assumptions, no RCRC data, so it is committed.

    python -m jaadah.network_congestion.zones
"""

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from jaadah.network_congestion.demand import (
    DEFAULT_ACTIVITIES,
    DEFAULT_POPULATION,
    read_population,
)
from jaadah.network_congestion.parameters import (
    ACTIVITY_CENTRES_FILE,
    AIRPORT,
    ARRIVING_SHARE,
    CAR_SHARE,
    CONTROL_TOTALS,
    EMPLOYMENT_CASE,
    EMPLOYMENT_CASES,
    EMPLOYMENT_CHECK,
    INDUSTRY_WORKER_MIX,
    MERGE_THRESHOLDS_M,
    PLACE_TYPICAL,
    POINT_IN_OUTLINE_EXCEPT,
    POINT_IN_OUTLINE_M,
    PURPOSES,
    SCHOOL_STUDENTS_PER_PERSON,
    SHOPPING_820_CURVE,
    TRIP_RATES,
    VISITOR_PEOPLE_PER_CAR,
    ZONE_DEGREES,
)
from jaadah.network_congestion.segments import (
    CITY_BOX,
    DEFAULT_OUTPUT_DIR,
    inside_box,
)

DEFAULT_ZONES = DEFAULT_OUTPUT_DIR / "zones.json"
DEFAULT_CENTRES = DEFAULT_OUTPUT_DIR / ACTIVITY_CENTRES_FILE

SQ_FT_PER_M2 = 10.7639


# ============================================================
# FROM SIZE TO TRIPS
# ============================================================

def daily_trip_ends(rate: str, value: float, unit: str) -> float:
    """
    Daily vehicle trip ends (arriving and leaving) of a place, from its
    size measure and the trip rate of its land use.
    """

    if rate == "shopping_820":
        slope, intercept = SHOPPING_820_CURVE
        thousand_sq_ft = value * SQ_FT_PER_M2 / 1000
        return math.exp(slope * math.log(thousand_sq_ft) + intercept)

    if rate in ("airport_passengers", "airport_employees"):
        # trip ends are twice the vehicles arriving
        arriving = airport_arriving_vehicles(
            value if rate == "airport_passengers" else 0.0,
            value if rate == "airport_employees" else 0.0,
        )
        return 2 * sum(arriving.values())

    if rate == "industry_workers":
        cars, _buses = industry_vehicles(value)
        return 2 * cars

    if rate == "visitor_trips":
        # each visit is one trip there and one trip back
        return value * CAR_SHARE / VISITOR_PEOPLE_PER_CAR * 2

    per_unit, rate_unit, _source = TRIP_RATES[rate]

    if rate_unit == "1000 sq ft":
        if unit != "m2":
            raise ValueError(f"{rate} needs a floor area in m2, not {unit}")
        return per_unit * value * SQ_FT_PER_M2 / 1000

    return per_unit * value


def airport_arriving_vehicles(
    passengers_per_day: float,
    employees: float,
    params: dict = AIRPORT,
) -> dict[str, float]:
    """
    Vehicles arriving at the airport on a weekday, by origin of the trip.

    passengers_per_day counts arrivals and departures together, so each
    passenger is counted once: half the origin-destination passengers
    depart and half arrive. Every departing road passenger's vehicle
    arrives at the airport; an arriving passenger's vehicle arrives to
    pick them up, unless they parked there when they left, since that
    car arrived on the way out. Other vehicles (freight, service, crew)
    are a share of the passenger and employee vehicles.
    """

    road = passengers_per_day * (1 - params["transfer_share"]) * params["road_share"]
    departing = road / 2 / params["passengers_per_vehicle"]
    picking_up = road / 2 * (1 - params["park_share"]) / params["passengers_per_vehicle"]
    staff = employees * params["employees_on_site"] * CAR_SHARE / params["employees_per_vehicle"]
    other = (departing + picking_up + staff) * params["other_vehicle_share"]

    return {
        "departing passengers": departing,
        "picking up arriving passengers": picking_up,
        "employees": staff,
        "freight, service and other": other,
    }


def work_vehicles(
    saudi: float,
    non_saudi: float,
    case: str = EMPLOYMENT_CASE,
    skilled_share: float | None = None,
) -> tuple[float, float]:
    """
    Cars and company buses arriving on a weekday for these workers: after
    attendance, how each group travels and how many share a vehicle.
    Buses are counted apart, never as cars.
    """

    c = EMPLOYMENT_CASES[case]
    skilled = c["skilled_share"] if skilled_share is None else skilled_share
    present = c["attendance"]

    cars = saudi * present * c["saudi_by_car"] / c["saudi_per_car"]
    cars += non_saudi * skilled * present * c["skilled_by_car"] / c["skilled_per_car"]
    other = non_saudi * (1 - skilled) * present * (1 - c["on_site"])
    cars += other * c["other_by_car"] / c["other_per_car"]

    return cars, other * c["other_by_bus"] / c["per_bus"]


def industry_vehicles(workers: float, case: str = EMPLOYMENT_CASE) -> tuple[float, float]:
    """Cars and company buses arriving at an industrial centre."""

    return work_vehicles(
        workers * INDUSTRY_WORKER_MIX["saudi"],
        workers * (1 - INDUSTRY_WORKER_MIX["saudi"]),
        case,
        INDUSTRY_WORKER_MIX["skilled_share"],
    )


def arriving_trips(rate: str, value: float, unit: str, purposes: dict[str, float]) -> dict:
    """Weekday vehicle trips arriving at a place, by purpose."""

    total = daily_trip_ends(rate, value, unit) * ARRIVING_SHARE

    return {purpose: total * share for purpose, share in purposes.items()}


# ============================================================
# ACTIVITY PLACES AND CENTRES
# ============================================================

def place_kind(tags: dict) -> str | None:
    """Return the kind of an OSM activity place, or None."""

    amenity = tags.get("amenity")
    healthcare = tags.get("healthcare")
    office = tags.get("office")

    if amenity == "university":
        return "university"

    if amenity == "college" or office == "educational_institution":
        return "college"

    if amenity == "school" or tags.get("building") == "school":
        return "school"

    if amenity == "hospital" or healthcare == "hospital":
        return "hospital"

    if amenity == "clinic" or healthcare == "clinic":
        return "clinic"

    if tags.get("shop") == "mall":
        return "mall"

    if amenity == "marketplace":
        return "marketplace"

    if office == "government" or "government" in tags:
        return "government_office"

    if office == "diplomatic":
        return "diplomatic"

    if office or tags.get("building") == "commercial":
        return "office"

    landuse = tags.get("landuse")

    if landuse == "retail":
        return "retail_area"

    if landuse == "commercial":
        return "commercial_area"

    return None


def read_places(path: Path, box: tuple = CITY_BOX) -> list[tuple]:
    """
    Return the activity places inside the box: (lon, lat, kind,
    "type/id", names), names being its name tags (name, name:en, name:ar).
    """

    if not path.exists():
        raise FileNotFoundError(f"{path} not found: see demand.py for how to export it")

    places = []

    for element in json.loads(path.read_text(encoding="utf-8")).get("elements", []):
        # nodes have lon/lat; ways and relations have a center
        point = element if "lon" in element else element.get("center")
        kind = place_kind(element.get("tags", {}))

        if point and kind and inside_box((point["lon"], point["lat"]), box):
            tags = element.get("tags", {})
            places.append((
                point["lon"], point["lat"], kind, f"{element['type']}/{element['id']}",
                tuple(tags[k] for k in ("name", "name:en", "name:ar") if tags.get(k)),
            ))

    if not places:
        raise ValueError(f"{path}: no activity place of a known kind inside the city box")

    return places


@dataclass(frozen=True)
class CentreComponent:
    """One part of a major centre (for example its mall or its offices)."""

    centre: str
    component: str
    lon: float
    lat: float
    osm_element: str
    rate: str
    value: float
    unit: str
    purposes: dict[str, float]
    seasonal: bool
    campus_kinds: frozenset = frozenset()
    campus_radius_m: float = 0.0


def parse_purposes(text: str) -> dict[str, float]:
    """Read "private_work:0.9;shopping_leisure:0.1"."""

    shares = {}

    for part in text.split(";"):
        purpose, share = part.split(":")
        if purpose not in PURPOSES:
            raise ValueError(f"unknown purpose {purpose}")
        shares[purpose] = float(share)

    if abs(sum(shares.values()) - 1) > 1e-6:
        raise ValueError(f"purpose shares must add up to 1: {text}")

    return shares


def read_centres(path: Path = DEFAULT_CENTRES) -> list[CentreComponent]:
    """
    Read the major activity centres and their size measures; rows still
    waiting for a verified location (status pending_location) are left
    out.
    """

    with path.open(encoding="utf-8", newline="") as file:
        return [
            CentreComponent(
                centre=row["centre"],
                component=row["component"],
                lon=float(row["lon"]),
                lat=float(row["lat"]),
                osm_element=row["osm_element"],
                rate=row["rate"],
                value=float(row["value"]),
                unit=row["unit"],
                purposes=parse_purposes(row["purposes"]),
                seasonal=row["season"] != "all",
                campus_kinds=frozenset(k for k in row["campus_kinds"].split(";") if k),
                campus_radius_m=float(row["campus_radius_m"] or 0),
            )
            for row in csv.DictReader(file)
            if row["status"] == "active"
        ]


# ============================================================
# MERGING FEATURES THAT ARE ONE PLACE
# ============================================================

def place_names(place: tuple) -> tuple:
    return place[4] if len(place) > 4 else ()


def metres(a: tuple, b: tuple) -> float:
    """Approximate distance in metres between two (lon, lat, ...) points in Riyadh."""

    return math.hypot((a[0] - b[0]) * 101_000, (a[1] - b[1]) * 111_000)


def normal_name(text: str) -> str:
    """A name without case, punctuation, Arabic diacritics, "Dr" or "The"."""

    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[\u064b-\u0652]", "", text)
    text = re.sub(r"\b(dr|the)\b|[^\w\s-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def names_match(first: tuple, second: tuple) -> bool:
    """
    Whether two lists of names are the same place: equal, one containing
    the other, or the same complex name before " - ".
    """

    for a in map(normal_name, first):
        for b in map(normal_name, second):
            if a == b:
                return True
            if len(a) > 5 and len(b) > 5 and (a in b or b in a):
                return True
            base_a = re.split(r"\s[-\u2013]\s", a)[0].strip()
            base_b = re.split(r"\s[-\u2013]\s", b)[0].strip()
            if len(base_a) > 5 and base_a == base_b:
                return True

    return False


def merge_places(places: list[tuple], centres: list) -> list[tuple]:
    """
    Return the places with features that are one place merged, keeping
    the named feature (Macro Map attraction research, section 7):

    - campus parts: places of a major centre's campus kinds within its
      campus radius belong to the centre;
    - same place: same kind, within MERGE_THRESHOLDS_M, and names
      compatible (matching, or one unnamed within the unnamed
      threshold). Two unrelated names never end up in one group;
    - point inside outline: a point and an outline of the same kind
      within POINT_IN_OUTLINE_M, whatever their names.
    """

    by_id = {p[3]: p for p in places}
    parent = {p[3]: p[3] for p in places}
    named = {p[3]: [p] if place_names(p) else [] for p in places}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(keep, drop):
        keep, drop = root(keep), root(drop)
        if keep != drop:
            parent[drop] = keep
            named[keep] += named.pop(drop)

    def groups_compatible(a, b):
        return all(
            names_match(place_names(x), place_names(y))
            for x in named[root(a)] for y in named[root(b)]
        )

    for centre in centres:
        head = by_id.get(centre.osm_element)
        if head is None or not centre.campus_kinds:
            continue
        for place in places:
            if (place[3] != head[3] and place[2] in centre.campus_kinds
                    and metres(place, head) <= centre.campus_radius_m):
                join(head[3], place[3])

    for kind, (named_limit, unnamed_limit) in MERGE_THRESHOLDS_M.items():
        group = [p for p in places if p[2] == kind]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                distance = metres(a, b)
                if distance > named_limit or root(a[3]) == root(b[3]):
                    continue

                both_named = bool(place_names(a)) and bool(place_names(b))
                types = {a[3].split("/")[0], b[3].split("/")[0]}
                point_in_outline = (
                    kind not in POINT_IN_OUTLINE_EXCEPT
                    and distance <= POINT_IN_OUTLINE_M
                    and "node" in types and len(types) == 2
                )
                same_place = (
                    (both_named and names_match(place_names(a), place_names(b)))
                    or (not both_named and distance <= unnamed_limit)
                ) and groups_compatible(a[3], b[3])

                if same_place or point_in_outline:
                    keep, drop = (a, b) if place_names(a) or not place_names(b) else (b, a)
                    join(keep[3], drop[3])

    return [p for p in places if root(p[3]) == p[3]]


# ============================================================
# TYPICAL SIZES FROM THE CONTROL TOTALS
# ============================================================

CENTRE_CATEGORY = {
    "office_710": "office_floor_area",
    "shopping_820": "retail_area",
    "university_540_550": "university_students",
    "hospital_610": "hospital_beds",
}


def typical_sizes(
    places: list[tuple],
    centres: list,
    totals: dict = CONTROL_TOTALS,
) -> dict[str, float]:
    """
    Return the typical size of each OSM place kind.

    For a category with a published total, the OSM places of that
    category (not replaced by a major centre) share the total minus the
    major centres' sizes, in proportion to their kinds' relative sizes.
    Other kinds keep their relative size.
    """

    replaced = {c.osm_element for c in centres if c.osm_element}
    counts = defaultdict(int)

    for place in places:
        kind, element = place[2], place[3]
        if kind in PLACE_TYPICAL and element not in replaced:
            counts[kind] += 1

    sizes = {kind: float(spec[1]) for kind, spec in PLACE_TYPICAL.items()}

    for category, (total, _unit, _source) in totals.items():
        named = sum(
            c.value for c in centres
            if CENTRE_CATEGORY.get(c.rate) == category
        )
        kinds = [k for k, spec in PLACE_TYPICAL.items() if spec[3] == category]
        relative = sum(counts[k] * PLACE_TYPICAL[k][1] for k in kinds)

        if relative == 0:
            continue

        if named >= total:
            raise ValueError(f"major centres alone exceed the {category} total")

        scale = (total - named) / relative

        for kind in kinds:
            sizes[kind] = PLACE_TYPICAL[kind][1] * scale

    return sizes


# ============================================================
# ZONES
# ============================================================

@dataclass
class Zone:
    """One zone: its centre, population and attraction by purpose."""

    zone_id: str
    lon: float
    lat: float
    population: float = 0.0
    attraction: dict[str, float] = field(default_factory=dict)
    seasonal_attraction: dict[str, float] = field(default_factory=dict)


def zone_key(lon: float, lat: float) -> tuple[int, int]:
    """Return the zone square a point falls in."""

    return math.floor(lon / ZONE_DEGREES), math.floor(lat / ZONE_DEGREES)


def build_zones(
    cells: list[tuple],
    places: list[tuple],
    centres: list[CentreComponent],
    totals: dict = CONTROL_TOTALS,
) -> list[Zone]:
    """
    Return every zone with people or activity places.

    cells: (lon, lat, people); places: (lon, lat, kind, "type/id",
    names), merged first (merge_places); centres: the major centres'
    components.
    """

    people = defaultdict(float)
    weighted = defaultdict(lambda: [0.0, 0.0])
    points = defaultdict(list)
    attraction = defaultdict(lambda: dict.fromkeys(PURPOSES, 0.0))
    seasonal = defaultdict(lambda: dict.fromkeys(PURPOSES, 0.0))
    replaced = {c.osm_element for c in centres if c.osm_element}

    for lon, lat, count in cells:
        key = zone_key(lon, lat)
        people[key] += count
        weighted[key][0] += lon * count
        weighted[key][1] += lat * count

    places = merge_places(places, centres)
    sizes = typical_sizes(places, centres, totals)

    for lon, lat, count in cells:
        key = zone_key(lon, lat)
        attraction[key]["school"] += sum(arriving_trips(
            "school_520_525", count * SCHOOL_STUDENTS_PER_PERSON, "students", {"school": 1.0},
        ).values())

    for place in places:
        lon, lat, kind, element = place[:4]
        if element in replaced or kind not in PLACE_TYPICAL:
            continue

        key = zone_key(lon, lat)
        points[key].append((lon, lat))
        rate, _relative, unit, _category, purposes = PLACE_TYPICAL[kind]

        for purpose, trips in arriving_trips(rate, sizes[kind], unit, purposes).items():
            attraction[key][purpose] += trips

    for centre in centres:
        key = zone_key(centre.lon, centre.lat)
        points[key].append((centre.lon, centre.lat))
        target = seasonal if centre.seasonal else attraction

        for purpose, trips in arriving_trips(
            centre.rate, centre.value, centre.unit, centre.purposes,
        ).items():
            target[key][purpose] += trips

    zones = []

    for key in sorted(set(people) | set(points)):
        if people[key] > 0:
            lon = weighted[key][0] / people[key]
            lat = weighted[key][1] / people[key]
        else:
            lon = sum(p[0] for p in points[key]) / len(points[key])
            lat = sum(p[1] for p in points[key]) / len(points[key])

        zones.append(Zone(
            zone_id=f"Z{key[0]}_{key[1]}",
            lon=round(lon, 5),
            lat=round(lat, 5),
            population=round(people[key], 1),
            attraction={p: round(v, 1) for p, v in attraction[key].items()},
            seasonal_attraction={p: round(v, 1) for p, v in seasonal[key].items()},
        ))

    return zones


def write_zones(path: Path, zones: list[Zone]) -> None:
    """Write the zones and where their values come from."""

    content = {
        "source": {
            "built": date.today().isoformat(),
            "population": "WorldPop 1 km (CC BY 4.0)",
            "places": "OpenStreetMap contributors (ODbL)",
            "centres": f"{ACTIVITY_CENTRES_FILE} (published size measures, sources listed there)",
            "attraction": "weekday vehicle trips arriving, from ITE 11th ed. rates (TRIP_RATES in parameters.py)",
            "control_totals": {k: v[2] for k, v in CONTROL_TOTALS.items()},
            "zone_degrees": ZONE_DEGREES,
        },
        "zones": [asdict(zone) for zone in zones],
    }
    path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")


def report(zones: list[Zone]) -> str:
    """A short summary for the command line."""

    lines = [f"{len(zones)} zones, population {sum(z.population for z in zones):,.0f}"]

    for purpose in PURPOSES:
        total = sum(z.attraction[purpose] for z in zones)
        top = sorted(zones, key=lambda z: z.attraction[purpose], reverse=True)[:3]
        lines.append(
            f"  {purpose}: {total:,.0f} trips; top zones "
            + ", ".join(f"{z.zone_id} ({z.attraction[purpose]:,.0f})" for z in top)
        )

    for purpose, (low, high) in EMPLOYMENT_CHECK.items():
        total = sum(z.attraction[purpose] for z in zones)
        lines.append(
            f"  {purpose} against employment: {total:,.0f} of {low:,.0f} to {high:,.0f} commuting cars"
        )

    in_season = sum(sum(z.seasonal_attraction.values()) for z in zones)
    lines.append(f"  seasonal (October to March): {in_season:,.0f} trips")

    return "\n".join(lines)


def main() -> None:
    """Command line entry point."""

    parser = argparse.ArgumentParser(description="Build the trip model's zones.")
    parser.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    parser.add_argument("--activities", type=Path, default=DEFAULT_ACTIVITIES)
    parser.add_argument("--centres", type=Path, default=DEFAULT_CENTRES)
    parser.add_argument("--output", type=Path, default=DEFAULT_ZONES)
    args = parser.parse_args()

    zones = build_zones(
        read_population(args.population),
        read_places(args.activities),
        read_centres(args.centres),
    )
    write_zones(args.output, zones)
    print(report(zones))
    print(f"written {args.output}")


if __name__ == "__main__":
    main()

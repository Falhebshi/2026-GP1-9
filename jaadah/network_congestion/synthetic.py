"""
Generate synthetic congestion for every road segment.

Network Overview needs a congestion level for every segment every 15
minutes. There is no measured data for the whole city, so it is
synthetic, built from three sources:

- how congested Riyadh is at each hour of each day of the week: the
  TomTom Traffic Index (time for a 10 km drive, 2025, in
  parameters.py);
- which roads are worse than others: demand.py's weighted network
  centrality (trips from WorldPop population to OpenStreetMap activity
  places along the fastest routes, homes to activities in the morning
  and back in the evening);
- how much the delay differs between roads, how much it varies every
  15 minutes and how much of that carries into the next: the RCRC
  sample (one week at one site), measured each time the script runs.

Congestion is expressed as speed, the way TomTom measures it and the
HCM grades urban streets (travel speed as a share of free-flow speed).

For every segment and 15 minutes:

    city delay  = TomTom travel time / free-flow travel time - 1
    delay       = city delay x corridor factor x (1 + variation)
    speed ratio = 1 / (1 + delay)

A corridor is one road in one direction (same name and class, going
with or against the road's main line; an unnamed piece joins the named
road it continues, otherwise it keeps its OSM way); its segments share
the factor and the variation, so congestion covers a stretch of road. The
corridor factor follows its demand ranking: the highest-demand
corridor gets the largest factor, the lowest the smallest, spread as
the peak v/c of the sample's approaches is (highest / lowest), with an
average of 1 so the city average stays TomTom's.

The values measured from the RCRC sample stay private: they are used
in memory and never written to the repository or printed.

The network map server (server.py) uses these functions: its producer
works out each completed 15 minutes with interval_speeds and stores it.
"""

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.parameters import (
    BASE_SATURATION_FLOW_VEH_H_LN,
    EVENING_DEMAND_FROM_HOUR,
    GREEN_SHARE_MAIN,
    GREEN_SHARE_SIDE,
    INTERVAL_S,
    INTERVALS_PER_DAY,
    MORNING_DEMAND_UNTIL_HOUR,
    SEED,
    TOMTOM_FREE_FLOW_10KM_S,
    TOMTOM_HOURS,
    TOMTOM_TRAVEL_TIME_10KM_S,
    segment_capacity,
)
from jaadah.network_congestion.segments import (
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    line_length_m,
)

DEFAULT_SEGMENTS = DEFAULT_OUTPUT_DIR / "road_segments.json"
DEFAULT_MAPPINGS = DEFAULT_OUTPUT_DIR / "segment_mappings.json"
DEFAULT_DEMAND = DEFAULT_OUTPUT_DIR / "segment_demand.json"
PROFILE_DIR = REPO_ROOT.parent / "jaadah-private-data/processed/rcrc_sample"
DEFAULT_DETECTOR_PROFILE = PROFILE_DIR / "detector_time_of_day_profile.csv"
DEFAULT_SUMMARY = PROFILE_DIR / "rcrc_profile_summary.json"

# RCRC direction codes (P2-WB-L1-L-STB: cars travelling west)
RCRC_DIRECTIONS = {"NB": "N", "EB": "E", "SB": "S", "WB": "W"}
SLOTS_PER_HOUR = 3600 // INTERVAL_S


# ============================================================
# WHAT IS MEASURED FROM THE RCRC SAMPLE
# ============================================================

@dataclass(frozen=True)
class SampleMeasures:
    """
    Everything taken from the RCRC sample, measured in memory.

    peak_vc_range: lowest and highest peak v/c of the approaches; their
      ratio sets how much more the busiest corridor is delayed than the
      quietest.
    variation_sd: how much a 15-minute count varies around its
      average for that time (standard deviation / mean).
    persistence: how much of one interval's variation carries into
      the next (lag-1 correlation after removing the daily pattern).
    """

    peak_vc_range: tuple[float, float]
    variation_sd: float
    persistence: float


@dataclass(frozen=True)
class Direction:
    """One direction of the sample site, from its detectors."""

    volumes: list[float]   # workday mean, all lanes, per slot
    lanes: int             # detectors (one per lane at the stop bar)
    sd_sum: float          # sum of the slots' standard deviations
    mean_sum: float        # sum of the slots' mean volumes


def read_directions(path: Path) -> dict[str, Direction]:
    """Return the sample's directions, adding up their detectors."""

    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run analysis/rcrc_sample/"
            "rcrc_sample_analysis.py first, or pass --detector-profile."
        )

    volumes, detectors, sd_sums, mean_sums = {}, {}, {}, {}

    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            parts = row["description"].split("-")
            code = parts[1].strip() if len(parts) > 1 else ""
            heading_code = RCRC_DIRECTIONS.get(code)
            slot = int(row["slot_index"])

            if heading_code is None or not 0 <= slot < INTERVALS_PER_DAY:
                continue

            mean = float(row["mean_volume"])
            series = volumes.setdefault(
                heading_code,
                [0.0] * INTERVALS_PER_DAY,
            )
            series[slot] += mean
            detectors.setdefault(heading_code, set()).add(row["detector_id"])

            if row.get("std_volume"):
                sd_sums[heading_code] = (
                    sd_sums.get(heading_code, 0.0) + float(row["std_volume"])
                )
                mean_sums[heading_code] = (
                    mean_sums.get(heading_code, 0.0) + mean
                )

    if not volumes:
        raise ValueError(f"{path}: no NB, EB, SB or WB detectors")

    return {
        heading_code: Direction(
            volumes=volumes[heading_code],
            lanes=len(detectors[heading_code]),
            sd_sum=sd_sums.get(heading_code, 0.0),
            mean_sum=mean_sums.get(heading_code, 0.0),
        )
        for heading_code in volumes
    }


def read_persistence(path: Path) -> float:
    """Return Aliyah's measured lag-1 correlation, kept in [0, 0.95]."""

    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run analysis/rcrc_sample/"
            "rcrc_sample_analysis.py first, or pass --summary."
        )

    summary = json.loads(path.read_text(encoding="utf-8"))
    value = summary["temporal_persistence"]["mean_adjusted_lag1_correlation"]

    # a negative or near-1 correlation would not describe traffic that
    # rises and falls smoothly; keep it in a usable range
    return max(0.0, min(0.95, float(value)))


def peak_vc_range(directions: dict[str, Direction]) -> tuple[float, float]:
    """
    Return the lowest and highest peak v/c of the sample's approaches.

    Peak v/c = busiest 15 minutes x 4 / capacity, with capacity = lanes
    x base saturation flow x green share. The axis (north-south or
    east-west) carrying more traffic at its peak is the main road.
    """

    def axis_peak(codes):
        return sum(
            max(directions[code].volumes)
            for code in codes
            if code in directions
        )

    east_west = axis_peak("EW") >= axis_peak("NS")
    main_axis = ("E", "W") if east_west else ("N", "S")
    values = []

    for code, direction in directions.items():
        share = GREEN_SHARE_MAIN if code in main_axis else GREEN_SHARE_SIDE
        capacity = direction.lanes * BASE_SATURATION_FLOW_VEH_H_LN * share
        hourly = max(direction.volumes) * 3600 / INTERVAL_S

        if capacity > 0 and hourly > 0:
            values.append(hourly / capacity)

    if not values:
        raise ValueError("no approach with traffic and lanes in the sample")

    return min(values), max(values)


def variation_sd(directions: dict[str, Direction]) -> float:
    """
    Return how much a 15-minute count varies around its average.

    The volume-weighted coefficient of variation of the detectors:
    the sum of the slots' standard deviations over the sum of their
    means, so quiet night slots do not dominate.
    """

    sd_sum = sum(direction.sd_sum for direction in directions.values())
    mean_sum = sum(direction.mean_sum for direction in directions.values())

    if mean_sum <= 0:
        raise ValueError("the detector profile has no std_volume values")

    return sd_sum / mean_sum


def measure_sample(detector_profile: Path, summary: Path) -> SampleMeasures:
    """Read the two private files and return what is used from them."""

    directions = read_directions(detector_profile)

    return SampleMeasures(
        peak_vc_range=peak_vc_range(directions),
        variation_sd=variation_sd(directions),
        persistence=read_persistence(summary),
    )


# ============================================================
# CITY DELAY BY HOUR (TomTom)
# ============================================================

def city_delay(day: date) -> list[float]:
    """
    Return the city's delay for every 15 minutes of a day.

    Delay = TomTom travel time / free-flow travel time - 1, read at
    00:00, 02:00 ... 22:00 for that day of the week and joined by
    straight lines in between; after 22:00 it runs to 00:00 of the next
    day.
    """

    today = TOMTOM_TRAVEL_TIME_10KM_S[day.weekday()]
    tomorrow = TOMTOM_TRAVEL_TIME_10KM_S[(day.weekday() + 1) % 7]
    hours = list(TOMTOM_HOURS) + [24]
    seconds = list(today) + [tomorrow[0]]
    delays = []

    for slot in range(INTERVALS_PER_DAY):
        hour = slot / SLOTS_PER_HOUR
        index = max(i for i, h in enumerate(hours[:-1]) if h <= hour)
        share = (hour - hours[index]) / (hours[index + 1] - hours[index])
        travel = seconds[index] + share * (seconds[index + 1] - seconds[index])
        delays.append(travel / TOMTOM_FREE_FLOW_10KM_S - 1)

    return delays


def evening_share(slot: int) -> float:
    """Return how much of a slot's traffic is evening (homeward) trips."""

    hour = slot / SLOTS_PER_HOUR

    if hour < MORNING_DEMAND_UNTIL_HOUR:
        return 0.0

    if hour >= EVENING_DEMAND_FROM_HOUR:
        return 1.0

    return (hour - MORNING_DEMAND_UNTIL_HOUR) / (
        EVENING_DEMAND_FROM_HOUR - MORNING_DEMAND_UNTIL_HOUR
    )


# ============================================================
# CORRIDORS
# ============================================================

def seeded_random(*parts) -> random.Random:
    """Return a random generator fixed by the seed and the given parts."""

    key = ":".join(str(part) for part in (SEED, *parts))
    digest = hashlib.sha256(key.encode("utf-8")).digest()

    return random.Random(int.from_bytes(digest[:8], "big"))


def bearing(segment: RoadSegment) -> float:
    """Return the segment's overall direction in degrees from north."""

    (lon1, lat1), (lon2, lat2) = segment.geometry[0], segment.geometry[-1]
    east = (lon2 - lon1) * math.cos(math.radians(lat1))

    return math.degrees(math.atan2(east, lat2 - lat1)) % 360


def road_key(segment: RoadSegment, osm_way_id: int) -> str:
    """Return the road of a segment: its name (or OSM way) and class."""

    name = segment.name_en or segment.name_ar
    road = name if name else f"way {osm_way_id}"

    return f"{road}|{segment.road_class.value}"


def road_axes(
    segments: list[RoadSegment],
    roads: dict[str, str],
) -> dict[str, float]:
    """
    Return every road's main line in degrees (0 to 180): the
    length-weighted mean of its segments' directions, taken as lines,
    so that the two directions of a two-way road add up instead of
    cancelling.
    """

    sums = {}

    for segment in segments:
        angle = math.radians(2 * bearing(segment))
        length = line_length_m(segment.geometry)
        x, y = sums.get(roads[segment.segment_id], (0.0, 0.0))
        sums[roads[segment.segment_id]] = (
            x + length * math.cos(angle), y + length * math.sin(angle),
        )

    return {
        road: math.degrees(math.atan2(y, x)) / 2 % 180
        for road, (x, y) in sums.items()
    }


def along(segment_bearing: float, axis: float) -> str:
    """Whether a direction goes with the road's main line or against it."""

    return "with" if math.cos(math.radians(segment_bearing - axis)) >= 0 else "against"


def same_way(first: float, second: float) -> bool:
    """Whether two directions are within 45 degrees of each other."""

    return math.cos(math.radians(first - second)) > math.cos(math.radians(45))


def segment_corridors(
    segments: list[RoadSegment],
    way_ids: dict[str, int],
) -> dict[str, str]:
    """
    Return every segment's corridor: its road in one direction.

    The direction is taken from the road itself, not from the compass:
    each road gets a main line (road_axes) and a segment goes with it
    or against it. A road that runs diagonally, such as one at 45
    degrees, so stays one corridor in each direction.

    Some OSM ways of a named road have no name. Such a segment joins
    the corridor of the named road it continues: a segment of the same
    class that ends where it starts or starts where it ends. First only
    roads going its way (within 45 degrees) are joined, so a run of
    pieces follows its own road. Then, if it touches more than one
    road, it joins the one its traffic comes from (a U-turn), or else
    the one it leads into (out of a junction). If that still leaves
    more than one or none, it keeps its own OSM way as corridor.
    """

    roads = {
        segment.segment_id: road_key(segment, way_ids[segment.segment_id])
        for segment in segments
    }
    axes = road_axes(segments, roads)
    bearings = {segment.segment_id: bearing(segment) for segment in segments}
    corridors = {
        segment.segment_id: (
            f"{roads[segment.segment_id]}|"
            f"{along(bearings[segment.segment_id], axes[roads[segment.segment_id]])}"
        )
        for segment in segments
    }
    named = {
        segment.segment_id for segment in segments
        if segment.name_en or segment.name_ar
    }

    # the direction of each named corridor, to compare a piece with
    direction = {}
    for segment in segments:
        if segment.segment_id in named:
            angle = math.radians(bearings[segment.segment_id])
            length = line_length_m(segment.geometry)
            x, y = direction.get(corridors[segment.segment_id], (0.0, 0.0))
            direction[corridors[segment.segment_id]] = (
                x + length * math.sin(angle), y + length * math.cos(angle),
            )
    direction = {
        corridor: math.degrees(math.atan2(x, y)) % 360
        for corridor, (x, y) in direction.items()
    }

    starting, ending = {}, {}
    for segment in segments:
        starting.setdefault(tuple(segment.geometry[0]), []).append(segment)
        ending.setdefault(tuple(segment.geometry[-1]), []).append(segment)

    def named_roads(pieces, road_class):
        """The corridors of the named pieces of this class."""

        return {
            corridors[other.segment_id] for other in pieces
            if other.segment_id in named and other.road_class == road_class
        }

    def join(segment, fall_back: bool) -> str | None:
        before = named_roads(
            ending.get(tuple(segment.geometry[0]), []), segment.road_class,
        )
        after = named_roads(
            starting.get(tuple(segment.geometry[-1]), []), segment.road_class,
        )
        choice = {
            road for road in before | after
            if same_way(bearings[segment.segment_id], direction[road])
        }

        if fall_back:
            # a U-turn or crossover between the two directions of a road
            # goes neither way: it joins the road its traffic comes from
            if len(choice) != 1 and len(before) == 1:
                choice = before

            # coming from a junction: it joins the road it leads into
            if len(choice) != 1 and len(after) == 1:
                choice = after

        return choice.pop() if len(choice) == 1 else None

    # repeated so a run of unnamed pieces takes the name from its ends
    for fall_back in (False, True):
        changed = True
        while changed:
            changed = False

            for segment in segments:
                if segment.segment_id in named:
                    continue

                corridor = join(segment, fall_back)

                if corridor is not None:
                    corridors[segment.segment_id] = corridor
                    named.add(segment.segment_id)
                    changed = True

    return corridors


def corridor_ranks(
    segments: list[RoadSegment],
    corridors: dict[str, str],
    demand: dict[str, float],
) -> dict[str, float]:
    """
    Return every corridor's place in the demand ranking, 0 to 1.

    A corridor's demand is the length-weighted mean of its segments'
    demand. The lowest corridor gets 0, the highest 1, and the others
    are spread evenly by their position (ties share a place).
    """

    totals, lengths = {}, {}

    for segment in segments:
        corridor = corridors[segment.segment_id]
        length = line_length_m(segment.geometry)
        totals[corridor] = (
            totals.get(corridor, 0.0)
            + demand.get(segment.segment_id, 0.0) * length
        )
        lengths[corridor] = lengths.get(corridor, 0.0) + length

    scores = {
        corridor: totals[corridor] / lengths[corridor]
        if lengths[corridor] > 0 else 0.0
        for corridor in totals
    }
    distinct = sorted(set(scores.values()))

    if len(distinct) == 1:
        return {corridor: 0.5 for corridor in scores}

    place = {score: index / (len(distinct) - 1)
             for index, score in enumerate(distinct)}

    return {corridor: place[score] for corridor, score in scores.items()}


def corridor_factor(rank: float, measures: SampleMeasures) -> float:
    """
    Return how much of the city delay a corridor gets.

    The factor runs from low / mid to high / mid of the sample's peak
    v/c range (mid = its middle), so the busiest corridor is delayed
    high / low times as much as the quietest and the average is 1.
    """

    low, high = measures.peak_vc_range
    middle = (low + high) / 2

    return (low + (high - low) * rank) / middle


def corridor_variation(
    corridor: str,
    day: date,
    measures: SampleMeasures,
) -> list[float]:
    """
    Return a corridor's 96 variations for one day.

    Each interval keeps part of the previous one (the measured
    persistence) and adds a new random part, so the variation has the
    measured spread and rises and falls smoothly.
    """

    rng = seeded_random("variation", corridor, day.isoformat())
    carry = measures.persistence
    fresh_sd = measures.variation_sd * (1 - carry ** 2) ** 0.5

    value = rng.gauss(0, measures.variation_sd)
    values = [value]

    for _ in range(INTERVALS_PER_DAY - 1):
        value = carry * value + rng.gauss(0, fresh_sd)
        values.append(value)

    return values


def slot_speed(
    city_delay_now: float,
    morning_factor: float,
    evening_factor: float,
    variation_now: float,
    slot: int,
) -> int:
    """Return a segment's speed in one slot, in percent of free flow."""

    evening = evening_share(slot)
    factor = (1 - evening) * morning_factor + evening * evening_factor
    delay = max(0.0, city_delay_now * factor * (1 + variation_now))

    return round(100 / (1 + delay))


# ============================================================
# ROAD LINES FOR THE MAP
# ============================================================

def segments_geojson(
    segments: list[RoadSegment],
    capacities: dict[str, float],
    source: str = "synthetic",
) -> dict:
    """Return the segments as GeoJSON lines, with where their speeds come from."""

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [round(lon, 5), round(lat, 5)]
                        for lon, lat in segment.geometry
                    ],
                },
                "properties": {
                    "id": segment.segment_id,
                    "name_en": segment.name_en,
                    "name_ar": segment.name_ar,
                    "road_class": segment.road_class.value,
                    "is_link": segment.is_link,
                    "lanes": segment.lane_count,
                    "capacity_veh_h": round(capacities[segment.segment_id]),
                    "source": source,
                },
            }
            for segment in segments
        ],
    }


# ============================================================
# THE CITY, LOADED ONCE (for the network map server)
# ============================================================

@dataclass(frozen=True)
class City:
    """Everything needed to work out any segment's speed at any time."""

    segments: list[RoadSegment]
    capacities: dict[str, float]
    corridors: dict[str, str]                 # segment ID -> corridor
    factors: dict[str, tuple[float, float]]   # corridor -> (morning, evening)
    measures: SampleMeasures


@dataclass(frozen=True)
class CityDay:
    """The parts of one day shared by all its 15-minute intervals."""

    day: date
    delays: list[float]                       # city delay, per slot
    variations: dict[str, list[float]]        # corridor -> 96 variations


def load_city(
    segments_path: Path = DEFAULT_SEGMENTS,
    mappings_path: Path = DEFAULT_MAPPINGS,
    demand_path: Path = DEFAULT_DEMAND,
    detector_profile: Path = DEFAULT_DETECTOR_PROFILE,
    summary: Path = DEFAULT_SUMMARY,
) -> City:
    """Read the segments, the demand and the private RCRC measures."""

    # measured values are RCRC-derived: used in memory, never printed
    measures = measure_sample(detector_profile, summary)

    content = json.loads(segments_path.read_text(encoding="utf-8"))
    segments = [RoadSegment(**record) for record in content["segments"]]
    mappings = json.loads(mappings_path.read_text(encoding="utf-8"))
    way_ids = {
        record["segment_id"]: record["osm_way_id"]
        for record in mappings["mappings"]
    }
    corridors = segment_corridors(segments, way_ids)

    if not demand_path.exists():
        raise FileNotFoundError(
            f"{demand_path} not found: run "
            "python -m jaadah.network_congestion.demand first"
        )

    demand = json.loads(demand_path.read_text(encoding="utf-8"))
    morning_demand = demand["to_activities"]
    evening_demand = demand["to_homes"]
    missing = [
        s.segment_id for s in segments if s.segment_id not in morning_demand
    ]

    if missing:
        raise ValueError(
            f"{len(missing)} segments have no demand score: run demand.py "
            "again after segments.py"
        )

    morning_ranks = corridor_ranks(segments, corridors, morning_demand)
    evening_ranks = corridor_ranks(segments, corridors, evening_demand)

    return City(
        segments=segments,
        capacities={
            segment.segment_id: segment_capacity(segment)
            for segment in segments
        },
        corridors=corridors,
        factors={
            corridor: (
                corridor_factor(morning_ranks[corridor], measures),
                corridor_factor(evening_ranks[corridor], measures),
            )
            for corridor in morning_ranks
        },
        measures=measures,
    )


def city_day(city: City, day: date) -> CityDay:
    """Return the city delay and every corridor's variation for a day."""

    return CityDay(
        day=day,
        delays=city_delay(day),
        variations={
            corridor: corridor_variation(corridor, day, city.measures)
            for corridor in set(city.corridors.values())
        },
    )


def interval_speeds(
    city: City,
    today: CityDay,
    slot: int,
) -> tuple[list[int], float]:
    """
    Return every segment's speed in one slot, and the network speed.

    The speeds are in the order of city.segments; the network speed is
    their mean, for the timeline.
    """

    speeds = []

    for segment in city.segments:
        corridor = city.corridors[segment.segment_id]
        morning, evening = city.factors[corridor]
        speeds.append(slot_speed(
            today.delays[slot], morning, evening,
            today.variations[corridor][slot], slot,
        ))

    return speeds, round(sum(speeds) / len(speeds), 1)

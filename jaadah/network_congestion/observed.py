"""
Road congestion for every segment, from the city's congestion and the
traffic observed at the study intersection.

Network Overview needs a congestion level for every road segment every
15 minutes, but traffic is counted at one intersection only. One
intersection cannot set the congestion of the whole city: in the
summer holidays the study intersection has almost no morning peak,
while the city still has one. So each source sets what it can:

1. How congested the city is in each 15 minutes: TomTom's average time
   for a 10 km drive in Riyadh, by day of the week and hour
   (parameters.py), over the time the same drive takes on the map's
   roads at their free-flow speeds (tomtom_travel_index). TomTom
   measures it from drivers' trips over the whole road network, over a
   whole year. TomTom's own congestion level compares each hour with
   Riyadh at night, when drivers already go slower than the roads'
   free-flow speeds (signals, junctions); the map's speed levels
   compare with the free-flow speed, so the travel time is the
   comparable measure.
2. Whether today is busier or quieter than usual: the study
   intersection's HCM critical volume-to-capacity ratio (from the
   observed demand, calculated by the KPI engine,
   backend/analytics/kpi/capacity.py) over its usual ratio for the same
   day of the week and 15 minutes, averaged over the day so far
   (day_factors). TomTom's congestion is scaled by this one factor for
   the day, within DAY_FACTOR_LIMITS, so one intersection cannot turn
   the whole city green or red, nor reorder TomTom's pattern within the
   day: Riyadh's evening (15:00 to 19:00) stays busier than its morning,
   as TomTom measures it. This is calibration to TomTom, not a
   measurement of the roads.
3. Which roads are worse than others. Roads are ranked by their hourly
   v/c in the trip model (assignment.py, segment_hourly_vc.json), the
   ranks of one hour blended into the next over its 15-minute slots; when
   that file is missing, by their load in the earlier demand model
   (demand.py, segment_demand.json): trips over capacity. A segment's
   v/c follows how its corridor ranks against the intersection's:

       v/c = level x exp(spread x (corridor rank - site rank))

   with the level chosen in each 15 minutes so that the network's
   travel-time index (weighted by vehicle-kilometres, as TomTom weights
   it by drivers' trips) equals TomTom's congestion times the day
   factor.
4. Speed: the BPR function (Bureau of Public Roads, 1964) turns a v/c
   ratio into travel time, and so into speed as a share of free flow:

       speed ratio = 1 / (1 + 0.15 x (v/c)^4)

The spread (how much busier busy roads are than quiet ones) is a stated
value (NETWORK_SPREAD in parameters.py): a city average cannot set it,
and approach_spread, which measures it from the four approaches of the
intersection, sets it only weakly.

Sections 1 to 4 below hold the parts, also used to check the method on
the counts (fit_level, evaluate); section 5 is what the map server uses,
through producer.py. The observed counts come from the traffic source
through ingestion and demand building (backend/ingestion,
backend/demand), so missing counts and movements without detectors are
treated exactly as for the simulation.
"""

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.analytics.kpi.capacity import CapacityResults, calculate_capacity
from backend.analytics.kpi.lane_groups import LaneGroup, derive_lane_groups
from jaadah.kpi_inputs.network_inputs import build_network_inputs
from jaadah.kpi_inputs.signal_program import build_signal_program
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import KpiStatus
from jaadah.models.network import ApproachLane, Movement, MovementAttributes
from jaadah.models.network_congestion import RoadSegment
from jaadah.models.signals import SignalProgram
from jaadah.models.traffic import SimulationDemand
from jaadah.network_congestion.parameters import (
    DAY_FACTOR_LIMITS,
    TIMELINE_SLOWEST_SHARE,
    TOMTOM_CONGESTION_LEVEL_PERCENT,
    TOMTOM_HOURS,
    TOMTOM_TRAVEL_TIME_10KM_S,
    segment_capacity,
)
from jaadah.network_congestion.segments import REPO_ROOT, line_length_m
from jaadah.network_congestion.synthetic import (
    DEFAULT_DEMAND,
    DEFAULT_MAPPINGS,
    DEFAULT_SEGMENTS,
    corridor_ranks,
    evening_share,
    segment_corridors,
)

DEFAULT_MAPPING_PATH = (
    REPO_ROOT / "data" / "processed" / "road_network" / "network_mappings.json"
)
DEFAULT_NETWORK_PATH = (
    REPO_ROOT / "data" / "processed" / "road_network" / "jaadah_study_area.net.xml"
)
# Each segment's v/c for every hour in the trip model (assignment.py),
# on a term Wednesday for Sunday to Thursday and on a term Friday for
# Friday and Saturday; without them, roads are ranked from
# segment_demand.json (and the weekday file serves every day without the
# weekend one)
DEFAULT_HOURLY_VC = DEFAULT_DEMAND.parent / "segment_hourly_vc.json"
DEFAULT_WEEKEND_HOURLY_VC = DEFAULT_DEMAND.parent / "segment_hourly_vc_friday.json"
WEEKEND_DAYS = (4, 5)       # Friday and Saturday, as date.weekday()
# The study intersection's centre, from the same record the website uses
INTERSECTIONS_PATH = REPO_ROOT / "frontend" / "public" / "data" / "intersections.json"

# BPR volume-delay function (Bureau of Public Roads, Traffic Assignment
# Manual, 1964): travel time = free-flow time x (1 + a x (v/c)^b)
BPR_ALPHA = 0.15
BPR_BETA = 4

# The highest v/c used. The BPR function has no upper limit, and at 3
# a road already runs at 8 % of its free-flow speed.
MAX_VOLUME_TO_CAPACITY = 3.0

# Segments ending at a signal this close to the intersection centre
# are the intersection's own approaches
SITE_RADIUS_M = 120

# The spread needs at least this many approaches with a ratio
MIN_SPREAD_APPROACHES = 3

# Where the level is searched, and how finely
LEVEL_SEARCH = (0.1, 5.0)
LEVEL_TOLERANCE = 0.001

# The levels of the index table (index_table): 400 steps, closer
# together at low levels, up to where every road is at the v/c limit
LEVEL_TABLE = np.geomspace(0.01, 20.0, 400)

INTERVALS_PER_HOUR = 4


# ============================================================
# 1. HOW FULL THE STUDY INTERSECTION IS
# ============================================================

@dataclass(frozen=True)
class SiteInputs:
    """The study intersection's lanes, movements and signal program."""

    groups: list[LaneGroup]
    lanes_by_id: dict[str, ApproachLane]
    movements: dict[str, Movement]
    attributes: dict[str, MovementAttributes]
    program: SignalProgram


def load_site_inputs(
    mapping_path: Path = DEFAULT_MAPPING_PATH,
    network_path: Path = DEFAULT_NETWORK_PATH,
) -> SiteInputs:
    """Read the intersection's lanes and signal program, as the KPI engine does."""

    config = load_network_mappings(mapping_path)
    network = build_network_inputs(config)
    program = build_signal_program(
        config, network_path,
        scenario_id="SCN_NETWORK_MAP", signal_program_id="SP_NETWORK_MAP",
    )

    return SiteInputs(
        groups=derive_lane_groups(network.lanes, list(network.movement_attributes.values())),
        lanes_by_id={lane.lane_id: lane for lane in network.lanes},
        movements=network.movements,
        attributes=network.movement_attributes,
        program=program,
    )


def site_capacity(site: SiteInputs, demand_veh_h: dict[str, float]) -> CapacityResults:
    """The KPI engine's HCM capacity results for one interval."""

    return calculate_capacity(
        site.groups, site.lanes_by_id, site.movements, site.attributes,
        site.program, demand_veh_h,
    )


def site_volume_to_capacity(
    site: SiteInputs,
    demand_veh_h: dict[str, float],
) -> float | None:
    """
    The intersection's HCM critical v/c in one interval, or None when
    the KPI engine cannot calculate it (for example a movement without
    demand).
    """

    return site_capacity(site, demand_veh_h).critical_volume_to_capacity


def approach_volume_to_capacity(
    site: SiteInputs,
    result: CapacityResults,
) -> dict[str, float]:
    """
    How full each approach is in one interval: the highest v/c of its
    lane groups, as for the critical lane group of an approach.
    """

    by_approach: dict[str, float] = {}

    for group in site.groups:
        capacity = result.lane_groups.get(group.lane_group_id)

        if capacity is None or capacity.status != KpiStatus.OK:
            continue

        by_approach[group.approach_id] = max(
            by_approach.get(group.approach_id, 0.0), capacity.volume_to_capacity,
        )

    return by_approach


def hourly_flows(
    site: SiteInputs,
    demands: list[SimulationDemand],
) -> dict[datetime, dict[str, float]]:
    """Each interval's movement demand in veh/h (counts per 15 minutes x 4)."""

    by_interval: dict[datetime, dict[str, float]] = defaultdict(dict)

    for demand in demands:
        if demand.movement_id in site.attributes:
            by_interval[demand.interval_start][demand.movement_id] = (
                demand.vehicle_count * INTERVALS_PER_HOUR
            )

    return dict(sorted(by_interval.items()))


def site_levels(
    site: SiteInputs,
    demands: list[SimulationDemand],
) -> dict[datetime, float | None]:
    """The intersection's critical v/c in every interval that has demand."""

    return {
        start: site_volume_to_capacity(site, flows)
        for start, flows in hourly_flows(site, demands).items()
    }


# ============================================================
# 2. HOW FULL EVERY OTHER ROAD IS
# ============================================================

def segment_loads(
    segments: list[RoadSegment],
    demand: dict[str, float],
    capacities: dict[str, float],
) -> dict[str, float]:
    """Each segment's trips in the demand model over its capacity."""

    return {
        s.segment_id: demand.get(s.segment_id, 0.0) / capacities[s.segment_id]
        for s in segments
    }


def distance_m(point: list[float], centre: tuple[float, float]) -> float:
    """Distance in metres between a [lon, lat] point and a (lon, lat) centre."""

    lon, lat = centre
    dx = (point[0] - lon) * 111_320 * math.cos(math.radians(lat))
    dy = (point[1] - lat) * 110_540

    return math.hypot(dx, dy)


def site_segments(
    segments: list[RoadSegment],
    centre: tuple[float, float],
    radius_m: float = SITE_RADIUS_M,
) -> list[RoadSegment]:
    """The segments that end at the intersection's signal."""

    return [
        segment for segment in segments
        if segment.signal_at_end and distance_m(segment.geometry[-1], centre) <= radius_m
    ]


def site_rank(
    segments: list[RoadSegment],
    corridors: dict[str, str],
    ranks: dict[str, float],
) -> float:
    """The length-weighted rank of the given segments' corridors."""

    if not segments:
        raise ValueError("no segment ends at the study intersection")

    lengths = [line_length_m(segment.geometry) for segment in segments]
    total = sum(
        ranks[corridors[segment.segment_id]] * length
        for segment, length in zip(segments, lengths)
    )

    return total / sum(lengths)


def approach_ways(mapping_path: Path = DEFAULT_MAPPING_PATH) -> dict[int, str]:
    """
    The OSM way of each approach's lanes, from the network mappings.

    SUMO names its edges after the OSM ways they were built from
    ("713369663#2" is part of way 713369663), so the mapped SUMO lanes
    of an approach tell which OSM ways arrive on it. The approach is
    not guessed from the compass: the intersection does not face north.
    """

    config = load_network_mappings(mapping_path)
    approach_of_lane = {lane.lane_id: lane.approach_id for lane in config.approach_lanes}
    ways: dict[int, str] = {}

    for lane in config.lane_mappings:
        for sumo_lane_id in lane.sumo_lane_ids:
            edge_id = sumo_lane_id.rsplit("_", 1)[0]
            way_id = int(re.match(r"-?(\d+)", edge_id).group(1))
            ways[way_id] = approach_of_lane[lane.lane_id]

    return ways


def approach_ranks(
    segments: list[RoadSegment],
    corridors: dict[str, str],
    ranks: dict[str, float],
    way_ids: dict[str, int],
    ways: dict[int, str],
) -> dict[str, float]:
    """
    The rank of each approach, from the intersection's segments on its
    OSM ways (approach_ways).
    """

    by_approach: dict[str, list[RoadSegment]] = defaultdict(list)

    for segment in segments:
        approach_id = ways.get(way_ids[segment.segment_id])

        if approach_id is not None:
            by_approach[approach_id].append(segment)

    return {
        approach_id: site_rank(arriving, corridors, ranks)
        for approach_id, arriving in by_approach.items()
    }


def rank_offsets(
    segments: list[RoadSegment],
    corridors: dict[str, str],
    ranks: dict[str, float],
    site: float,
) -> np.ndarray:
    """Every segment's corridor rank minus the intersection's rank."""

    return np.array([ranks[corridors[s.segment_id]] - site for s in segments])


def approach_spread(
    approach_ratios: dict[str, float],
    ranks: dict[str, float],
) -> float | None:
    """
    The spread measured at the intersection: the slope of log(v/c)
    against rank across its approaches (least squares). approach_ratios
    are the approaches' average v/c; ranks their rank in the demand
    model. None when fewer than MIN_SPREAD_APPROACHES approaches have
    both, when their ranks are all equal, or when the busier-ranked
    approaches are not fuller (a slope of zero or less), so that the
    caller falls back to a stated assumption.
    """

    common = [
        a for a in approach_ratios
        if a in ranks and approach_ratios[a] > 0
    ]

    if len(common) < MIN_SPREAD_APPROACHES:
        return None

    x = np.array([ranks[a] for a in common])
    y = np.log([approach_ratios[a] for a in common])

    if np.ptp(x) == 0:
        return None

    slope = float(np.polyfit(x, y, 1)[0])

    return slope if slope > 0 else None


def segment_volume_to_capacity(
    site_level: float,
    offsets: np.ndarray,
    spread: float,
    level: float = 1.0,
) -> np.ndarray:
    """Every segment's v/c from the intersection's v/c and the rank offsets."""

    return np.minimum(
        level * site_level * np.exp(spread * offsets), MAX_VOLUME_TO_CAPACITY,
    )


# ============================================================
# 3. SPEED
# ============================================================

def bpr_travel_ratio(volume_to_capacity: np.ndarray) -> np.ndarray:
    """Travel time over free-flow time (BPR)."""

    return 1 + BPR_ALPHA * np.power(volume_to_capacity, BPR_BETA)


def speed_percent(volume_to_capacity: np.ndarray) -> np.ndarray:
    """Speed in percent of free flow, rounded to whole percent."""

    return np.rint(100 / bpr_travel_ratio(volume_to_capacity)).astype(int)


# ============================================================
# 4. THE LEVEL, FITTED TO TOMTOM, AND THE TEST
# ============================================================

def tomtom_index(day: date) -> list[float]:
    """
    TomTom's travel-time index (1 + congestion level) for every
    15 minutes of a day. The level is given every 2 hours for each day
    of the week; the values in between are joined by straight lines,
    and after 22:00 the line runs to 00:00 of the next day.
    """

    today = TOMTOM_CONGESTION_LEVEL_PERCENT[day.weekday()]
    tomorrow = TOMTOM_CONGESTION_LEVEL_PERCENT[(day.weekday() + 1) % 7]
    hours = list(TOMTOM_HOURS) + [24]
    levels = list(today) + [tomorrow[0]]
    index = []

    for slot in range(24 * INTERVALS_PER_HOUR):
        hour = slot / INTERVALS_PER_HOUR
        i = max(k for k, h in enumerate(hours[:-1]) if h <= hour)
        share = (hour - hours[i]) / (hours[i + 1] - hours[i])
        level = levels[i] + share * (levels[i + 1] - levels[i])
        index.append(1 + level / 100)

    return index


def tomtom_travel_index(day: date, free_flow_10km_s: float) -> list[float]:
    """
    TomTom's time for a 10 km drive in every 15 minutes of a day over the
    free-flow time of the same drive on the map's roads. TomTom gives it
    every 2 hours for each day of the week; the values in between are
    joined by straight lines, and after 22:00 the line runs to 00:00 of
    the next day.
    """

    today = TOMTOM_TRAVEL_TIME_10KM_S[day.weekday()]
    tomorrow = TOMTOM_TRAVEL_TIME_10KM_S[(day.weekday() + 1) % 7]
    hours = list(TOMTOM_HOURS) + [24]
    times = list(today) + [tomorrow[0]]
    index = []

    for slot in range(24 * INTERVALS_PER_HOUR):
        hour = slot / INTERVALS_PER_HOUR
        i = max(k for k, h in enumerate(hours[:-1]) if h <= hour)
        share = (hour - hours[i]) / (hours[i + 1] - hours[i])
        seconds = times[i] + share * (times[i + 1] - times[i])
        index.append(seconds / free_flow_10km_s)

    return index


def free_flow_10km_s(segments: list[RoadSegment], capacities: np.ndarray, lengths: np.ndarray) -> float:
    """
    Seconds for 10 km at the map roads' free-flow speeds, each road
    weighted by capacity x length as in the travel-time index.
    """

    speeds = np.array([s.free_flow_speed_kmh for s in segments], dtype=float)
    weights = capacities * lengths

    return 10.0 / (weights.sum() / (weights / speeds).sum()) * 3600


@dataclass(frozen=True)
class CalibrationSample:
    """One interval: its time, the intersection's v/c, the offsets and TomTom's index."""

    moment: datetime
    site_level: float
    offsets: np.ndarray
    tomtom_index: float


def travel_time_index(
    volume_to_capacity: np.ndarray,
    capacities: np.ndarray,
    lengths: np.ndarray,
) -> float:
    """
    The city's travel time over free-flow time, weighted by
    vehicle-kilometres (v/c x capacity x length), so that busy roads
    count as much as the trips on them, as in TomTom's index.
    """

    weights = volume_to_capacity * capacities * lengths
    total = weights.sum()

    if total <= 0:
        return 1.0

    return float((weights * bpr_travel_ratio(volume_to_capacity)).sum() / total)


def model_indices(
    samples: list[CalibrationSample],
    spread: float,
    level: float,
    capacities: np.ndarray,
    lengths: np.ndarray,
) -> np.ndarray:
    """The model's travel-time index in each sample."""

    return np.array([
        travel_time_index(
            segment_volume_to_capacity(s.site_level, s.offsets, spread, level),
            capacities, lengths,
        )
        for s in samples
    ])


def split_by_week(
    samples: list[CalibrationSample],
) -> tuple[list[CalibrationSample], list[CalibrationSample]]:
    """Samples of even ISO weeks (to fit) and of odd ISO weeks (to test)."""

    fit = [s for s in samples if s.moment.isocalendar().week % 2 == 0]
    test = [s for s in samples if s.moment.isocalendar().week % 2 == 1]

    return fit, test


def fit_level(
    samples: list[CalibrationSample],
    spread: float,
    capacities: np.ndarray,
    lengths: np.ndarray,
    search: tuple[float, float] = LEVEL_SEARCH,
    tolerance: float = LEVEL_TOLERANCE,
) -> float:
    """
    The level that brings the model's index closest to TomTom's on the
    given samples (least squares, golden-section search; the model's
    index rises with the level, so the error has one minimum).
    """

    if not samples:
        raise ValueError("at least one calibration sample is needed")

    target = np.array([s.tomtom_index for s in samples])

    def error(level: float) -> float:
        model = model_indices(samples, spread, level, capacities, lengths)
        return float(np.mean((model - target) ** 2))

    ratio = (math.sqrt(5) - 1) / 2
    low, high = search
    left, right = high - ratio * (high - low), low + ratio * (high - low)
    left_error, right_error = error(left), error(right)

    while high - low > tolerance:
        if left_error < right_error:
            high, right, right_error = right, left, left_error
            left = high - ratio * (high - low)
            left_error = error(left)
        else:
            low, left, left_error = left, right, right_error
            right = low + ratio * (high - low)
            right_error = error(right)

    return round((low + high) / 2, 4)


@dataclass(frozen=True)
class Evaluation:
    """How the model's index compares with TomTom's on samples it was not fitted on."""

    samples: int
    rmse: float                 # root mean square difference of the index
    mean_difference: float      # model minus TomTom, on average
    shape_correlation: float    # Pearson r of the two series over the samples


def evaluate(
    samples: list[CalibrationSample],
    spread: float,
    level: float,
    capacities: np.ndarray,
    lengths: np.ndarray,
) -> Evaluation:
    """Compare the model with TomTom on test samples."""

    if len(samples) < 2:
        raise ValueError("at least two test samples are needed")

    model = model_indices(samples, spread, level, capacities, lengths)
    target = np.array([s.tomtom_index for s in samples])
    difference = model - target

    return Evaluation(
        samples=len(samples),
        rmse=float(np.sqrt(np.mean(difference ** 2))),
        mean_difference=float(np.mean(difference)),
        shape_correlation=float(np.corrcoef(model, target)[0, 1]),
    )


# ============================================================
# 5. THE MODEL THE MAP SERVER USES
# ============================================================

def slot_of(moment: datetime) -> int:
    """The 15 minutes of the day a time falls in, 0 to 95."""

    return moment.hour * INTERVALS_PER_HOUR + moment.minute // 15


def site_centre(path: Path = INTERSECTIONS_PATH) -> tuple[float, float]:
    """The study intersection's centre (lon, lat)."""

    record = json.loads(path.read_text(encoding="utf-8"))[0]

    return record["center_longitude"], record["center_latitude"]


@dataclass(frozen=True)
class RoadNetwork:
    """Every segment, with what the model needs of it."""

    segments: list[RoadSegment]
    capacities: dict[str, float]
    capacity_array: np.ndarray
    length_array: np.ndarray
    # each segment's rank offset in every 15 minutes of the day (Sunday
    # to Thursday): from the trip model's hourly v/c, or else the
    # morning and evening ranks of the demand model, blended
    offsets: list[np.ndarray]
    # the same for Friday and Saturday; None when the same as offsets
    weekend_offsets: list[np.ndarray] | None = None

    def offsets_on(self, moment: datetime) -> list[np.ndarray]:
        """The offsets for the kind of day of this moment."""

        if self.weekend_offsets is not None and moment.weekday() in WEEKEND_DAYS:
            return self.weekend_offsets
        return self.offsets


def load_road_network(
    segments_path: Path = DEFAULT_SEGMENTS,
    mappings_path: Path = DEFAULT_MAPPINGS,
    demand_path: Path = DEFAULT_DEMAND,
    centre: tuple[float, float] | None = None,
    hourly_vc_path: Path | None = DEFAULT_HOURLY_VC,
    weekend_hourly_vc_path: Path | None = DEFAULT_WEEKEND_HOURLY_VC,
) -> RoadNetwork:
    """
    Read the segments and rank every corridor: by the trip model's v/c
    of each hour when hourly_vc_path exists, else by the demand model;
    Friday and Saturday by weekend_hourly_vc_path when it exists too.
    """

    segments = [
        RoadSegment(**record)
        for record in json.loads(segments_path.read_text(encoding="utf-8"))["segments"]
    ]
    way_ids = {
        record["segment_id"]: record["osm_way_id"]
        for record in json.loads(mappings_path.read_text(encoding="utf-8"))["mappings"]
    }
    capacities = {s.segment_id: segment_capacity(s) for s in segments}
    corridors = segment_corridors(segments, way_ids)
    at_site = site_segments(segments, centre or site_centre())

    def offsets_for(loads: dict[str, float]) -> np.ndarray:
        ranks = corridor_ranks(segments, corridors, loads)
        return rank_offsets(segments, corridors, ranks, site_rank(at_site, corridors, ranks))

    def hourly_offsets(path: Path) -> list[np.ndarray]:
        hourly = json.loads(path.read_text(encoding="utf-8"))["segments"]
        by_hour = [offsets_for({sid: values[h] for sid, values in hourly.items()}) for h in range(24)]
        result = []
        for slot in range(24 * INTERVALS_PER_HOUR):
            hour, share = divmod(slot, INTERVALS_PER_HOUR)
            share /= INTERVALS_PER_HOUR
            result.append((1 - share) * by_hour[hour] + share * by_hour[(hour + 1) % 24])
        return result

    weekend_offsets = None
    if hourly_vc_path is not None and hourly_vc_path.exists():
        slot_offsets = hourly_offsets(hourly_vc_path)
        if weekend_hourly_vc_path is not None and weekend_hourly_vc_path.exists():
            weekend_offsets = hourly_offsets(weekend_hourly_vc_path)
    else:
        demand = json.loads(demand_path.read_text(encoding="utf-8"))
        morning = offsets_for(segment_loads(segments, demand["to_activities"], capacities))
        evening = offsets_for(segment_loads(segments, demand["to_homes"], capacities))
        slot_offsets = [
            (1 - evening_share(slot)) * morning + evening_share(slot) * evening
            for slot in range(24 * INTERVALS_PER_HOUR)
        ]

    return RoadNetwork(
        segments=segments,
        capacities=capacities,
        capacity_array=np.array([capacities[s.segment_id] for s in segments]),
        length_array=np.array([line_length_m(s.geometry) for s in segments]),
        offsets=slot_offsets,
        weekend_offsets=weekend_offsets,
    )


def calibration_samples(
    levels: dict[datetime, float],
    network: RoadNetwork,
) -> list[CalibrationSample]:
    """One sample for every interval with the intersection's v/c."""

    return [
        CalibrationSample(
            moment=moment,
            site_level=level,
            offsets=network.offsets_on(moment)[slot_of(moment)],
            tomtom_index=tomtom_index(moment.date())[slot_of(moment)],
        )
        for moment, level in levels.items()
    ]


def usual_site_levels(levels: dict[datetime, float]) -> dict[tuple[int, int], float]:
    """
    The intersection's usual v/c for each day of the week (Monday = 0)
    and 15 minutes: the mean over the given intervals.
    """

    by_time: dict[tuple[int, int], list[float]] = defaultdict(list)

    for moment, level in levels.items():
        by_time[(moment.weekday(), slot_of(moment))].append(level)

    return {key: float(np.mean(values)) for key, values in by_time.items()}


@dataclass(frozen=True)
class IndexTable:
    """
    The network's travel-time index for a range of levels, in one 15
    minutes of the day (its rank offsets), so the level giving any
    index is read off instead of searched for each time.
    """

    levels: np.ndarray
    indices: np.ndarray     # rising with the level


def index_table(
    offsets: np.ndarray,
    spread: float,
    network: RoadNetwork,
    levels: np.ndarray = LEVEL_TABLE,
) -> IndexTable:
    """The travel-time index at every level of the table."""

    return IndexTable(
        levels=levels,
        indices=np.array([
            travel_time_index(
                segment_volume_to_capacity(1.0, offsets, spread, level),
                network.capacity_array, network.length_array,
            )
            for level in levels
        ]),
    )


@dataclass(frozen=True)
class ObservedModel:
    """
    The study intersection and the road network, with the spread, the
    intersection's usual v/c and the index table of every 15 minutes.
    """

    site: SiteInputs
    network: RoadNetwork
    spread: float
    usual: dict[tuple[int, int], float]
    tables: list[IndexTable]
    # the tables of Friday and Saturday; None when the same as tables
    weekend_tables: list[IndexTable] | None = None

    def tables_on(self, moment: datetime) -> list[IndexTable]:
        if self.weekend_tables is not None and moment.weekday() in WEEKEND_DAYS:
            return self.weekend_tables
        return self.tables


def build_model(
    site: SiteInputs,
    network: RoadNetwork,
    levels: dict[datetime, float],
    spread: float,
) -> ObservedModel:
    """The model, with the intersection's usual v/c taken from the given intervals."""

    return ObservedModel(
        site=site,
        network=network,
        spread=spread,
        usual=usual_site_levels(levels),
        tables=[index_table(offsets, spread, network) for offsets in network.offsets],
        weekend_tables=(
            [index_table(offsets, spread, network) for offsets in network.weekend_offsets]
            if network.weekend_offsets is not None else None
        ),
    )


def day_factor(model: ObservedModel, moment: datetime, site_level: float) -> float:
    """
    How much busier the intersection is than usual at this day of the
    week and 15 minutes, within DAY_FACTOR_LIMITS; 1 when there is no
    usual value to compare with.
    """

    usual = model.usual.get((moment.weekday(), slot_of(moment)))

    if not usual:
        return 1.0

    low, high = DAY_FACTOR_LIMITS

    return min(max(site_level / usual, low), high)


def day_factors(model: ObservedModel, levels: dict[datetime, float]) -> dict[datetime, float]:
    """
    The day factor at every interval: the intersection's v/c over its
    usual value, averaged over that date's intervals up to this one,
    within DAY_FACTOR_LIMITS (1 until there is a usual value to compare
    with). One factor for the whole day, instead of one per 15 minutes,
    keeps TomTom's pattern within the day; an interval's factor depends
    only on the counts up to it, so it never changes once stored.
    """

    low, high = DAY_FACTOR_LIMITS
    totals: dict[date, list[float]] = defaultdict(lambda: [0.0, 0])
    factors = {}

    for moment in sorted(levels):
        usual = model.usual.get((moment.weekday(), slot_of(moment)))
        total = totals[moment.date()]
        if usual:
            total[0] += levels[moment] / usual
            total[1] += 1
        factors[moment] = min(max(total[0] / total[1], low), high) if total[1] else 1.0

    return factors


@lru_cache(maxsize=16)
def _tomtom_day(day: date, free_flow_s: float) -> tuple[float, ...]:
    return tuple(tomtom_travel_index(day, free_flow_s))


def target_index(
    model: ObservedModel,
    moment: datetime,
    site_level: float,
    factor: float | None = None,
) -> float:
    """
    TomTom's travel time at this time over the map's free-flow time
    (tomtom_travel_index), its delay scaled by the day factor
    (day_factors), or by this interval's own factor when none is given.
    """

    network = model.network
    free_flow = free_flow_10km_s(network.segments, network.capacity_array, network.length_array)
    usual_index = _tomtom_day(moment.date(), round(free_flow, 3))[slot_of(moment)]
    if factor is None:
        factor = day_factor(model, moment, site_level)

    return 1 + (usual_index - 1) * factor


def interval_speeds(
    model: ObservedModel,
    moment: datetime,
    site_level: float,
    factor: float | None = None,
) -> tuple[list[int], float]:
    """
    Every segment's speed (percent of free flow) in one interval, and
    the network speed for the timeline (timeline_speed). The level is
    the one whose network index equals the target index.
    """

    slot = slot_of(moment)
    table = model.tables_on(moment)[slot]
    target = target_index(model, moment, site_level, factor)
    level = float(np.interp(target, table.indices, table.levels))
    speeds = speed_percent(segment_volume_to_capacity(
        1.0, model.network.offsets_on(moment)[slot], model.spread, level,
    ))

    return speeds.tolist(), timeline_speed(speeds, model.network.length_array)


def timeline_speed(speeds: np.ndarray, lengths: np.ndarray, share: float = TIMELINE_SLOWEST_SHARE) -> float:
    """
    The speed that the slowest share of the road length is at or below
    (length-weighted percentile), for the timeline bar.
    """

    order = np.argsort(speeds)
    cumulative = np.cumsum(lengths[order]) / lengths.sum()

    return round(float(np.asarray(speeds)[order][np.searchsorted(cumulative, share)]), 1)

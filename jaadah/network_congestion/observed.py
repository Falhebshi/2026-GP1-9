"""
Road congestion from the traffic observed at the study intersection.

Network Overview needs a congestion level for every road segment every
15 minutes, but traffic is counted at one intersection only. This module
carries what is counted there to the rest of the network:

1. How full the study intersection is: its HCM critical volume-to-
   capacity ratio in each 15 minutes, from the observed movement demand
   and the intersection's lanes and signal program, calculated by the
   KPI engine (backend/analytics/kpi/capacity.py).
2. How full every other road is. Roads are ranked by their load in the
   demand model (demand.py): trips over capacity, so a narrow road with
   moderate traffic can rank above a wide road with more. A segment
   gets the intersection's ratio, scaled by how its corridor ranks
   against the corridors at the intersection:

       v/c = level x site v/c x exp(spread x (corridor rank - site rank))

3. Speed: the BPR function (Bureau of Public Roads, 1964) turns a v/c
   ratio into travel time, and so into speed as a share of free flow:

       speed ratio = 1 / (1 + 0.15 x (v/c)^4)

Two values are not observed directly, and each comes from its own
source so that neither decides the other:

- spread (how much busier busy roads are than quiet ones): measured at
  the intersection, from how full its four approaches are against how
  the demand model ranks them (approach_spread). A city average cannot
  set it: an evenly congested city and one with green streets and red
  corridors can have the same average.
- level (how congested the city is overall): fitted to the TomTom
  Traffic Index congestion level for Riyadh, on part of the days only
  (fit_level); the other days test it (evaluate). Both sides use the
  same measure: travel time over free-flow time, weighted by
  vehicle-kilometres as TomTom weights it by drivers' trips.

The observed counts come from the traffic source through ingestion and
demand building (backend/ingestion, backend/demand), so missing counts
and movements without detectors are treated exactly as for the
simulation.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
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
    TOMTOM_CONGESTION_LEVEL_PERCENT,
    TOMTOM_HOURS,
)
from jaadah.network_congestion.segments import REPO_ROOT, line_length_m
from jaadah.network_congestion.synthetic import heading

DEFAULT_MAPPING_PATH = (
    REPO_ROOT / "data" / "processed" / "road_network" / "network_mappings.json"
)
DEFAULT_NETWORK_PATH = (
    REPO_ROOT / "data" / "processed" / "road_network" / "jaadah_study_area.net.xml"
)

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

# The approach a segment arrives on, from the direction it travels:
# travelling west means arriving from the east
APPROACH_BY_HEADING = {"W": "APP_E", "E": "APP_W", "S": "APP_N", "N": "APP_S"}

# The spread needs at least this many approaches with a ratio
MIN_SPREAD_APPROACHES = 3

# Where the level is searched, and how finely
LEVEL_SEARCH = (0.1, 5.0)
LEVEL_TOLERANCE = 0.001

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


def approach_ranks(
    segments: list[RoadSegment],
    corridors: dict[str, str],
    ranks: dict[str, float],
) -> dict[str, float]:
    """The rank of each approach, from the intersection's segments arriving on it."""

    by_approach: dict[str, list[RoadSegment]] = defaultdict(list)

    for segment in segments:
        by_approach[APPROACH_BY_HEADING[heading(segment)]].append(segment)

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

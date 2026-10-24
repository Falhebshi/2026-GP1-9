"""
Plan SUMO departures from movement-level SimulationDemand.

The planner turns each SimulationDemand record into exactly
vehicle_count timed departures on the movement's mapped SUMO route.
It is pure logic: it reads no files except the SUMO network in
compute_free_flow_times, and writes nothing. Writing the SUMO route
file is a separate step.

Rules applied, and why:

- Simulation time: SUMO second 0 is the analysis start minus the
  warm-up. Scenario.start_time and end_time are the analysis period;
  the warm-up runs before it and the clearance after it. Demand is
  required for the whole run, including warm-up and clearance, so
  traffic keeps arriving during the clearance.

- Routes: each movement uses its own mapped route only
  (MovementMapping.sumo_route_edge_ids). Ramp and U-turn variants are
  not split out of through demand, because no detector measures that
  split.

- Arrivals within an interval: N vehicles are given N independent,
  uniformly random times within the interval. This is a Poisson
  arrival process conditioned on exactly N arrivals, the random-arrival
  assumption also used by the HCM delay calculation (arrival type 3).

- Departure shift: a detector counts a vehicle at the stop line, but
  SUMO creates it at the network edge. Each departure is therefore
  moved earlier by the movement's free-flow travel time from the start
  of its route to the stop line, so that the vehicle reaches the stop
  line in the interval in which it was counted. Only free-flow time is
  used: any extra time spent in queues is the delay the KPIs measure.

- Reproducibility: each demand record gets its own random generator,
  seeded from the run seed, the movement and the interval start
  through SHA-256. The same inputs and seed always give the same
  departures, and changing one record does not change the departures
  of any other record.

- Missing data: a movement that receives detector demand must have a
  record for every interval of the run. A missing, duplicate or
  misaligned record raises an error rather than being filled in.
"""

import hashlib
import math
import random
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..models.mappings import MappingStatus, NetworkMappingConfig
from ..models.scenario import Scenario, SimulationConfig
from ..models.traffic import SimulationDemand


INTERVAL_S = 900
CENTISECONDS_PER_SECOND = 100


# ============================================================
# ERRORS
# ============================================================

class DemandPlanningError(ValueError):
    """Raised when demand cannot be planned safely; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot plan SUMO demand:\n" + "\n".join(problems))


# ============================================================
# PLAN MODELS
# ============================================================

class RunWindow(BaseModel):
    """The time span of one continuous run: warm-up, analysis, clearance."""

    model_config = ConfigDict(extra="forbid")

    epoch: datetime
    analysis_start: datetime
    analysis_end: datetime
    run_end: datetime

    @property
    def duration_s(self) -> int:
        return int((self.run_end - self.epoch).total_seconds())

    def interval_starts(self) -> list[datetime]:
        """Start of every 15-minute demand interval in the run."""

        return [
            self.epoch + timedelta(seconds=offset)
            for offset in range(0, self.duration_s, INTERVAL_S)
        ]

    def to_simulation_seconds(self, moment: datetime) -> float:
        return (moment - self.epoch).total_seconds()


class PlannedDeparture(BaseModel):
    """
    One vehicle to be created in SUMO.

    Stores only the facts the planner creates. The movement and interval are
    found through demand_id, and the stop-line time is depart_s plus the
    movement's free-flow time, so neither is stored a second time.
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    demand_id: str
    depart_s: float = Field(ge=0)


class DemandPlan(BaseModel):
    """
    All planned departures of one run, sorted by departure time.

    The run window, seed, routes and free-flow times used to make the
    plan belong to Scenario, SimulationConfig, SimulationRun and the
    mapping, and are not stored here.
    """

    model_config = ConfigDict(extra="forbid")

    departures: list[PlannedDeparture]


# ============================================================
# RUN WINDOW
# ============================================================

def build_run_window(
    scenario: Scenario,
    simulation_config: SimulationConfig,
) -> RunWindow:
    """Derive the run window from the scenario and the simulation configuration."""

    problems = []

    if scenario.end_time is None:
        raise DemandPlanningError(
            ["scenario must have an end_time to plan a bounded run"]
        )

    analysis_s = (scenario.end_time - scenario.start_time).total_seconds()
    warmup_s = simulation_config.warmup_duration_s
    clearance_s = simulation_config.clearance_duration_s

    if analysis_s % INTERVAL_S:
        problems.append(
            "analysis period must be a whole number of 15-minute intervals"
        )
    for label, value in (("warm-up", warmup_s), ("clearance", clearance_s)):
        if value % INTERVAL_S:
            problems.append(
                f"{label} duration must be a whole number of 15-minute "
                f"intervals, got {value} s"
            )
    if scenario.start_time.minute % 15 or scenario.start_time.second:
        problems.append(
            "analysis start must fall on a quarter hour (:00, :15, :30, :45)"
        )

    total_s = warmup_s + analysis_s + clearance_s
    if (
        simulation_config.simulation_duration_s is not None
        and simulation_config.simulation_duration_s != total_s
    ):
        problems.append(
            "simulation_duration_s must equal warm-up + analysis + clearance "
            f"({total_s:.0f} s), got {simulation_config.simulation_duration_s} s"
        )

    if problems:
        raise DemandPlanningError(problems)

    return RunWindow(
        epoch=scenario.start_time - timedelta(seconds=warmup_s),
        analysis_start=scenario.start_time,
        analysis_end=scenario.end_time,
        run_end=scenario.end_time + timedelta(seconds=clearance_s),
    )


# ============================================================
# MAPPING INPUTS
# ============================================================

def demand_movement_ids(config: NetworkMappingConfig) -> frozenset[str]:
    """Movements that receive detector demand: candidates of non-unresolved detectors."""

    return frozenset(
        movement_id
        for detector in config.detector_mappings
        if detector.mapping_status != MappingStatus.UNRESOLVED
        for movement_id in detector.movement_ids
    )


def movement_routes(config: NetworkMappingConfig) -> dict[str, list[str]]:
    """SUMO edge route of every mapped movement."""

    return {
        item.movement_id: list(item.sumo_route_edge_ids)
        for item in config.movement_mappings
    }


def _read_network_edges(network_path: str | Path):
    """Length, highest lane speed limit and lanes of every non-internal edge."""

    root = ET.parse(network_path).getroot()
    edge_length = {}
    edge_speed = {}
    lane_edge = {}
    for edge in root.findall("edge"):
        if edge.get("function") == "internal":
            continue
        lanes = edge.findall("lane")
        if not lanes:
            continue
        edge_id = edge.get("id")
        edge_length[edge_id] = float(lanes[0].get("length"))
        edge_speed[edge_id] = max(float(lane.get("speed")) for lane in lanes)
        for lane in lanes:
            lane_edge[lane.get("id")] = edge_id
    return edge_length, edge_speed, lane_edge


def stop_line_edges(
    config: NetworkMappingConfig,
    network_path: str | Path,
) -> dict[str, str]:
    """
    The SUMO edge that ends at each movement's stop line.

    It is the edge of the last SUMO segment of the canonical lanes that
    serve the movement; all of a movement's lanes must end on the same
    edge, and that edge must be on the movement's route. Movements
    served by no canonical lane (U-turns, ramps, tunnels) have no stop
    line and are left out.
    """

    _, _, lane_edge = _read_network_edges(network_path)
    sumo_lanes = {item.lane_id: item.sumo_lane_ids for item in config.lane_mappings}
    candidates: dict[str, set[str]] = {}
    for lane in config.approach_lanes:
        if lane.lane_id not in sumo_lanes:
            continue
        stop_edge = lane_edge.get(sumo_lanes[lane.lane_id][-1])
        for movement_id in lane.served_movement_ids:
            candidates.setdefault(movement_id, set()).add(stop_edge)

    problems = []
    edges = {}
    routes = movement_routes(config)
    for movement_id, found in sorted(candidates.items()):
        if len(found) != 1 or None in found:
            problems.append(
                f"{movement_id}: lanes do not end on one known stop-line edge: "
                f"{sorted(str(edge) for edge in found)}"
            )
            continue
        stop_edge = next(iter(found))
        if stop_edge not in routes[movement_id]:
            problems.append(
                f"{movement_id}: stop-line edge {stop_edge} is not on its route"
            )
            continue
        edges[movement_id] = stop_edge

    if problems:
        raise DemandPlanningError(problems)
    return edges


def compute_free_flow_times(
    config: NetworkMappingConfig,
    network_path: str | Path,
) -> dict[str, float]:
    """
    Free-flow travel time, in seconds, from the start of each movement's
    route to its stop line.

    The time is the sum, over the route edges up to and including the
    stop-line edge (stop_line_edges), of edge length divided by the
    edge's highest lane speed limit. Internal junction lanes are not
    included; they add a few metres.
    """

    edge_length, edge_speed, _ = _read_network_edges(network_path)
    routes = movement_routes(config)

    problems = []
    times = {}
    for movement_id, stop_edge in stop_line_edges(config, network_path).items():
        route = routes[movement_id]
        upstream = route[: route.index(stop_edge) + 1]
        missing = [edge for edge in upstream if edge not in edge_length]
        if missing:
            problems.append(f"{movement_id}: route edges not in network: {missing}")
            continue
        seconds = sum(edge_length[edge] / edge_speed[edge] for edge in upstream)
        times[movement_id] = round(seconds, 2)

    if problems:
        raise DemandPlanningError(problems)
    return times


# ============================================================
# DEPARTURE PLANNING
# ============================================================

def record_random_generator(
    seed: int,
    movement_id: str,
    interval_start: datetime,
) -> random.Random:
    """
    A generator unique to one demand record.

    SHA-256 is used instead of Python's hash(), which changes between
    processes, so the result is the same on every run and machine.
    """

    key = f"{seed}|{movement_id}|{interval_start.isoformat()}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def vehicle_id(movement_id: str, interval_end: datetime, number: int) -> str:
    """
    Stable vehicle ID, e.g. MOV_E_W__20261020T0815__007 for the seventh
    vehicle of 08:00-08:15.

    The interval is labelled by its end, as in the source records and the
    SimulationDemand IDs.
    """

    return f"{movement_id}__{interval_end:%Y%m%dT%H%M}__{number:03d}"


def _check_records(
    demands: list[SimulationDemand],
    window: RunWindow,
    routes: Mapping[str, list[str]],
    expected_movements: frozenset[str],
    free_flow_s: Mapping[str, float],
) -> None:
    problems = []
    interval_starts = set(window.interval_starts())
    seen = set()

    for demand in demands:
        label = f"{demand.demand_id} ({demand.movement_id}, {demand.interval_start.isoformat()})"
        if demand.movement_id not in routes:
            problems.append(f"{label}: unknown movement")
            continue
        if demand.movement_id not in expected_movements:
            problems.append(f"{label}: movement receives no detector demand")
        elif demand.movement_id not in free_flow_s:
            problems.append(f"{label}: no free-flow time for this movement")
        if (demand.interval_end - demand.interval_start).total_seconds() != INTERVAL_S:
            problems.append(f"{label}: interval is not 15 minutes")
        if demand.interval_start not in interval_starts:
            problems.append(
                f"{label}: interval is outside the run window or not on the 15-minute grid"
            )
        key = (demand.movement_id, demand.interval_start)
        if key in seen:
            problems.append(f"{label}: duplicate record for this movement and interval")
        seen.add(key)

    for movement_id in sorted(expected_movements):
        for start in sorted(interval_starts):
            if (movement_id, start) not in seen:
                end = start + timedelta(seconds=INTERVAL_S)
                problems.append(
                    f"missing demand: {movement_id} "
                    f"{start.isoformat()} - {end.isoformat()}"
                )

    if problems:
        raise DemandPlanningError(problems)


def _record_departures(
    demand: SimulationDemand,
    window: RunWindow,
    offset_s: float,
    seed: int,
) -> list[PlannedDeparture]:
    """
    Draw the record's departures, in whole hundredths of a second.

    Stop-line arrivals are uniform on [start, end). Departures are those
    times minus the free-flow offset. Where that would fall before
    second 0 (first warm-up interval only), the departures are drawn
    uniformly on [0, end - offset) instead.
    """

    start_s = window.to_simulation_seconds(demand.interval_start)
    end_s = start_s + INTERVAL_S
    low_cs = math.ceil(max(0.0, start_s - offset_s) * CENTISECONDS_PER_SECOND)
    high_cs = math.ceil((end_s - offset_s) * CENTISECONDS_PER_SECOND)
    if high_cs <= low_cs:
        raise DemandPlanningError(
            [f"{demand.movement_id}: free-flow time {offset_s} s is not shorter than an interval"]
        )

    rng = record_random_generator(seed, demand.movement_id, demand.interval_start)
    depart_cs = sorted(
        low_cs + math.floor(rng.random() * (high_cs - low_cs))
        for _ in range(demand.vehicle_count)
    )

    return [
        PlannedDeparture(
            vehicle_id=vehicle_id(demand.movement_id, demand.interval_end, number),
            demand_id=demand.demand_id,
            depart_s=cs / CENTISECONDS_PER_SECOND,
        )
        for number, cs in enumerate(depart_cs, start=1)
    ]


def plan_departures(
    demands: Iterable[SimulationDemand],
    *,
    window: RunWindow,
    routes: Mapping[str, list[str]],
    expected_movements: frozenset[str],
    free_flow_s: Mapping[str, float],
    seed: int,
) -> DemandPlan:
    """Plan exactly vehicle_count departures for every demand record of the run."""

    if isinstance(seed, bool) or seed < 0:
        raise DemandPlanningError(["seed must be a non-negative integer"])

    demands = list(demands)
    _check_records(demands, window, routes, expected_movements, free_flow_s)

    departures = []
    for demand in demands:
        departures.extend(
            _record_departures(
                demand, window, free_flow_s[demand.movement_id], seed
            )
        )
    departures.sort(key=lambda item: (item.depart_s, item.vehicle_id))

    return DemandPlan(departures=departures)

"""
Reduce a SUMO run's vehicle positions to VehicleDelayRecord,
IncompletePassage and UninsertedVehicle records (KPI measurements,
section 2).

Inputs are files written by one run: the FCD output (lane, pos, speed
and odometer every fcd_period_s), the tripinfo output (each vehicle's
speed factor, written with unfinished vehicles), and the demand
writer's manifest and demand file (vehicle -> demand record ->
movement). The SUMO run is not part of this module.

Rules applied, and why:

- Movement: found through the manifest and the demand file, never by
  parsing vehicle IDs. Only analysed movements are measured.
- Position along the path: the vehicle's odometer, the distance SUMO
  has driven it since it entered the network, including the junction's
  internal lanes and lane changes.
  - stop line: the last row on the stop-line edge, plus the rest of
    that lane (lane length - pos). A vehicle that has not reached the
    stop-line edge yet (still queued upstream when the run ends) is
    placed from its last row on an earlier route edge, plus the route
    length from there to the stop line, read from the network;
  - junction exit: the first row on the next route edge, minus pos;
  - zone entry and exit: zone_upstream_m before the stop line and
    zone_downstream_m after the junction exit.
- Crossing times: interpolated on the odometer between the two rows
  around each point.
- Free-flow travel time: the zone's path split at lane boundaries, each
  piece at its lane's speed limit times the vehicle's speed factor.
- Time stopped: rows with speed below 0.1 m/s between zone entry and
  exit, each counting fcd_period_s.
- Rounding: a time loss between -fcd_period_s and 0 is recorded as 0;
  below that the measurement is wrong and an error is raised.
- Unfinished: a vehicle that entered its zone but was last seen before
  reaching the zone exit gives an IncompletePassage. Every vehicle that
  entered its zone during the run is recorded; the engine uses those
  that arrived in the analysis period.
- Never inserted: SUMO leaves a vehicle it could not insert before the
  run ended out of tripinfo, or writes it with depart -1 when
  --tripinfo-output.write-undeparted is set. A planned vehicle due to
  depart during the run that is not in tripinfo as departed gives an
  UninsertedVehicle, with the time
  it was planned to reach the stop line (planned departure plus the
  movement's free-flow time to the stop line, as the demand planner
  aims it).
"""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

from ..models.mappings import NetworkMappingConfig
from ..models.outputs import IncompletePassage, UninsertedVehicle, VehicleDelayRecord
from ..sumo_demand.planner import RunWindow, compute_free_flow_times


HALTING_SPEED_MPS = 0.1


class VehiclePassageError(ValueError):
    """Raised when vehicle passages cannot be measured; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot measure vehicle passages:\n" + "\n".join(problems))


class Row(NamedTuple):
    time_s: float
    lane: str
    pos_m: float
    speed_mps: float
    odometer_m: float


class MovementZone(NamedTuple):
    """
    Where a movement's zone is: its stop-line edge, junction-exit edge
    and distances. to_stop_line_m gives, for each route edge up to the
    stop-line edge, the route length from the end of that edge to the
    stop line (0 for the stop-line edge itself).
    """

    stop_edge: str
    exit_edge: str
    upstream_m: float
    downstream_m: float
    to_stop_line_m: dict[str, float]


class VehiclePassages(NamedTuple):
    records: list[VehicleDelayRecord]
    incomplete: list[IncompletePassage]
    uninserted: list[UninsertedVehicle]


# ============================================================
# NETWORK
# ============================================================

def movement_zones(config: NetworkMappingConfig, network_path: str | Path) -> dict[str, MovementZone]:
    """The zone of every analysed movement, from the mapping (KPI measurements, section 1.1)."""

    edge_lengths, junction_lengths = read_route_lengths(network_path)

    approaches = {item.approach_id: item for item in config.approach_mappings}
    movements = {item.movement_id: item for item in config.movement_mappings}
    sumo_lanes = {item.lane_id: item.sumo_lane_ids for item in config.lane_mappings}

    stop_edges = defaultdict(set)
    for lane in config.approach_lanes:
        if lane.lane_id in sumo_lanes:
            for movement_id in lane.served_movement_ids:
                stop_edges[movement_id].add(sumo_lanes[lane.lane_id][-1].rsplit("_", 1)[0])

    problems, zones = [], {}
    for item in config.movement_attributes:
        movement = movements[item.movement_id]
        approach = approaches.get(movement.approach_id)
        found = stop_edges.get(item.movement_id, set())
        route = movement.sumo_route_edge_ids
        if approach is None or approach.zone_upstream_m is None:
            problems.append(f"{item.movement_id}: its approach has no measurement zone")
        elif len(found) != 1:
            problems.append(f"{item.movement_id}: lanes do not end on one mapped stop-line edge")
        else:
            stop_edge = next(iter(found))
            if stop_edge not in route or route.index(stop_edge) == len(route) - 1:
                problems.append(f"{item.movement_id}: stop-line edge {stop_edge} has no next route edge")
                continue
            upstream = route[: route.index(stop_edge) + 1]
            to_stop = {stop_edge: 0.0}
            for edge, following in reversed(list(zip(upstream, upstream[1:]))):
                to_stop[edge] = (to_stop[following] + edge_lengths[following]
                                 + junction_lengths.get((edge, following), 0.0))
            zones[item.movement_id] = MovementZone(
                stop_edge=stop_edge,
                exit_edge=route[route.index(stop_edge) + 1],
                upstream_m=approach.zone_upstream_m,
                downstream_m=approach.zone_downstream_m,
                to_stop_line_m=to_stop,
            )
    if problems:
        raise VehiclePassageError(problems)
    return zones


def read_lanes(network_path: str | Path) -> tuple[dict[str, float], dict[str, float]]:
    """Length and speed limit of every lane, including internal lanes."""

    lengths, speeds = {}, {}
    for lane in ET.parse(network_path).getroot().iter("lane"):
        lengths[lane.get("id")] = float(lane.get("length"))
        speeds[lane.get("id")] = float(lane.get("speed"))
    return lengths, speeds


def read_route_lengths(network_path: str | Path) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """
    Length of every normal edge, and the length of the junction's
    internal lanes between two connected edges (the mean over their
    lane connections; they differ by a few centimetres to metres).
    """

    root = ET.parse(network_path).getroot()
    edge_lengths = {
        edge.get("id"): float(edge.find("lane").get("length"))
        for edge in root.iter("edge")
        if edge.get("function") != "internal" and edge.find("lane") is not None
    }
    internal = {lane.get("id"): float(lane.get("length")) for lane in root.iter("lane")}
    via_next = {}
    for connection in root.iter("connection"):
        if connection.get("from", "").startswith(":") and connection.get("via"):
            via_next[f"{connection.get('from')}_{connection.get('fromLane')}"] = connection.get("via")

    options = defaultdict(list)
    for connection in root.iter("connection"):
        via = connection.get("via")
        if connection.get("from", "").startswith(":") or not via:
            continue
        length, seen = 0.0, 0
        while via and seen < 10:
            length += internal[via]
            via, seen = via_next.get(via), seen + 1
        options[(connection.get("from"), connection.get("to"))].append(length)
    return edge_lengths, {pair: sum(values) / len(values) for pair, values in options.items()}


def edge_of(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


# ============================================================
# RUN FILES
# ============================================================

def vehicle_movements(manifest_path: str | Path, demand_path: str | Path) -> dict[str, str]:
    """vehicle_id -> movement_id, through the manifest and the demand file."""

    movement_of = {item["demand_id"]: item["movement_id"]
                   for item in json.loads(Path(demand_path).read_text(encoding="utf-8"))}
    return {item["vehicle_id"]: movement_of[item["demand_id"]] for item in planned_departures(manifest_path)}


def planned_departures(manifest_path: str | Path) -> list[dict]:
    """The manifest's planned departures: vehicle_id, demand_id and depart_s."""

    return json.loads(Path(manifest_path).read_text(encoding="utf-8"))["departures"]


def speed_factors(tripinfo_path: str | Path) -> dict[str, float]:
    """
    The speed factor of each vehicle that entered the network, from
    tripinfo (written with unfinished vehicles). Vehicles that never
    departed (depart -1, written with write-undeparted) are left out.
    """

    return {item.get("id"): float(item.get("speedFactor"))
            for item in ET.parse(tripinfo_path).getroot().iter("tripinfo")
            if float(item.get("depart", "0")) >= 0}


def read_fcd(fcd_path: str | Path, vehicle_ids: set[str]) -> dict[str, list[Row]]:
    """The FCD rows of the given vehicles, in time order."""

    rows = defaultdict(list)
    time_s = None
    for event, element in ET.iterparse(fcd_path, events=("start", "end")):
        if event == "start" and element.tag == "timestep":
            time_s = float(element.get("time"))
        elif event == "end" and element.tag == "vehicle":
            vehicle_id = element.get("id")
            if vehicle_id in vehicle_ids:
                rows[vehicle_id].append(Row(
                    time_s, element.get("lane"), float(element.get("pos")),
                    float(element.get("speed")), float(element.get("odometer")),
                ))
            element.clear()
        elif event == "end" and element.tag == "timestep":
            element.clear()
    return dict(rows)


# ============================================================
# ONE VEHICLE
# ============================================================

def time_at(rows: list[Row], odometer_m: float) -> float | None:
    """Interpolated time at which the vehicle reached odometer_m, or None if it did not."""

    for previous, row in zip(rows, rows[1:]):
        if row.odometer_m >= odometer_m:
            if row.odometer_m == previous.odometer_m:
                return row.time_s
            share = (odometer_m - previous.odometer_m) / (row.odometer_m - previous.odometer_m)
            return previous.time_s + max(0.0, share) * (row.time_s - previous.time_s)
    return None


def stop_line_odometer(rows: list[Row], zone: MovementZone, lengths: dict[str, float]) -> float | None:
    """
    The vehicle's odometer at the stop line: from its last row on the
    stop-line edge, or, if it did not reach that edge, from its last row
    on an earlier route edge. None if it was never on those edges.
    """

    upstream = [row for row in rows if edge_of(row.lane) in zone.to_stop_line_m]
    if not upstream:
        return None
    on_stop_edge = [row for row in upstream if edge_of(row.lane) == zone.stop_edge]
    last = on_stop_edge[-1] if on_stop_edge else upstream[-1]
    return (last.odometer_m + lengths[last.lane] - last.pos_m
            + zone.to_stop_line_m[edge_of(last.lane)])


def junction_exit_odometer(rows: list[Row], zone: MovementZone) -> float | None:
    for row in rows:
        if edge_of(row.lane) == zone.exit_edge:
            return row.odometer_m - row.pos_m
    return None


def free_flow_time(
    rows: list[Row],
    start_m: float,
    end_m: float,
    lengths: dict[str, float],
    speeds: dict[str, float],
    speed_factor: float,
) -> float:
    """Free-flow time between two odometer values, each lane piece at its own desired speed."""

    pieces = []
    for previous, row in zip(rows, rows[1:]):
        if previous.lane != row.lane and edge_of(previous.lane) != edge_of(row.lane):
            boundary = previous.odometer_m + lengths[previous.lane] - previous.pos_m
            boundary = min(max(boundary, previous.odometer_m), row.odometer_m)
            pieces.append((previous.odometer_m, boundary, previous.lane))
            pieces.append((boundary, row.odometer_m, row.lane))
        else:
            pieces.append((previous.odometer_m, row.odometer_m, previous.lane))

    seconds = 0.0
    for low, high, lane in pieces:
        length = min(high, end_m) - max(low, start_m)
        if length > 0:
            seconds += length / (speeds[lane] * speed_factor)
    return seconds


# ============================================================
# ALL VEHICLES
# ============================================================

def collect_vehicle_passages(
    config: NetworkMappingConfig,
    network_path: str | Path,
    *,
    run_id: str,
    window: RunWindow,
    fcd_path: str | Path,
    tripinfo_path: str | Path,
    manifest_path: str | Path,
    demand_path: str | Path,
    fcd_period_s: float = 0.4,
) -> VehiclePassages:
    """Every analysed vehicle's passage through its movement's zone in one run."""

    zones = movement_zones(config, network_path)
    lengths, speeds = read_lanes(network_path)
    movement_of = {v: m for v, m in vehicle_movements(manifest_path, demand_path).items() if m in zones}
    factors = speed_factors(tripinfo_path)
    traces = read_fcd(fcd_path, set(movement_of))

    def moment(seconds):
        return window.epoch + timedelta(seconds=seconds)

    records, incomplete, problems = [], [], []
    for vehicle_id, movement_id in sorted(movement_of.items()):
        rows = traces.get(vehicle_id)
        if not rows or len(rows) < 2:
            continue
        zone = zones[movement_id]
        stop_m = stop_line_odometer(rows, zone, lengths)
        if stop_m is None:
            continue
        entry_m = stop_m - zone.upstream_m
        if entry_m < rows[0].odometer_m:
            problems.append(f"{vehicle_id}: first seen inside its zone")
            continue
        entry_s = time_at(rows, entry_m)
        if entry_s is None:
            continue

        exit_junction_m = junction_exit_odometer(rows, zone)
        stop_s = time_at(rows, stop_m) if rows[-1].odometer_m >= stop_m else None
        exit_m = None if exit_junction_m is None else exit_junction_m + zone.downstream_m
        exit_s = None if exit_m is None else time_at(rows, exit_m)

        if exit_s is None:
            incomplete.append(IncompletePassage(
                run_id=run_id, vehicle_id=vehicle_id, movement_id=movement_id,
                zone_entry_time=moment(entry_s),
                stop_line_time=None if stop_s is None else moment(stop_s),
                last_seen_time=moment(rows[-1].time_s),
            ))
            continue

        if vehicle_id not in factors:
            problems.append(f"{vehicle_id}: no speed factor in tripinfo")
            continue
        zone_time = exit_s - entry_s
        free_flow = free_flow_time(rows, entry_m, exit_m, lengths, speeds, factors[vehicle_id])
        if free_flow - zone_time > fcd_period_s:
            problems.append(f"{vehicle_id}: time loss {zone_time - free_flow:.2f} s is below "
                            f"-{fcd_period_s} s; the measurement is wrong")
            continue
        halted = sum(fcd_period_s for row in rows
                     if entry_s <= row.time_s <= exit_s and row.speed_mps < HALTING_SPEED_MPS)

        records.append(VehicleDelayRecord(
            run_id=run_id, vehicle_id=vehicle_id, movement_id=movement_id,
            zone_entry_time=moment(entry_s),
            stop_line_time=moment(stop_s),
            zone_exit_time=moment(exit_s),
            zone_distance_m=exit_m - entry_m,
            free_flow_travel_time_s=min(free_flow, zone_time),
            halted_time_s=min(halted, zone_time),
        ))

    if problems:
        raise VehiclePassageError(problems)

    free_flow_s = compute_free_flow_times(config, network_path)
    uninserted = [
        UninsertedVehicle(
            run_id=run_id,
            vehicle_id=item["vehicle_id"],
            movement_id=movement_of[item["vehicle_id"]],
            planned_stop_line_time=moment(
                item["depart_s"] + free_flow_s[movement_of[item["vehicle_id"]]]
            ),
        )
        for item in planned_departures(manifest_path)
        if item["vehicle_id"] in movement_of
        and item["vehicle_id"] not in factors
        and item["depart_s"] < window.duration_s
    ]
    return VehiclePassages(records=records, incomplete=incomplete, uninserted=uninserted)

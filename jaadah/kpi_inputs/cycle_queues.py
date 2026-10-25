"""
Lane queues per signal cycle, measured from a SUMO run's FCD output and
reduced to CycleQueueRecord records (KPI measurements, section 5).

The FCD file is read once, step by step, without keeping the rows, so
memory does not grow with the number of vehicles.

Rules applied, and why:

- Section: each canonical lane's queue is measured over its own section
  (KPI engine section 13.1): its lane chain (LaneMapping.sumo_lane_ids)
  together with the junction lanes that join the chain's segments, from
  the start of the first segment to the stop line. A junction lane can be
  long (32.6 m on South's lanes 1 and 2), and vehicles on it are part of
  the section.
- Queued: a vehicle slower than 1.39 m/s (5 km/h) for at least 1 s.
  Vehicles creeping at the back of a queue count, so the queue length is
  how far back the queue reaches.
- Anchored at the stop line: a queue starts with a queued vehicle whose
  front is less than 10 m from the stop line, and continues through
  queued vehicles less than 10 m behind the back of the one before. Its
  length is the distance from the stop line to the back of its last
  vehicle; queued vehicles separated from it by a larger gap are not part
  of it.
- Section end: a queue whose last vehicle's back is less than 10 m from
  the start of the section may continue upstream, where lanes merge and
  the queue belongs to no single lane. Its length is capped at the
  section length and the record is marked reaches_section_end; the full
  queue is measured on the approach.
- Cycles: one record per lane and whole signal cycle of the run, aligned
  with the cycle start (KPI engine section 6.1): the cycle is the signal
  program's, and the signal's offset must be a whole number of cycles.
  The record holds the longest queue in the cycle, in metres and in
  vehicles (each the largest of the cycle), and a cycle without a queue
  is a measured 0.
"""

import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

from ..models.mappings import NetworkMappingConfig
from ..models.outputs import CycleQueueRecord
from ..models.signals import SignalProgram
from ..sumo_demand.planner import RunWindow


JAM_SPEED_MPS = 1.39
JAM_TIME_S = 1.0
JAM_GAP_M = 10.0
TOLERANCE_S = 1e-6


class CycleQueueError(ValueError):
    """Raised when cycle queues cannot be measured; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot measure cycle queues:\n" + "\n".join(problems))


class LaneSection(NamedTuple):
    """
    A canonical lane's section. to_stop_line_m gives, for each SUMO lane of
    the section, the distance from the end of that lane to the stop line.
    """

    lane_id: str
    length_m: float
    to_stop_line_m: dict[str, float]


class QueueAtStep(NamedTuple):
    length_m: float
    vehicles: int
    reaches_section_end: bool


# ============================================================
# SECTIONS
# ============================================================

def lane_sections(config: NetworkMappingConfig, network_path: str | Path) -> dict[str, LaneSection]:
    """Every canonical lane's section, with the junction lanes between its segments."""

    root = ET.parse(network_path).getroot()
    lengths = {lane.get("id"): float(lane.get("length")) for lane in root.iter("lane")}
    via = {}
    for connection in root.iter("connection"):
        via[(f"{connection.get('from')}_{connection.get('fromLane')}",
             f"{connection.get('to')}_{connection.get('toLane')}")] = connection.get("via")
    internal_next = {
        source: target for (source, target), _ in via.items() if source.startswith(":")
    }

    problems, sections, owner = [], {}, {}
    for mapping in config.lane_mappings:
        chain = mapping.sumo_lane_ids
        pieces = [chain[0]]
        for upstream, downstream in zip(chain, chain[1:]):
            junction = via.get((upstream, downstream))
            while junction:
                pieces.append(junction)
                junction = via.get((junction, internal_next.get(junction))) if junction in internal_next else None
            pieces.append(downstream)

        missing = [lane for lane in pieces if lane not in lengths]
        if missing:
            problems.append(f"{mapping.lane_id}: SUMO lanes not in network: {missing}")
            continue
        to_stop, remaining = {}, 0.0
        for lane in reversed(pieces):
            to_stop[lane] = remaining
            remaining += lengths[lane]
        for lane in pieces:
            if lane in owner:
                problems.append(f"SUMO lane {lane} is in the sections of {owner[lane]} and {mapping.lane_id}")
            owner[lane] = mapping.lane_id
        sections[mapping.lane_id] = LaneSection(mapping.lane_id, remaining, to_stop)

    if problems:
        raise CycleQueueError(problems)
    return sections


def anchored_queue(fronts_m: list[float], section_length_m: float, vehicle_length_m: float) -> QueueAtStep:
    """
    The queue anchored at the stop line, from the distances of queued
    vehicles' fronts to the stop line.
    """

    back, vehicles = None, 0
    for front in sorted(fronts_m):
        previous_end = 0.0 if back is None else back
        if front - previous_end >= JAM_GAP_M:
            break
        back, vehicles = front + vehicle_length_m, vehicles + 1

    if back is None:
        return QueueAtStep(0.0, 0, False)
    reaches_end = back > section_length_m - JAM_GAP_M
    return QueueAtStep(min(back, section_length_m), vehicles, reaches_end)


# ============================================================
# CYCLE QUEUES
# ============================================================

def collect_cycle_queues(
    config: NetworkMappingConfig,
    network_path: str | Path,
    program: SignalProgram,
    fcd_path: str | Path,
    *,
    run_id: str,
    window: RunWindow,
    vehicle_length_m: float,
) -> list[CycleQueueRecord]:
    """Every canonical lane's longest queue in every whole signal cycle of the run."""

    cycle = program.cycle_length_s
    plans = [item for item in ET.parse(network_path).getroot().findall("tlLogic")
             if item.get("id") == config.intersection_mapping.sumo_tls_id]
    offsets = sorted({float(item.get("offset", 0)) for item in plans})
    if any(min(offset % cycle, cycle - offset % cycle) > TOLERANCE_S for offset in offsets):
        raise CycleQueueError([f"signal offset {offsets} is not a whole number of {cycle:g} s cycles; "
                               "cycles could not be aligned with the run"])

    sections = lane_sections(config, network_path)
    section_of = {lane: section for section in sections.values() for lane in section.to_stop_line_m}
    lengths = {lane.get("id"): float(lane.get("length")) for lane in ET.parse(network_path).getroot().iter("lane")}

    slow_since: dict[str, float] = {}
    best: dict[tuple[str, int], list] = defaultdict(lambda: [0.0, 0, False])
    fronts = defaultdict(list)
    time_s = None

    def close_step():
        number = int(math.floor(time_s / cycle + TOLERANCE_S))
        for lane_id, section in sections.items():
            queue = anchored_queue(fronts[lane_id], section.length_m, vehicle_length_m)
            item = best[(lane_id, number)]
            item[0] = max(item[0], queue.length_m)
            item[1] = max(item[1], queue.vehicles)
            item[2] = item[2] or queue.reaches_section_end
        fronts.clear()

    for event, element in ET.iterparse(fcd_path, events=("start", "end")):
        if event == "start" and element.tag == "timestep":
            time_s = float(element.get("time"))
        elif event == "end" and element.tag == "vehicle":
            vehicle_id, lane = element.get("id"), element.get("lane")
            if float(element.get("speed")) < JAM_SPEED_MPS:
                slow_since.setdefault(vehicle_id, time_s)
            else:
                slow_since.pop(vehicle_id, None)
            section = section_of.get(lane)
            if section is not None and time_s - slow_since.get(vehicle_id, math.inf) >= JAM_TIME_S - TOLERANCE_S:
                front = lengths[lane] - float(element.get("pos")) + section.to_stop_line_m[lane]
                fronts[section.lane_id].append(front)
            element.clear()
        elif event == "end" and element.tag == "timestep":
            close_step()
            element.clear()

    whole_cycles = int(window.duration_s // cycle + TOLERANCE_S)
    return [
        CycleQueueRecord(
            run_id=run_id,
            lane_id=lane_id,
            cycle_start=window.epoch + timedelta(seconds=number * cycle),
            cycle_end=window.epoch + timedelta(seconds=(number + 1) * cycle),
            max_queue_length_m=round(best[(lane_id, number)][0], 3),
            max_queue_vehicles=best[(lane_id, number)][1],
            reaches_section_end=best[(lane_id, number)][2],
        )
        for lane_id in sections
        for number in range(whole_cycles)
    ]

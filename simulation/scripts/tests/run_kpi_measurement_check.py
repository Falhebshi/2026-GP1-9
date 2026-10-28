"""
Run SUMO once with KPI measurement output and check the measurement records.

The demand is generated with jaadah/sumo_demand exactly as for a real run
(hand-made by default: every demand movement gets the same number of
vehicles in every interval; with --demand, SimulationDemand records are
read from an exported JSON file). SUMO then runs once with FCD output
(lane, pos, speed, odometer every 0.4 s) and tripinfo, and
jaadah/kpi_inputs reduces them to VehicleDelayRecord,
IncompletePassage, CycleQueueRecord and ApproachCycleQueueRecord records
(docs/kpi_measurements.md).

The run passes when:

1. SUMO ends without an error;
2. every vehicle of an analysed movement that arrived in its zone during
   the analysis period has left it by the end of the run (otherwise the
   clearance is too short and the engine reports those intervals as
   unavailable);
3. no vehicle's time loss in its zone exceeds its time loss over its
   whole trip, as SUMO reports it in tripinfo, by more than one FCD
   period (the zone is part of the trip, so it cannot lose more);
4. every canonical lane and every signalised approach has a queue
   record for every whole signal cycle of the run (a missing record
   would be reported as unavailable);
5. no approach's queue is shorter than the queue of one of its signal
   lanes in the same cycle (the approach queue continues the lane
   queues, so it cannot be shorter), unless it reached its zone end
   (it stops there, and both values are then unavailable).

The records are saved as JSON next to the SUMO files.
"""

import argparse
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Support direct invocation from any working directory without installing Jaadah.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import TypeAdapter

from jaadah.kpi_inputs.cycle_queues import CycleQueueError, collect_cycle_queues
from jaadah.kpi_inputs.signal_program import SignalProgramError, build_signal_program
from jaadah.kpi_inputs.vehicle_passages import VehiclePassageError, collect_vehicle_passages
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import Scenario, SimulationConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import (
    DemandPlanningError,
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import VEHICLE_TYPE, DemandWritingError, write_sumo_demand

DEFAULT_MAPPING = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
DEFAULT_NETWORK = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
DEFAULT_OUTPUT = PROJECT_ROOT / "simulation/outputs/tests/kpi_measurement_check"
WARMUP_S = 900
CLEARANCE_S = 900
FCD_PERIOD_S = 0.4
OUTPUT_PRECISION = 3
RUN_ID = "RUN_KPI_MEASUREMENT_CHECK"


def make_window(analysis_start, analysis_end):
    scenario = Scenario(
        scenario_id="SCN_KPI_MEASUREMENT_CHECK",
        intersection_id="INT_001",
        time_context="historical",
        control_mode="baseline",
        start_time=analysis_start,
        end_time=analysis_end,
    )
    config = SimulationConfig(warmup_duration_s=WARMUP_S, clearance_duration_s=CLEARANCE_S)
    return build_run_window(scenario, config)


def hand_made_demand(window, movements, vehicles_per_record):
    """The same number of vehicles for every demand movement and interval."""

    demands = []
    for start in window.interval_starts():
        end = start + timedelta(seconds=900)
        for movement_id in sorted(movements):
            demands.append(SimulationDemand(
                demand_id=f"DEM_TEST_{movement_id}_{end:%Y%m%dT%H%M}",
                interval_start=start,
                interval_end=end,
                movement_id=movement_id,
                vehicle_count=vehicles_per_record,
                source="synthetic",
                source_observation_ids=[f"OBS_TEST_{movement_id}_{end:%Y%m%dT%H%M}"],
            ))
    return demands


def run_sumo(sumo_bin, network, route_file, folder, end_s, step_length, seed):
    paths = {
        "log": folder / "sumo.log",
        "fcd": folder / "fcd.xml",
        "tripinfo": folder / "tripinfo.xml",
    }
    command = [
        sumo_bin,
        "--net-file", str(network),
        "--route-files", str(route_file),
        "--begin", "0",
        "--end", str(end_s),
        "--step-length", str(step_length),
        "--seed", str(seed),
        "--no-step-log", "true",
        "--precision", str(OUTPUT_PRECISION),
        "--log", str(paths["log"]),
        "--fcd-output", str(paths["fcd"]),
        "--device.fcd.period", str(FCD_PERIOD_S),
        "--fcd-output.attributes", "lane,pos,speed,odometer",
        "--tripinfo-output", str(paths["tripinfo"]),
        "--tripinfo-output.write-unfinished", "true",
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    return completed.returncode, paths


def evaluate(passages, queues, expected_cycles, lane_ids, mapping, window, returncode, paths):
    trips = {item.get("id"): item.attrib for item in ET.parse(paths["tripinfo"]).getroot().iter("tripinfo")}

    unfinished = sorted(
        item.vehicle_id for item in passages.incomplete
        if window.analysis_start <= item.zone_entry_time < window.analysis_end
    )
    exceeding = sorted(
        item.vehicle_id for item in passages.records
        if item.time_loss_s > float(trips[item.vehicle_id]["timeLoss"]) + FCD_PERIOD_S
    )
    cycles = {lane_id: 0 for lane_id in lane_ids}
    for item in queues.lanes:
        cycles[item.lane_id] = cycles.get(item.lane_id, 0) + 1
    for item in queues.approaches:
        cycles[item.approach_id] = cycles.get(item.approach_id, 0) + 1
    approach_ids = sorted({item.approach_id for item in queues.approaches})
    incomplete_lanes = sorted(key for key, count in cycles.items() if count != expected_cycles)

    signal_movements = {
        item.movement_id for item in mapping.movement_attributes if item.control.value == "signalized"
    }
    approach_of_lane = {
        lane.lane_id: lane.approach_id for lane in mapping.approach_lanes
        if set(lane.served_movement_ids) & signal_movements
    }
    approach_queue = {
        (item.approach_id, item.cycle_start): item.max_queue_length_m
        for item in queues.approaches if not item.reaches_zone_end
    }
    shorter = sorted({
        f"{approach_of_lane[item.lane_id]} {item.cycle_start:%H:%M:%S}"
        for item in queues.lanes
        if item.lane_id in approach_of_lane
        and (approach_of_lane[item.lane_id], item.cycle_start) in approach_queue
        and approach_queue[(approach_of_lane[item.lane_id], item.cycle_start)] < item.max_queue_length_m - 1e-6
    })
    return {
        "1. SUMO ends without an error": {"passed": returncode == 0, "exit_code": returncode},
        "2. Analysis-period arrivals have left their zone": {
            "passed": not unfinished, "unfinished": unfinished[:20], "count": len(unfinished)},
        "3. Zone time loss within trip time loss": {
            "passed": not exceeding, "exceeding": exceeding[:20], "count": len(exceeding)},
        "4. A queue record for every lane, approach and cycle": {
            "passed": not incomplete_lanes, "with_missing_cycles": incomplete_lanes,
            "lanes": len(lane_ids), "approaches": len(approach_ids), "cycles_each": expected_cycles,
            "records": len(queues.lanes) + len(queues.approaches)},
        "5. No approach queue shorter than its lanes'": {
            "passed": not shorter, "approach_cycles": shorter[:20], "count": len(shorter)},
    }


def uninserted_by_movement(uninserted):
    counts = {}
    for item in uninserted:
        counts[item.movement_id] = counts.get(item.movement_id, 0) + 1
    return dict(sorted(counts.items()))


def movement_summary(passages, window):
    rows = defaultdict(list)
    for item in passages.records:
        if window.analysis_start <= item.zone_entry_time < window.analysis_end:
            rows[item.movement_id].append(item)
    return {
        movement_id: {
            "vehicles": len(items),
            "zone_m": round(items[0].zone_distance_m, 1),
            "mean_time_loss_s": round(sum(i.time_loss_s for i in items) / len(items), 1),
            "mean_halted_s": round(sum(i.halted_time_s for i in items) / len(items), 1),
        }
        for movement_id, items in sorted(rows.items())
    }


def lane_summary(queues, window):
    rows = defaultdict(list)
    for item in queues:
        if window.analysis_start <= item.cycle_start < window.analysis_end:
            rows[item.lane_id].append(item)
    return {
        lane_id: {
            "cycles": len(items),
            "max_queue_m": max(i.max_queue_length_m for i in items),
            "max_queue_vehicles": max(i.max_queue_vehicles for i in items),
            "cycles_reaching_section_end": sum(i.reaches_section_end for i in items),
        }
        for lane_id, items in sorted(rows.items())
    }


def approach_summary(queues, window):
    rows = defaultdict(list)
    for item in queues:
        if window.analysis_start <= item.cycle_start < window.analysis_end:
            rows[item.approach_id].append(item)
    return {
        approach_id: {
            "cycles": len(items),
            "max_queue_m": max(i.max_queue_length_m for i in items),
            "max_queue_vehicles": max(i.max_queue_vehicles for i in items),
            "cycles_reaching_zone_end": sum(i.reaches_zone_end for i in items),
        }
        for approach_id, items in sorted(rows.items())
    }


def save(path, items):
    path.write_text(json.dumps([item.model_dump(mode="json") for item in items], indent=2) + "\n",
                    encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--net", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sumo-bin", default="sumo")
    parser.add_argument("--demand", type=Path, help="exported SimulationDemand JSON list")
    parser.add_argument("--analysis-start", default="2026-10-20T08:00:00+03:00")
    parser.add_argument("--analysis-end", default="2026-10-20T09:00:00+03:00")
    parser.add_argument("--vehicles-per-record", type=int, default=20)
    parser.add_argument("--step-length", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if shutil.which(args.sumo_bin) is None:
        parser.error("SUMO executable not found. Supply --sumo-bin with the path to sumo.exe.")
    if not args.mapping.is_file() or not args.net.is_file():
        parser.error("Mapping JSON or SUMO network not found.")

    try:
        mapping = load_network_mappings(args.mapping, network_path=args.net)
        window = make_window(
            datetime.fromisoformat(args.analysis_start),
            datetime.fromisoformat(args.analysis_end),
        )
        movements = demand_movement_ids(mapping)
        if args.demand:
            demands = TypeAdapter(list[SimulationDemand]).validate_json(args.demand.read_bytes())
        else:
            demands = hand_made_demand(window, movements, args.vehicles_per_record)
        plan = plan_departures(
            demands,
            window=window,
            routes=movement_routes(mapping),
            expected_movements=movements,
            free_flow_s=compute_free_flow_times(mapping, args.net),
            seed=args.seed,
        )
        generated = write_sumo_demand(plan, demands, mapping, args.out)
        program = build_signal_program(
            mapping, args.net, scenario_id="SCN_KPI_MEASUREMENT_CHECK", signal_program_id="SP_KPI_MEASUREMENT_CHECK",
        )
        folder = generated.route_file.parent
    except (DemandPlanningError, DemandWritingError, SignalProgramError, ValueError, OSError) as exc:
        print(f"Cannot run the check:\n{exc}", file=sys.stderr)
        return 2

    returncode, paths = run_sumo(
        args.sumo_bin, args.net, generated.route_file, folder,
        window.duration_s, args.step_length, args.seed,
    )
    if not all(paths[name].is_file() for name in ("fcd", "tripinfo")):
        print(f"SUMO did not produce its outputs (exit code {returncode}); see {paths['log']}", file=sys.stderr)
        return 1

    try:
        passages = collect_vehicle_passages(
            mapping, args.net, run_id=RUN_ID, window=window,
            fcd_path=paths["fcd"], tripinfo_path=paths["tripinfo"],
            manifest_path=generated.manifest_file, demand_path=generated.demand_file,
            fcd_period_s=FCD_PERIOD_S,
        )
        queues = collect_cycle_queues(
            mapping, args.net, program, paths["fcd"], run_id=RUN_ID, window=window,
            vehicle_length_m=float(VEHICLE_TYPE["length"]),
        )
    except (VehiclePassageError, CycleQueueError) as exc:
        print(f"FAIL  Measurements could not be taken:\n{exc}", file=sys.stderr)
        return 1

    expected_cycles = int(window.duration_s // program.cycle_length_s)
    lane_ids = [item.lane_id for item in mapping.lane_mappings]

    save(folder / "vehicle_delay_records.json", passages.records)
    save(folder / "incomplete_passages.json", passages.incomplete)
    save(folder / "uninserted_vehicles.json", passages.uninserted)
    save(folder / "cycle_queue_records.json", queues.lanes)
    save(folder / "approach_cycle_queue_records.json", queues.approaches)
    results = evaluate(passages, queues, expected_cycles, lane_ids, mapping, window, returncode, paths)
    summary = {
        "settings": {
            "demand": str(args.demand) if args.demand else f"hand-made, {args.vehicles_per_record} per record",
            "analysis_start": args.analysis_start, "analysis_end": args.analysis_end,
            "step_length_s": args.step_length, "fcd_period_s": FCD_PERIOD_S, "seed": args.seed,
        },
        "records": len(passages.records),
        "incomplete": len(passages.incomplete),
        "uninserted": len(passages.uninserted),
        "uninserted_by_movement": uninserted_by_movement(passages.uninserted),
        "cycle_queues": len(queues.lanes),
        "approach_cycle_queues": len(queues.approaches),
        "results": results,
        "analysis_period_by_movement": movement_summary(passages, window),
        "analysis_period_by_lane": lane_summary(queues.lanes, window),
        "analysis_period_by_approach": approach_summary(queues.approaches, window),
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Measured: {len(passages.records)} complete passages, {len(passages.incomplete)} incomplete, "
          f"{len(passages.uninserted)} never inserted, "
          f"{len(queues.lanes)} lane and {len(queues.approaches)} approach cycle queues")
    for movement_id, count in summary["uninserted_by_movement"].items():
        print(f"INFO  {movement_id}: {count} vehicle(s) never inserted")
    for name, result in results.items():
        details = ", ".join(f"{k}={v}" for k, v in result.items() if k != "passed" and not isinstance(v, list))
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {name}: {details}")
        for key, value in result.items():
            if isinstance(value, list) and value:
                print(f"      {key}: {', '.join(value)}")
    for movement_id, values in summary["analysis_period_by_movement"].items():
        print(f"INFO  {movement_id}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
    for lane_id, values in summary["analysis_period_by_lane"].items():
        print(f"INFO  {lane_id}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
    for approach_id, values in summary["analysis_period_by_approach"].items():
        print(f"INFO  {approach_id}: " + ", ".join(f"{k}={v}" for k, v in values.items()))

    passed = all(result["passed"] for result in results.values())
    print(("All checks passed." if passed else "Some checks failed.") + f" Report: {folder / 'summary.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

"""
Generate SUMO demand, check the files and run them once in SUMO.

By default the demand is hand-made: every demand movement gets the same
number of vehicles in every interval, so a failure points to the demand
generation rather than to the demand. With --demand, the SimulationDemand
records are read from an exported JSON file instead.

The run ends at the end of the clearance. It passes when:

1. SUMO reports no errors;
2. every planned vehicle has been inserted and none is still waiting;
3. every vehicle planned to reach the stop line before the end of the
   analysis period has left the network (an approximation of KPI
   eligibility, see evaluate);
4. there are no teleports and no collisions;
5. at least 95 % of the slip-road vehicles due before the end of the
   analysis period cross the stop line inside their own interval.

Insertion delay is reported but not judged.
"""

import argparse
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Support direct invocation from any working directory without installing Jaadah.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import TypeAdapter

from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import Scenario, SimulationConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.checks import DemandCheckError, check_generated_demand
from jaadah.sumo_demand.planner import (
    DemandPlanningError,
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
    stop_line_edges,
)
from jaadah.sumo_demand.writer import DemandWritingError, write_sumo_demand

DEFAULT_MAPPING = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
DEFAULT_NETWORK = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
DEFAULT_OUTPUT = PROJECT_ROOT / "simulation/outputs/tests/sumo_demand_check"
WARMUP_S = 900
CLEARANCE_S = 900
SLIP_TIMING_SHARE = 0.95


# ============================================================
# DEMAND
# ============================================================

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


def make_window(analysis_start, analysis_end):
    scenario = Scenario(
        scenario_id="SCN_SUMO_DEMAND_CHECK",
        intersection_id="INT_001",
        time_context="historical",
        control_mode="baseline",
        start_time=analysis_start,
        end_time=analysis_end,
    )
    config = SimulationConfig(warmup_duration_s=WARMUP_S, clearance_duration_s=CLEARANCE_S)
    return build_run_window(scenario, config)


# ============================================================
# SUMO RUN
# ============================================================

def run_sumo(sumo_bin, network, route_file, folder, end_s, step_length, seed):
    paths = {
        "log": folder / "sumo.log",
        "statistics": folder / "statistics.xml",
        "tripinfo": folder / "tripinfo.xml",
        "vehroute": folder / "vehroute.xml",
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
        "--log", str(paths["log"]),
        "--statistic-output", str(paths["statistics"]),
        "--tripinfo-output", str(paths["tripinfo"]),
        "--tripinfo-output.write-unfinished", "true",
        "--vehroute-output", str(paths["vehroute"]),
        "--vehroute-output.exit-times", "true",
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    return completed.returncode, paths


# ============================================================
# PASS RULES
# ============================================================

def evaluate(plan, demands, window, free_flow, stop_edges, slip_movements, returncode, paths):
    record_of = {item.demand_id: item for item in demands}
    analysis_end_s = window.to_simulation_seconds(window.analysis_end)
    results = {}

    log_lines = paths["log"].read_text(encoding="utf-8", errors="replace").splitlines()
    errors = [line for line in log_lines if line.startswith("Error")]
    warnings = [line for line in log_lines if line.startswith("Warning")]
    results["1. SUMO reports no errors"] = {
        "passed": returncode == 0 and not errors,
        "errors": errors[:10],
        "warnings": len(warnings),
        "first_warnings": warnings[:10],
    }

    statistics = ET.parse(paths["statistics"]).getroot()
    vehicles = statistics.find("vehicles").attrib
    inserted, waiting = int(vehicles["inserted"]), int(vehicles["waiting"])
    results["2. Every vehicle enters"] = {
        "passed": inserted == len(plan.departures) and waiting == 0,
        "planned": len(plan.departures),
        "inserted": inserted,
        "waiting": waiting,
    }

    trips = {item.get("id"): item.attrib for item in ET.parse(paths["tripinfo"]).getroot().iter("tripinfo")}
    # Smoke-test proxy: "due" uses the planned stop-line time (departure +
    # free-flow time), not the actual measurement-zone entry that decides KPI
    # eligibility. A pass does not show that every KPI-eligible vehicle
    # completed its passage; that needs zone-entry times from the measurement
    # outputs.
    due = [
        item for item in plan.departures
        if item.depart_s + free_flow[record_of[item.demand_id].movement_id] < analysis_end_s
    ]
    unfinished = [
        item.vehicle_id for item in due
        if float(trips.get(item.vehicle_id, {}).get("arrival", -1)) < 0
    ]
    results["3. Vehicles due before the analysis end have left"] = {
        "passed": not unfinished,
        "due": len(due),
        "unfinished": unfinished[:20],
    }

    teleports = int(statistics.find("teleports").get("total"))
    collisions = int(statistics.find("safety").get("collisions"))
    results["4. No teleports and no collisions"] = {
        "passed": teleports == 0 and collisions == 0,
        "teleports": teleports,
        "collisions": collisions,
    }

    exits = {}
    for vehicle in ET.parse(paths["vehroute"]).getroot().iter("vehicle"):
        route = vehicle.find("route")
        if route is not None and route.get("exitTimes"):
            exits[vehicle.get("id")] = dict(zip(route.get("edges").split(), route.get("exitTimes").split()))
    slip_due = [item for item in due if record_of[item.demand_id].movement_id in slip_movements]
    on_time = 0
    late = []
    for item in slip_due:
        record = record_of[item.demand_id]
        crossing = exits.get(item.vehicle_id, {}).get(stop_edges[record.movement_id])
        start_s = window.to_simulation_seconds(record.interval_start)
        end_s = window.to_simulation_seconds(record.interval_end)
        if crossing is not None and start_s <= float(crossing) < end_s:
            on_time += 1
        else:
            late.append(item.vehicle_id)
    share = on_time / len(slip_due) if slip_due else 1.0
    results["5. Slip-road vehicles cross in their interval"] = {
        "passed": share >= SLIP_TIMING_SHARE,
        "slip_vehicles": len(slip_due),
        "in_interval": on_time,
        "share": round(share, 4),
        "required_share": SLIP_TIMING_SHARE,
        "outside_interval": late[:20],
    }

    delays = [float(item["departDelay"]) for item in trips.values() if float(item.get("depart", -1)) >= 0]
    report = {
        "vehicles": len(delays),
        "mean_s": round(sum(delays) / len(delays), 2) if delays else None,
        "max_s": round(max(delays), 2) if delays else None,
        "over_1_s": sum(1 for value in delays if value > 1.0),
    }
    return results, report


# ============================================================
# MAIN
# ============================================================

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
        free_flow = compute_free_flow_times(mapping, args.net)
        plan = plan_departures(
            demands,
            window=window,
            routes=movement_routes(mapping),
            expected_movements=movements,
            free_flow_s=free_flow,
            seed=args.seed,
        )
        generated = write_sumo_demand(plan, demands, mapping, args.out)
        summary = check_generated_demand(
            args.out, mapping, args.net, window=window, seed=args.seed
        )
    except (DemandPlanningError, DemandWritingError, DemandCheckError, ValueError, OSError) as exc:
        print(f"Cannot run the check:\n{exc}", file=sys.stderr)
        return 2
    print(f"Generated and checked: {summary.records} records, {summary.vehicles} vehicles, {summary.routes} routes")

    folder = generated.route_file.parent
    returncode, paths = run_sumo(
        args.sumo_bin, args.net, generated.route_file, folder,
        window.duration_s, args.step_length, args.seed,
    )
    if not paths["statistics"].is_file():
        print(f"SUMO did not produce its outputs (exit code {returncode}); see {paths['log']}", file=sys.stderr)
        return 1

    slip_movements = {
        item.movement_id for item in mapping.movement_mappings
        if not item.signal_controlled and item.movement_id in movements
    }
    results, insertion_delay = evaluate(
        plan, demands, window, free_flow, stop_line_edges(mapping, args.net),
        slip_movements, returncode, paths,
    )

    for name, result in results.items():
        details = ", ".join(
            f"{key}={value}" for key, value in result.items()
            if key != "passed" and not isinstance(value, list)
        )
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {name}: {details}")
        for key, value in result.items():
            if isinstance(value, list) and value:
                print(f"      {key}: {', '.join(map(str, value))}")
    print(
        f"INFO  Insertion delay: mean {insertion_delay['mean_s']} s, "
        f"max {insertion_delay['max_s']} s, {insertion_delay['over_1_s']} vehicles over 1 s"
    )

    report = {
        "settings": {
            "demand": str(args.demand) if args.demand else f"hand-made, {args.vehicles_per_record} per record",
            "analysis_start": args.analysis_start,
            "analysis_end": args.analysis_end,
            "step_length_s": args.step_length,
            "seed": args.seed,
        },
        "files": generated.model_dump(mode="json"),
        "results": results,
        "insertion_delay": insertion_delay,
    }
    report_path = folder / "summary.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    passed = all(item["passed"] for item in results.values())
    print(f"{'All checks passed' if passed else 'Some checks failed'}. Report: {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

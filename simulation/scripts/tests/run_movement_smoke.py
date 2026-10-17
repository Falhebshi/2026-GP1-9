import argparse
import hashlib
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
DEFAULT_NETWORK = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
DEFAULT_OUTPUT = PROJECT_ROOT / "simulation/outputs/tests/movement_smoke"


def require_mapping(mapping_path: Path, network_path: Path) -> list[dict]:
    with mapping_path.open("r", encoding="utf-8") as file:
        mapping = json.load(file)

    actual_hash = hashlib.sha256(network_path.read_bytes()).hexdigest()
    if actual_hash.lower() != mapping["network"]["sha256"].lower():
        raise ValueError("Network SHA-256 differs from mapping JSON. Review mappings before testing.")

    movements = mapping["movement_mappings"]
    if len(movements) != 18 or len({m["movement_id"] for m in movements}) != 18:
        raise ValueError("Expected 18 unique movement mappings.")

    for movement in movements:
        if not movement["sumo_route_edge_ids"]:
            raise ValueError(f"Empty route: {movement['movement_id']}")

    return movements


def write_vehicle_route(movement: dict, output_file: Path) -> None:
    root = ET.Element("routes")
    vehicle = ET.SubElement(
        root,
        "vehicle",
        {
            "id": movement["movement_id"],
            "depart": "0",
            "departLane": "best",
            "departSpeed": "0",
        },
    )
    ET.SubElement(vehicle, "route", {"edges": " ".join(movement["sumo_route_edge_ids"])})
    ET.ElementTree(root).write(output_file, encoding="utf-8", xml_declaration=True)


def run_one(
    sumo_bin: str,
    network_path: Path,
    movement: dict,
    output_dir: Path,
    end_time: float,
) -> dict:
    """Run an isolated TraCI simulation and check real arrival and teleport events."""
    import traci

    movement_id = movement["movement_id"]
    case_dir = output_dir / movement_id
    case_dir.mkdir(parents=True, exist_ok=True)

    route_file = case_dir / "vehicle.rou.xml"
    log_file = case_dir / "sumo.log"
    write_vehicle_route(movement, route_file)

    command = [
        sumo_bin,
        "--net-file", str(network_path.resolve()),
        "--route-files", str(route_file.resolve()),
        "--log", str(log_file.resolve()),
        "--begin", "0",
        "--step-length", "0.2",
        "--seed", "42",
        "--time-to-teleport", "-1",
        "--no-step-log", "true",
    ]

    arrived = False
    teleported = False
    departed = False
    simulation_time = 0.0
    error = None
    started = False

    try:
        traci.start(command)
        started = True

        while traci.simulation.getMinExpectedNumber() > 0 and simulation_time < end_time:
            traci.simulationStep()
            simulation_time = traci.simulation.getTime()

            if movement_id in traci.simulation.getDepartedIDList():
                departed = True
            if movement_id in traci.simulation.getArrivedIDList():
                arrived = True
            if (
                movement_id in traci.simulation.getStartingTeleportIDList()
                or movement_id in traci.simulation.getEndingTeleportIDList()
            ):
                teleported = True

        if not arrived and not teleported:
            error = "Vehicle did not arrive before the deadline or simulation ended"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if started:
            try:
                traci.close()
            except Exception as exc:
                error = error or f"TraCI close failed: {exc}"

    passed = arrived and departed and not teleported and error is None
    return {
        "movement_id": movement_id,
        "passed": passed,
        "departed": departed,
        "arrived": arrived,
        "teleported": teleported,
        "simulation_time": simulation_time,
        "error": error,
        "log": str(log_file),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--net", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sumo-bin", default="sumo")
    parser.add_argument("--end", type=float, default=1200)
    args = parser.parse_args()

    if args.end <= 0:
        parser.error("--end must be positive")
    if not args.mapping.is_file() or not args.net.is_file():
        parser.error("Mapping JSON or SUMO network not found.")
    if shutil.which(args.sumo_bin) is None:
        parser.error("SUMO executable not found. Supply --sumo-bin with the path to sumo.exe.")
    try:
        import traci  # noqa: F401
    except ImportError:
        parser.error("TraCI is unavailable. Install the SUMO traci Python package.")

    try:
        movements = require_mapping(args.mapping, args.net)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for movement in movements:
        result = run_one(args.sumo_bin, args.net, movement, args.out, args.end)
        results.append(result)
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['movement_id']}: "
              f"arrived={result['arrived']}, teleported={result['teleported']}"
              + (f", error={result['error']}" if result["error"] else ""))

    summary_path = args.out / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    count = sum(item["passed"] for item in results)
    print(f"Completed {count}/{len(results)} movement tests. Report: {summary_path}")
    return 0 if count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

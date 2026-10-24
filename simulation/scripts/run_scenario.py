import hashlib
from collections.abc import Iterable
from pathlib import Path
import xml.etree.ElementTree as ET

from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import ControlMode, Scenario, SimulationConfig, SimulationRun, SimulationRunStatus
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.checks import check_generated_demand
from jaadah.sumo_demand.planner import (
    build_run_window, compute_free_flow_times, demand_movement_ids,
    movement_routes, plan_departures,
)
from jaadah.sumo_demand.writer import GeneratedDemand, write_sumo_demand
from simulation.scripts.run_simulation import run_simulation


def _sumo_input_filename(path: Path) -> str:
    filename = str(path)
    # SUMO expands ${...} and splits comma-separated file lists after reading the config.
    if "${" in filename or "," in filename:
        raise ValueError(f"SUMO input path contains a filename substitution or comma: {filename}")
    return filename


def _validate_baseline_run(scenario: Scenario, run: SimulationRun) -> None:
    if run.scenario_id != scenario.scenario_id:
        raise ValueError("SimulationRun belongs to a different scenario")
    if run.status != SimulationRunStatus.PENDING or run.started_at is not None:
        raise ValueError("Scenario execution requires a pending, unstarted run")
    if scenario.control_mode != ControlMode.BASELINE:
        raise ValueError("Intervention scenario execution requires a signal-control configuration; only baseline scenarios are supported")


def execute_scenario(
    scenario: Scenario,
    simulation_config: SimulationConfig,
    run: SimulationRun,
    generated: GeneratedDemand,
    *,
    mapping_path: str | Path,
    network_path: str | Path,
    run_dir: str | Path,
    sumo_bin: str = "sumo",
) -> dict:
    """Validate generated demand, then execute one continuous SUMO run."""
    _validate_baseline_run(scenario, run)

    network_path = Path(network_path).expanduser().resolve()
    network_filename = _sumo_input_filename(network_path)
    mapping = load_network_mappings(mapping_path, network_path=network_path)
    if scenario.intersection_id != mapping.intersection_mapping.intersection_id:
        raise ValueError("Scenario intersection does not match the network mapping")
    if run.network_version != mapping.network.version:
        raise ValueError("SimulationRun network version does not match the mapping")
    if run.mapping_version is not None and run.mapping_version != mapping.mapping_version:
        raise ValueError("SimulationRun mapping version does not match the mapping")

    window = build_run_window(scenario, simulation_config)
    demand_dir = generated.route_file.expanduser().resolve().parent
    prefix = demand_dir.name
    expected_files = {
        "route_file": demand_dir / f"{prefix}_routes.rou.xml",
        "manifest_file": demand_dir / f"{prefix}_manifest.json",
        "demand_file": demand_dir / f"{prefix}_demand.json",
    }
    for name, expected in expected_files.items():
        if getattr(generated, name).expanduser().resolve() != expected:
            raise ValueError(f"Generated demand {name} does not match its validated folder")
    route_filename = _sumo_input_filename(expected_files["route_file"])

    check_generated_demand(
        demand_dir, mapping, network_path, window=window, seed=run.random_seed
    )
    # Verify that the files still match the fingerprints supplied by demand generation.
    for name, fingerprint in (
        ("route_file", generated.route_file_sha256),
        ("manifest_file", generated.manifest_sha256),
        ("demand_file", generated.demand_sha256),
    ):
        if hashlib.sha256(expected_files[name].read_bytes()).hexdigest() != fingerprint:
            raise ValueError(f"Generated demand {name} changed after it was written")
    if run.demand_sha256 is not None and run.demand_sha256.lower() != generated.demand_sha256.lower():
        raise ValueError("SimulationRun demand fingerprint does not match generated demand")
    if run.route_file_sha256 is not None and run.route_file_sha256.lower() != generated.route_file_sha256.lower():
        raise ValueError("SimulationRun route fingerprint does not match generated demand")

    run_dir = Path(run_dir).expanduser().resolve()
    _sumo_input_filename(run_dir / "scenario.sumocfg")
    run_dir.mkdir(parents=True, exist_ok=False)
    config_path = run_dir / "scenario.sumocfg"
    config = ET.Element("configuration")
    inputs = ET.SubElement(config, "input")
    ET.SubElement(inputs, "net-file", value=network_filename)
    ET.SubElement(inputs, "route-files", value=route_filename)
    config_path.write_bytes(ET.tostring(config, encoding="utf-8", xml_declaration=True))

    execution = run_simulation(
        config_path,
        sumo_bin=sumo_bin,
        end_time_s=window.duration_s,
        seed=run.random_seed,
        step_length_s=run.step_length_s,
    )
    return {
        "run_id": run.run_id,
        "scenario_id": scenario.scenario_id,
        "window_epoch": window.epoch.isoformat(),
        "analysis_start": window.analysis_start.isoformat(),
        "analysis_end": window.analysis_end.isoformat(),
        "config_path": str(config_path),
        "route_file": str(expected_files["route_file"]),
        "provenance": {
            "mapping_version": mapping.mapping_version,
            "demand_sha256": generated.demand_sha256,
            "route_file_sha256": generated.route_file_sha256,
        },
        "execution": execution,
    }


def generate_and_execute_scenario(
    scenario: Scenario,
    simulation_config: SimulationConfig,
    run: SimulationRun,
    demands: Iterable[SimulationDemand],
    *,
    mapping_path: str | Path,
    network_path: str | Path,
    demand_dir: str | Path,
    run_dir: str | Path,
    sumo_bin: str = "sumo",
) -> dict:
    """Generate demand in a fresh folder and execute one baseline scenario."""
    _validate_baseline_run(scenario, run)
    network_path = Path(network_path).expanduser().resolve()
    demand_dir = Path(demand_dir).expanduser().resolve()
    run_dir = Path(run_dir).expanduser().resolve()

    if demand_dir == run_dir or demand_dir in run_dir.parents or run_dir in demand_dir.parents:
        raise ValueError("Demand and run directories must be separate and non-overlapping")
    if demand_dir.exists():
        raise FileExistsError(f"Demand directory already exists: {demand_dir}")
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    _sumo_input_filename(network_path)
    _sumo_input_filename(demand_dir / f"{demand_dir.name}_routes.rou.xml")
    _sumo_input_filename(run_dir / "scenario.sumocfg")

    mapping = load_network_mappings(mapping_path, network_path=network_path)
    if scenario.intersection_id != mapping.intersection_mapping.intersection_id:
        raise ValueError("Scenario intersection does not match the network mapping")
    if run.network_version != mapping.network.version:
        raise ValueError("SimulationRun network version does not match the mapping")
    if run.mapping_version is not None and run.mapping_version != mapping.mapping_version:
        raise ValueError("SimulationRun mapping version does not match the mapping")

    window = build_run_window(scenario, simulation_config)
    demands = list(demands)
    plan = plan_departures(
        demands,
        window=window,
        routes=movement_routes(mapping),
        expected_movements=demand_movement_ids(mapping),
        free_flow_s=compute_free_flow_times(mapping, network_path),
        seed=run.random_seed,
    )

    demand_dir.mkdir(parents=True, exist_ok=False)
    generated = write_sumo_demand(plan, demands, mapping, demand_dir)

    result = execute_scenario(
        scenario, simulation_config, run, generated,
        mapping_path=mapping_path, network_path=network_path,
        run_dir=run_dir, sumo_bin=sumo_bin,
    )
    return {"generated_demand": generated, "scenario_execution": result}

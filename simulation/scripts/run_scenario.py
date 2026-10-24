import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import ControlMode, Scenario, SimulationConfig, SimulationRun, SimulationRunStatus
from jaadah.sumo_demand.checks import check_generated_demand
from jaadah.sumo_demand.planner import build_run_window
from jaadah.sumo_demand.writer import GeneratedDemand
from simulation.scripts.run_simulation import run_simulation


def _sumo_input_filename(path: Path) -> str:
    filename = str(path)
    # SUMO expands ${...} and splits comma-separated file lists after reading the config.
    if "${" in filename or "," in filename:
        raise ValueError(f"SUMO input path contains a filename substitution or comma: {filename}")
    return filename


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
    if run.scenario_id != scenario.scenario_id:
        raise ValueError("SimulationRun belongs to a different scenario")
    if run.status != SimulationRunStatus.PENDING or run.started_at is not None:
        raise ValueError("Scenario execution requires a pending, unstarted run")
    if scenario.control_mode != ControlMode.BASELINE:
        raise ValueError("Intervention scenario execution requires a signal-control configuration; only baseline scenarios are supported")

    network_path = Path(network_path).expanduser().resolve()
    network_filename = _sumo_input_filename(network_path)
    mapping = load_network_mappings(mapping_path, network_path=network_path)
    if scenario.intersection_id != mapping.intersection_mapping.intersection_id:
        raise ValueError("Scenario intersection does not match the network mapping")
    if run.network_version != mapping.network.version:
        raise ValueError("SimulationRun network version does not match the mapping")

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

    run_dir = Path(run_dir).expanduser().resolve()
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

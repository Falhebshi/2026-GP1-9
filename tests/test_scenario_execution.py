import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from jaadah.models.scenario import ControlMode, Scenario, SimulationConfig, SimulationRun
from jaadah.sumo_demand.checks import DemandCheckError
from jaadah.sumo_demand.writer import GeneratedDemand
from simulation.scripts import run_scenario


RIYADH = timezone(timedelta(hours=3))


@pytest.fixture
def case(tmp_path, monkeypatch):
    scenario = Scenario(
        scenario_id="SCN_1", intersection_id="INT_1", time_context="historical",
        control_mode="baseline", start_time=datetime(2026, 10, 20, 8, tzinfo=RIYADH),
        end_time=datetime(2026, 10, 20, 9, tzinfo=RIYADH),
    )
    config = SimulationConfig(warmup_duration_s=900, clearance_duration_s=900)
    run = SimulationRun(
        run_id="RUN_1", scenario_id="SCN_1", random_seed=42,
        network_version="network-v1", sumo_version="SUMO 1.27.1",
        step_length_s=0.4, status="pending",
    )
    network = tmp_path / "network.net.xml"
    network.write_text("<net/>")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text("{}")
    mapping = SimpleNamespace(
        mapping_version="mapping-v2", network=SimpleNamespace(version="network-v1"),
        intersection_mapping=SimpleNamespace(intersection_id="INT_1"),
    )
    load = []
    monkeypatch.setattr(run_scenario, "load_network_mappings", lambda *a, **k: load.append((a, k)) or mapping)
    checks = []
    monkeypatch.setattr(run_scenario, "check_generated_demand", lambda *a, **k: checks.append((a, k)))
    executions = []
    summary = {"status": "completed", "steps": 13500, "final_time_s": 5400.0}

    def run_once(*args, **kwargs):
        executions.append((args, kwargs))
        assert len(executions) == 1
        return summary

    monkeypatch.setattr(run_scenario, "run_simulation", run_once)
    demand_dir = tmp_path / "demand"
    demand_dir.mkdir()
    files = {
        "route_file": demand_dir / "demand_routes.rou.xml",
        "manifest_file": demand_dir / "demand_manifest.json",
        "demand_file": demand_dir / "demand_demand.json",
    }
    for name, path in files.items():
        path.write_text(name)
    generated = GeneratedDemand(
        **files,
        route_file_sha256=hashlib.sha256(files["route_file"].read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(files["manifest_file"].read_bytes()).hexdigest(),
        demand_sha256=hashlib.sha256(files["demand_file"].read_bytes()).hexdigest(),
    )
    return SimpleNamespace(
        scenario=scenario, config=config, run=run, generated=generated,
        mapping_path=mapping_path, network=network, run_dir=tmp_path / "run",
        mapping=mapping, load=load, checks=checks, executions=executions,
        summary=summary, files=files,
    )


def execute(case):
    return run_scenario.execute_scenario(
        case.scenario, case.config, case.run, case.generated,
        mapping_path=case.mapping_path, network_path=case.network,
        run_dir=case.run_dir,
    )


def test_execution_uses_validated_artifacts_and_full_window(case):
    before = {name: path.read_bytes() for name, path in case.files.items()}
    result = execute(case)
    assert result["execution"] is case.summary
    assert result["window_epoch"] == "2026-10-20T07:45:00+03:00"
    assert result["analysis_start"] == "2026-10-20T08:00:00+03:00"
    assert result["provenance"] == {
        "mapping_version": "mapping-v2",
        "demand_sha256": case.generated.demand_sha256,
        "route_file_sha256": case.generated.route_file_sha256,
    }
    assert case.load == [((case.mapping_path,), {"network_path": case.network.resolve()})]
    assert len(case.checks) == len(case.executions) == 1
    check_args, check_kwargs = case.checks[0]
    assert check_args == (case.generated.route_file.parent, case.mapping, case.network.resolve())
    assert check_kwargs["window"].duration_s == 5400
    assert check_kwargs["seed"] == 42
    args, kwargs = case.executions[0]
    assert args == (case.run_dir / "scenario.sumocfg",)
    assert kwargs == {"sumo_bin": "sumo", "end_time_s": 5400,
                      "seed": 42, "step_length_s": 0.4}
    root = ET.parse(args[0]).getroot()
    assert root.find("input/net-file").get("value") == str(case.network.resolve())
    assert root.find("input/route-files").get("value") == str(case.generated.route_file)
    assert [child.tag for child in root.find("input")] == ["net-file", "route-files"]
    assert len(root) == 1
    assert {name: path.read_bytes() for name, path in case.files.items()} == before


@pytest.mark.parametrize("change, message", [
    ({"scenario_id": "OTHER"}, "different scenario"),
    ({"status": "completed", "started_at": datetime(2026, 10, 20, tzinfo=RIYADH)}, "pending"),
    ({"network_version": "OTHER"}, "network version"),
])
def test_invalid_run_cannot_start(case, change, message):
    case.run = case.run.model_copy(update=change)
    with pytest.raises(ValueError, match=message):
        execute(case)
    assert not case.checks and not case.executions and not case.run_dir.exists()


def test_wrong_intersection_cannot_start(case):
    case.mapping.intersection_mapping.intersection_id = "OTHER"
    with pytest.raises(ValueError, match="intersection"):
        execute(case)
    assert not case.executions


def test_intervention_is_rejected_before_execution_side_effects(case):
    case.scenario = Scenario(**{
        **case.scenario.model_dump(),
        "control_mode": ControlMode.INTERVENTION,
        "reference_scenario_id": "SCN_BASELINE",
    })
    with pytest.raises(ValueError, match="Intervention scenario execution requires a signal-control configuration"):
        execute(case)
    assert not case.load and not case.checks and not case.executions
    assert not case.run_dir.exists()


@pytest.mark.parametrize("directory_name", ["d_${JAADAH_REVIEW_PATH}", "d,extra"])
def test_sumo_route_filename_interpretation_cannot_change_validated_input(case, monkeypatch, directory_name):
    demand_dir = case.run_dir.parent / directory_name
    demand_dir.mkdir()
    files = {
        "route_file": demand_dir / f"{directory_name}_routes.rou.xml",
        "manifest_file": demand_dir / f"{directory_name}_manifest.json",
        "demand_file": demand_dir / f"{directory_name}_demand.json",
    }
    for name, path in files.items():
        path.write_bytes(case.files[name].read_bytes())
    case.generated = GeneratedDemand(
        **files,
        route_file_sha256=hashlib.sha256(files["route_file"].read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(files["manifest_file"].read_bytes()).hexdigest(),
        demand_sha256=hashlib.sha256(files["demand_file"].read_bytes()).hexdigest(),
    )
    monkeypatch.setenv("JAADAH_REVIEW_PATH", "replacement")
    alternative = case.run_dir.parent / "d_replacement"
    alternative.mkdir()
    alternative_route = alternative / "d_replacement_routes.rou.xml"
    alternative_route.write_text(
        '<routes><route id="other" edges="a b"/>'
        '<vehicle id="UNVALIDATED_VEHICLE" route="other" depart="0"/></routes>'
    )
    before = alternative_route.read_bytes()

    with pytest.raises(ValueError, match="filename substitution or comma"):
        execute(case)
    assert alternative_route.read_bytes() == before
    assert not case.checks and not case.executions and not case.run_dir.exists()


@pytest.mark.parametrize("directory_name", ["n_${JAADAH_REVIEW_PATH}", "n,extra"])
def test_sumo_network_filename_interpretation_is_rejected(case, directory_name):
    network_dir = case.run_dir.parent / directory_name
    network_dir.mkdir()
    case.network = network_dir / "network.net.xml"
    case.network.write_text("<net/>")
    with pytest.raises(ValueError, match="filename substitution or comma"):
        execute(case)
    assert not case.load and not case.checks and not case.executions
    assert not case.run_dir.exists()


def test_generated_demand_failure_prevents_config_and_launch(case, monkeypatch):
    def fail(*args, **kwargs):
        raise DemandCheckError(["stale window or seed"])
    monkeypatch.setattr(run_scenario, "check_generated_demand", fail)
    with pytest.raises(DemandCheckError, match="stale window or seed"):
        execute(case)
    assert not case.run_dir.exists() and not case.executions


@pytest.mark.parametrize("name", ["route_file", "manifest_file", "demand_file"])
def test_changed_generated_file_is_rejected(case, name):
    case.files[name].write_bytes(case.files[name].read_bytes() + b"\n")
    with pytest.raises(ValueError, match=f"{name} changed"):
        execute(case)
    assert not case.run_dir.exists() and not case.executions


def test_missing_generated_file_prevents_launch(case):
    case.files["manifest_file"].unlink()
    with pytest.raises(FileNotFoundError):
        execute(case)
    assert not case.run_dir.exists() and not case.executions


def test_mismatched_artifact_reference_is_rejected(case):
    other = case.generated.model_copy(update={"route_file": case.files["route_file"].parent / "other.rou.xml"})
    case.generated = other
    with pytest.raises(ValueError, match="validated folder"):
        execute(case)
    assert not case.checks and not case.executions


def test_existing_run_directory_is_not_reused(case):
    case.run_dir.mkdir()
    (case.run_dir / "scenario.sumocfg").write_text("preserve")
    with pytest.raises(FileExistsError):
        execute(case)
    assert (case.run_dir / "scenario.sumocfg").read_text() == "preserve"
    assert not case.executions


def test_runner_failure_summary_is_returned(case):
    case.summary["status"] = "failed"
    case.summary["error"] = "TraCI connection failed"
    assert execute(case)["execution"] is case.summary

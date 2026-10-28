import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from simulation.scripts import sumo_config_validator as validator


SCRIPT = Path(__file__).resolve().parents[1] / "simulation/scripts/run_simulation.py"
spec = importlib.util.spec_from_file_location("simulation_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


# Minimal SUMO-exported option metadata. Individual tests can extend it to
# verify that new output options are discovered without a runner allowlist.
TEMPLATE = '''<sumoConfiguration>
  <configuration><save-template type="FILE"/><save-schema type="FILE"/>
    <save-configuration type="FILE" synonymes="C save-config"/></configuration>
  <input><net-file type="FILE"/><route-files type="FILE"/>
    <additional-files type="FILE"/><load-state type="FILE"/></input>
  <output><summary-output type="FILE"/><tripinfo-output type="FILE"/>
    <fcd-output.filter-edges.input-file type="FILE"/><save-state.files type="FILE"/>
    <save-state.prefix type="FILE"/><vtk-output type="FILE"/>
    <output-prefix type="STR"/><output-suffix type="STR"/></output>
  <report><log type="FILE"/></report>
  <processing><lanechange.duration type="TIME"/></processing>
</sumoConfiguration>'''


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    config = tmp_path / "test.sumocfg"
    config.write_text('<configuration><time><end value="2"/><step-length value="0.4"/></time></configuration>')
    monkeypatch.setattr(validator.shutil, "which", lambda executable: str(executable))
    return config


@pytest.fixture
def runtime(configuration, monkeypatch):
    process = Mock(returncode=None)
    process.poll.return_value = None

    def wait(timeout):
        process.returncode = 0
        return 0

    process.wait.side_effect = wait
    state = SimpleNamespace(time=0.0, remaining=0)
    connection = Mock()
    connection.getVersion.return_value = (22, "SUMO 1.27.1")
    connection.simulation.getTime.side_effect = lambda: state.time
    connection.simulation.getDeltaT.return_value = 0.4
    connection.simulation.getMinExpectedNumber.side_effect = lambda: state.remaining

    def step():
        state.time = round(state.time + 0.4, 3)

    connection.simulationStep.side_effect = step
    connection.vehicle.getIDList.return_value = []
    popen = Mock(return_value=process)
    connect = Mock(return_value=connection)
    monkeypatch.setattr(runner, "getFreeSocketPort", lambda: 43210)
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.traci, "connect", connect)
    def inspect(command):
        if "--save-template" in command:
            return validator.ET.fromstring(TEMPLATE)
        return validator.ET.parse(command[command.index("-c") + 1]).getroot()
    monkeypatch.setattr(validator, "_sumo_xml", inspect)
    return SimpleNamespace(config=configuration, process=process, connection=connection,
                           state=state, popen=popen, connect=connect)


def test_empty_network_runs_to_deadline_once(runtime):
    result = runner.run_simulation(runtime.config, seed=42)
    assert result == {
        "status": "completed", "final_time_s": 2.0, "steps": 5,
        "remaining_expected_vehicles": 0, "error": None, "cleanup_errors": [],
        "sumo_version": "SUMO 1.27.1", "traci_api_version": 22,
        "end_time_s": 2.0, "step_length_s": 0.4, "seed": 42,
    }
    runtime.popen.assert_called_once()
    runtime.connect.assert_called_once_with(port=43210, host="127.0.0.1", proc=runtime.process,
                                           numRetries=20, waitBetweenRetries=0.1)
    runtime.connection.close.assert_called_once_with(wait=False)
    runtime.process.wait.assert_called_once_with(timeout=5.0)
    runtime.process.terminate.assert_not_called()


def test_stops_with_vehicles_remaining_and_propagates_overrides(runtime):
    runtime.state.remaining = 7
    result = runner.run_simulation(runtime.config, end_time_s=1.2, step_length_s=0.4, seed=81)
    assert result["status"] == "completed"
    assert (result["steps"], result["final_time_s"], result["remaining_expected_vehicles"]) == (3, 1.2, 7)
    command = runtime.popen.call_args.args[0]
    for flag, value in (("--begin", "0"), ("--end", "1.2"), ("--step-length", "0.4"),
                        ("--seed", "81"), ("--remote-port", "43210"), ("--random", "false")):
        assert command[command.index(flag) + 1] == value
    assert "--lanechange.duration" not in command
    assert "--lcSpeedGain" not in command


@pytest.mark.parametrize("kwargs", [
    {"end_time_s": 1.0}, {"end_time_s": 0}, {"end_time_s": float("nan")},
    {"end_time_s": float("inf")}, {"end_time_s": True},
    {"step_length_s": 0}, {"step_length_s": -1}, {"step_length_s": 0.0004},
    {"step_length_s": float("nan")}, {"step_length_s": True},
    {"seed": -1}, {"seed": True}, {"seed": 1.5}, {"seed": 2147483648},
    {"shutdown_timeout_s": 0}, {"shutdown_timeout_s": float("inf")},
    {"allow_overwrite": "false"},
])
def test_invalid_parameters_never_launch(runtime, kwargs):
    result = runner.run_simulation(runtime.config, **kwargs)
    assert result["status"] == "failed" and result["error"]
    runtime.popen.assert_not_called()


@pytest.mark.parametrize("content", ["not xml", "<routes/>", "<configuration/>",
                                     '<configuration><time><end value="bad"/></time></configuration>'])
def test_invalid_config_never_launches(runtime, content):
    runtime.config.write_text(content)
    assert runner.run_simulation(runtime.config)["status"] == "failed"
    runtime.popen.assert_not_called()


def test_missing_config_and_executable(runtime, monkeypatch):
    assert "FileNotFoundError" in runner.run_simulation(runtime.config.with_name("absent"))["error"]
    monkeypatch.setattr(validator.shutil, "which", lambda executable: None)
    assert "executable not found" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_config_defaults_and_explicit_override(configuration):
    configuration.write_text('<configuration><time><end value="3"/></time>'
                             '<random_number><seed value="123"/><random value="true"/></random_number></configuration>')
    command = runner.build_sumo_command(configuration, sumo_bin="sumo", end_time_s=None,
                                        seed=None, step_length_s=None)
    assert command[command.index("--step-length") + 1] == "1"
    assert command[command.index("--seed") + 1] == "123"
    assert command[command.index("--random") + 1] == "false"


def test_prepared_execution_reuses_validated_settings(configuration):
    prepared = runner.prepare_execution(
        configuration, sumo_bin="sumo", end_time_s=1.2,
        seed=" 42 ", step_length_s=0.4,
    )
    assert (prepared["end_time_s"], prepared["step_length_s"],
            prepared["total_steps"], prepared["seed"]) == (1.2, 0.4, 3, 42)
    assert prepared["command"][prepared["command"].index("--seed") + 1] == "42"


@pytest.mark.parametrize("seed", ["+42", "042", 42.0, True])
def test_prepared_execution_keeps_seed_representation_rules(configuration, seed):
    with pytest.raises(ValueError):
        runner.prepare_execution(
            configuration, sumo_bin="sumo", end_time_s=None,
            seed=seed, step_length_s=None,
        )


def test_sumo_xml_reads_inspection_output(monkeypatch):
    xml = '<sumoConfiguration><output><summary-output value="é_result.xml"/></output></sumoConfiguration>'
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=xml.encode("utf-8"), stderr=b""))
    monkeypatch.setattr(validator.subprocess, "run", run)
    result = validator._sumo_xml(["sumo", "--save-template", "stdout"])
    assert result.find("output/summary-output").get("value") == "é_result.xml"
    run.assert_called_once_with(["sumo", "--save-template", "stdout"],
                                capture_output=True, timeout=10)


def test_sumo_xml_reports_inspection_failure(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad config\n"))
    monkeypatch.setattr(validator.subprocess, "run", run)
    with pytest.raises(ValueError, match="SUMO configuration inspection failed: bad config"):
        validator._sumo_xml(["sumo", "--save-configuration", "stdout"])


def test_sumo_xml_handles_invalid_utf8_diagnostic_and_invalid_xml(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad \xff input"))
    monkeypatch.setattr(validator.subprocess, "run", run)
    with pytest.raises(ValueError, match="bad .* input"):
        validator._sumo_xml(["sumo", "--save-configuration", "stdout"])
    run.return_value = SimpleNamespace(returncode=0, stdout=b"<broken", stderr=b"")
    with pytest.raises(validator.ET.ParseError):
        validator._sumo_xml(["sumo", "--save-configuration", "stdout"])


def test_process_start_failure(runtime):
    runtime.popen.side_effect = OSError("cannot launch")
    result = runner.run_simulation(runtime.config)
    assert "cannot launch" in result["error"]
    runtime.connect.assert_not_called()


def test_connection_failure_terminates_owned_child(runtime):
    runtime.connect.side_effect = RuntimeError("cannot connect")
    runtime.process.wait.side_effect = [subprocess.TimeoutExpired("sumo", 5), 0]
    result = runner.run_simulation(runtime.config)
    assert "cannot connect" in result["error"]
    assert result["final_time_s"] is None
    runtime.process.terminate.assert_called_once()
    runtime.connection.close.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError("step failed"), KeyboardInterrupt()])
def test_step_failure_preserves_last_observation_and_closes(runtime, failure):
    original_step = runtime.connection.simulationStep.side_effect

    def step():
        if runtime.state.time:
            raise failure
        original_step()

    runtime.connection.simulationStep.side_effect = step
    result = runner.run_simulation(runtime.config)
    assert result["status"] == "failed"
    assert type(failure).__name__ in result["error"]
    assert result["steps"] == 1 and result["final_time_s"] == 0.4
    runtime.connection.close.assert_called_once_with(wait=False)


def test_unexpected_process_exit(runtime):
    runtime.process.poll.return_value = 9
    runtime.process.returncode = 9
    assert "exited unexpectedly" in runner.run_simulation(runtime.config)["error"]
    runtime.connection.simulationStep.assert_not_called()


def test_cleanup_failure_does_not_hide_runtime_error(runtime):
    runtime.connection.simulationStep.side_effect = RuntimeError("original error")
    runtime.connection.close.side_effect = RuntimeError("close error")
    result = runner.run_simulation(runtime.config)
    assert "original error" in result["error"]
    assert any("close error" in error for error in result["cleanup_errors"])


def test_close_failure_marks_completed_steps_failed(runtime):
    runtime.connection.close.side_effect = RuntimeError("close error")
    result = runner.run_simulation(runtime.config)
    assert result["status"] == "failed" and result["steps"] == 5
    assert "close error" in result["error"]


def test_shutdown_escalates_to_kill_and_reaps(runtime):
    runtime.process.wait.side_effect = [subprocess.TimeoutExpired("sumo", 5),
                                        subprocess.TimeoutExpired("sumo", 5), 0]
    result = runner.run_simulation(runtime.config)
    assert result["status"] == "failed"
    runtime.process.terminate.assert_called_once()
    runtime.process.kill.assert_called_once()
    assert runtime.process.wait.call_count == 3


def test_blocked_close_is_released_by_watchdog(runtime):
    killed = threading.Event()
    runtime.process.kill.side_effect = killed.set
    runtime.connection.close.side_effect = lambda **kwargs: killed.wait(2)
    result = runner.run_simulation(runtime.config, shutdown_timeout_s=0.02)
    assert killed.is_set()
    assert "TraCI shutdown timed out" in result["cleanup_errors"]
    assert result["status"] == "failed"


def test_wrong_runtime_step_is_rejected(runtime):
    runtime.connection.simulation.getDeltaT.return_value = 1
    assert "begin/step" in runner.run_simulation(runtime.config)["error"]
    runtime.connection.simulationStep.assert_not_called()


def test_full_window_crosses_interval_boundaries_without_restart(runtime):
    result = runner.run_simulation(runtime.config, end_time_s=5400)
    assert result["status"] == "completed"
    assert result["final_time_s"] == 5400 and result["steps"] == 13500
    runtime.popen.assert_called_once()
    runtime.connect.assert_called_once()


def test_version_handshake_failure_closes_connection(runtime):
    runtime.connection.getVersion.side_effect = RuntimeError("handshake failed")
    result = runner.run_simulation(runtime.config)
    assert "handshake failed" in result["error"]
    runtime.connection.close.assert_called_once_with(wait=False)
    runtime.process.wait.assert_called_once()


def test_connection_interruption_cleans_child(runtime):
    runtime.connect.side_effect = KeyboardInterrupt()
    result = runner.run_simulation(runtime.config)
    assert "KeyboardInterrupt" in result["error"]
    runtime.process.wait.assert_called_once()


def test_interrupted_shutdown_still_terminates_child(runtime):
    runtime.process.wait.side_effect = [KeyboardInterrupt(), 0]
    result = runner.run_simulation(runtime.config)
    assert result["status"] == "failed"
    assert "KeyboardInterrupt" in result["error"]
    runtime.process.terminate.assert_called_once()


def test_time_drift_is_failure(runtime):
    runtime.connection.simulationStep.side_effect = lambda: setattr(runtime.state, "time", 0.5)
    result = runner.run_simulation(runtime.config)
    assert "step grid" in result["error"]
    assert result["final_time_s"] == 0.5


def test_verbose_uses_owned_connection(runtime, capsys):
    runtime.connection.vehicle.getIDList.return_value = ["vehicle_1"]
    runtime.connection.vehicle.getSpeed.return_value = 3
    runtime.connection.vehicle.getPosition.return_value = (1, 2)
    assert runner.run_simulation(runtime.config, verbose=True)["status"] == "completed"
    assert "vehicle=vehicle_1" in capsys.readouterr().out


def test_cli_existing_flags_and_new_options():
    args = runner.parse_args(["--config", "sample.sumocfg", "--verbose", "--seed", "42",
                              "--step-length", "0.4", "--end-time", "5400"])
    assert args.config == Path("sample.sumocfg") and args.verbose
    assert (args.seed, args.step_length_s, args.end_time_s) == (42, 0.4, 5400)


@pytest.mark.parametrize("status,error,expected", [("completed", None, 0),
                                                  ("failed", "bad input", 1),
                                                  ("failed", "KeyboardInterrupt: ", 130)])
def test_cli_exit_status(monkeypatch, status, error, expected):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    monkeypatch.setattr(runner, "run_simulation", lambda **kwargs: {"status": status, "error": error})
    assert runner.main() == expected


def test_cli_passes_config_to_runner(monkeypatch, runtime):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--config", str(runtime.config)])
    run = Mock(return_value={"status": "completed", "error": None})
    monkeypatch.setattr(runner, "run_simulation", run)
    assert runner.main() == 0
    assert run.call_args.kwargs["config_path"] == runtime.config
    assert "config" not in run.call_args.kwargs


def test_help_from_outside_repository(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "--end-time" in result.stdout and "--verbose" in result.stdout


def configure(runtime, contents):
    runtime.config.write_text('<configuration><time><end value="2"/><step-length value="0.4"/></time>'
                              + contents + '</configuration>')


def test_existing_output_is_rejected_before_simulation(runtime):
    output = runtime.config.parent / "previous.xml"
    output.write_text("preserve this result")
    configure(runtime, '<output><summary-output value="previous.xml"/></output>')
    result = runner.run_simulation(runtime.config)
    assert "summary-output" in result["error"] and str(output) in result["error"]
    assert output.read_text() == "preserve this result"
    runtime.popen.assert_not_called()


def test_non_ascii_output_collision(runtime):
    output = runtime.config.parent / "é_result.xml"
    output.write_text("preserve")
    runtime.config.write_text(
        '<configuration><time><end value="2"/><step-length value="0.4"/></time>'
        '<output><summary-output value="é_result.xml"/></output></configuration>',
        encoding="utf-8",
    )
    result = runner.run_simulation(runtime.config)
    assert "already exists" in result["error"]
    assert output.read_text() == "preserve"
    runtime.popen.assert_not_called()


@pytest.mark.parametrize("setting,actual", [
    ("output-prefix", "pre_result.xml"),
    ("output-suffix", "result_pre.xml"),
])
def test_environment_substitution_in_output_affixes(runtime, monkeypatch, setting, actual):
    monkeypatch.setenv("M9_OUTPUT_AFFIX", "pre_")
    if setting == "output-suffix":
        monkeypatch.setenv("M9_OUTPUT_AFFIX", "_pre")
    output = runtime.config.parent / actual
    output.write_text("preserve")
    configure(runtime, f'<output><summary-output value="result.xml"/>'
                       f'<{setting} value="${{M9_OUTPUT_AFFIX}}"/></output>')
    result = runner.run_simulation(runtime.config)
    assert "already exists" in result["error"]
    assert output.read_text() == "preserve"
    runtime.popen.assert_not_called()


@pytest.mark.parametrize("allow_overwrite", [False, True])
def test_substituted_output_cannot_replace_input(runtime, monkeypatch, allow_overwrite):
    monkeypatch.setenv("M9_OUTPUT_AFFIX", "pre_")
    source = runtime.config.parent / "pre_network.xml"
    source.write_text("<net/>")
    configure(runtime, '<input><net-file value="pre_network.xml"/></input>'
                       '<output><summary-output value="network.xml"/>'
                       '<output-prefix value="${M9_OUTPUT_AFFIX}"/></output>')
    result = runner.run_simulation(runtime.config, allow_overwrite=allow_overwrite)
    assert "collides with simulation input" in result["error"]
    assert source.read_text() == "<net/>"
    runtime.popen.assert_not_called()


def test_undefined_output_affix_variable_fails_before_launch(runtime):
    configure(runtime, '<output><summary-output value="result.xml"/>'
                       '<output-prefix value="${M9_UNDEFINED_AFFIX}"/></output>')
    result = runner.run_simulation(runtime.config)
    assert "Cannot resolve filename variable ${M9_UNDEFINED_AFFIX}" in result["error"]
    runtime.popen.assert_not_called()


def test_validator_checks_outputs_without_launching_sumo(runtime):
    (runtime.config.parent / "previous.xml").write_text("old")
    configure(runtime, '<output><summary-output value="previous.xml"/></output>')
    command = validator.build_sumo_command(
        runtime.config, sumo_bin="sumo", end_time_s=None,
        seed=None, step_length_s=None,
    )
    with pytest.raises(ValueError, match="already exists"):
        validator.preflight_configuration(command)
    with pytest.raises(ValueError, match="explicit boolean"):
        validator.preflight_configuration(command, allow_overwrite="true")
    assert validator.preflight_configuration(command, allow_overwrite=True) is None
    runtime.popen.assert_not_called()


def test_explicit_overwrite_allows_existing_output(runtime):
    (runtime.config.parent / "previous.xml").write_text("old")
    configure(runtime, '<output><summary-output value="previous.xml"/></output>')
    assert runner.run_simulation(runtime.config, allow_overwrite=True)["status"] == "completed"


@pytest.mark.parametrize("allow_overwrite", [False, True])
def test_input_output_collision_is_always_rejected(runtime, allow_overwrite):
    source = runtime.config.parent / "network.xml"
    source.write_text("<net/>")
    configure(runtime, '<input><net-file value="network.xml"/></input>'
                       '<output><summary-output value="network.xml"/></output>')
    result = runner.run_simulation(runtime.config, allow_overwrite=allow_overwrite)
    assert "collides with simulation input" in result["error"]
    assert source.read_text() == "<net/>"
    runtime.popen.assert_not_called()


def test_output_colliding_with_config_is_rejected(runtime):
    configure(runtime, '<output><summary-output value="test.sumocfg"/></output>')
    assert "collides" in runner.run_simulation(runtime.config, allow_overwrite=True)["error"]
    runtime.popen.assert_not_called()


def test_prefix_suffix_and_log_destinations(runtime):
    output = runtime.config.parent / "pre_result_new.xml"
    output.write_text("old")
    configure(runtime, '<output><output-prefix value="pre_"/><output-suffix value="_new"/></output>'
                       '<report><log value="result.xml"/></report>')
    assert str(output) in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_metadata_discovers_other_output_options(runtime, monkeypatch):
    output = runtime.config.parent / "other.xml"
    output.write_text("old")
    configure(runtime, '<output><future-output value="other.xml"/></output>')
    original = validator._sumo_xml
    def inspect(command):
        xml = original(command)
        if "--save-template" in command:
            validator.ET.SubElement(xml.find("output"), "future-output", type="FILE")
        return xml
    monkeypatch.setattr(validator, "_sumo_xml", inspect)
    assert "future-output" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_filter_input_is_not_misclassified_as_output(runtime):
    (runtime.config.parent / "edges.txt").write_text("edge")
    configure(runtime, '<output><fcd-output.filter-edges.input-file value="edges.txt"/></output>')
    assert runner.run_simulation(runtime.config)["status"] == "completed"


@pytest.mark.parametrize("destination", ["stdout", "stderr", "NUL", "/dev/null", "-", "localhost:1234"])
def test_special_output_destinations(runtime, destination):
    configure(runtime, f'<output><summary-output value="{destination}"/></output>')
    assert runner.run_simulation(runtime.config)["status"] == "completed"


def test_environment_output_and_time_prefix(runtime, monkeypatch):
    monkeypatch.setenv("M9_TEST_RESULT", "previous.xml")
    (runtime.config.parent / "2026-10-22_previous.xml").write_text("old")
    configure(runtime, '<output><summary-output value="${M9_TEST_RESULT}"/>'
                       '<output-prefix value="TIME_"/></output>')
    assert "already exists" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_additional_output_and_includes_are_checked(runtime):
    folder = runtime.config.parent
    (folder / "detector.add.xml").write_text('<additional><laneAreaDetector id="q" file="queue.xml"/></additional>')
    (folder / "included.add.xml").write_text('<additional><include href="detector.add.xml"/></additional>')
    (folder / "queue.xml").write_text("old queue")
    configure(runtime, '<input><additional-files value="included.add.xml"/></input>')
    result = runner.run_simulation(runtime.config)
    assert "laneAreaDetector.file" in result["error"]
    assert (folder / "queue.xml").read_text() == "old queue"
    runtime.popen.assert_not_called()


@pytest.mark.parametrize("duration,valid", [("0", True), ("0.0", True), ("2", False), ("nan", False)])
def test_inherited_lanechange_duration(runtime, duration, valid):
    configure(runtime, f'<processing><lanechange.duration value="{duration}"/></processing>')
    result = runner.run_simulation(runtime.config)
    assert (result["status"] == "completed") == valid
    if not valid:
        assert f"lanechange.duration={duration}" in result["error"]
        runtime.popen.assert_not_called()


@pytest.mark.parametrize("gain,valid", [("1", True), ("1.0", True), ("0", False), ("2", False)])
def test_vehicle_type_lc_speed_gain(runtime, gain, valid):
    route = runtime.config.parent / "vehicles.rou.xml"
    route.write_text(f'<routes><vType id="car" lcSpeedGain="{gain}" accel="2.6"/></routes>')
    configure(runtime, '<input><route-files value="vehicles.rou.xml"/></input>')
    result = runner.run_simulation(runtime.config)
    assert (result["status"] == "completed") == valid
    if not valid:
        assert f"lcSpeedGain={gain}" in result["error"]
        runtime.popen.assert_not_called()


def test_original_shutdown_interruption_regression(runtime):
    def wait(timeout):
        if runtime.process.wait.call_count == 1:
            raise subprocess.TimeoutExpired("sumo", timeout)
        if runtime.process.wait.call_count == 2:
            raise KeyboardInterrupt()
        runtime.process.returncode = -9
        return -9
    runtime.process.wait.side_effect = wait
    result = runner.run_simulation(runtime.config)
    runtime.process.terminate.assert_called_once()
    runtime.process.kill.assert_called_once()
    assert runtime.process.wait.call_count == 3
    assert runtime.process.returncode == -9
    assert any("KeyboardInterrupt" in error for error in result["cleanup_errors"])
    assert result["status"] == "failed"


def test_shutdown_interruption_keeps_original_execution_error(runtime):
    runtime.connection.simulationStep.side_effect = RuntimeError("original failure")
    runtime.process.wait.side_effect = [subprocess.TimeoutExpired("sumo", 5), KeyboardInterrupt(), 0]
    result = runner.run_simulation(runtime.config)
    assert "original failure" in result["error"]
    assert any("KeyboardInterrupt" in error for error in result["cleanup_errors"])
    runtime.process.kill.assert_called_once()


def test_final_kill_failure_is_reported(runtime):
    runtime.process.wait.side_effect = [subprocess.TimeoutExpired("sumo", 5), KeyboardInterrupt()]
    runtime.process.kill.side_effect = OSError("kill denied")
    result = runner.run_simulation(runtime.config)
    assert any("kill denied" in error for error in result["cleanup_errors"])


def test_export_action_rejected_before_config_inspection(runtime, monkeypatch):
    configure(runtime, '<configuration><save-schema value="important.xsd"/></configuration>')
    assert "save-schema" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_inspection_receives_effective_runtime_command(runtime, monkeypatch):
    calls = []
    original = validator._sumo_xml
    def inspect(command):
        calls.append(command)
        return original(command)
    monkeypatch.setattr(validator, "_sumo_xml", inspect)
    runner.run_simulation(runtime.config, seed=81, end_time_s=1.2)
    assert calls[1][-2:] == ["--save-configuration", "stdout"]
    assert calls[1][calls[1].index("--seed") + 1] == "81"
    assert calls[1][calls[1].index("--end") + 1] == "1.2"


def test_cli_overwrite_opt_in():
    assert runner.parse_args(["--allow-overwrite"]).allow_overwrite
    assert not runner.parse_args([]).allow_overwrite


def test_configuration_inspection_failure_never_launches(runtime, monkeypatch):
    def fail(command):
        raise subprocess.TimeoutExpired(command, 10)
    monkeypatch.setattr(validator, "_sumo_xml", fail)
    assert "TimeoutExpired" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_gzip_vehicle_type_conflict(runtime):
    route = runtime.config.parent / "vehicles.rou.xml.gz"
    with validator.gzip.open(route, "wt") as stream:
        stream.write('<routes><vType id="car" lcSpeedGain="0"/></routes>')
    configure(runtime, '<input><route-files value="vehicles.rou.xml.gz"/></input>')
    assert "lcSpeedGain=0" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()


def test_input_hardlink_is_protected(runtime):
    source = runtime.config.parent / "network.xml"
    source.write_text("<net/>")
    alias = runtime.config.parent / "alias.xml"
    alias.hardlink_to(source)
    configure(runtime, '<input><net-file value="network.xml"/></input>'
                       '<output><summary-output value="alias.xml"/></output>')
    assert "collides" in runner.run_simulation(runtime.config, allow_overwrite=True)["error"]
    assert source.read_text() == "<net/>"
    runtime.popen.assert_not_called()


def test_unrelated_additional_input_file_is_preserved(runtime):
    folder = runtime.config.parent
    (folder / "speed.xml").write_text('<additional/>')
    (folder / "sign.add.xml").write_text('<additional><variableSpeedSign id="s" file="speed.xml"/></additional>')
    configure(runtime, '<input><additional-files value="sign.add.xml"/></input>')
    assert runner.run_simulation(runtime.config)["status"] == "completed"


def test_state_output_family_collision(runtime):
    (runtime.config.parent / "state_1.00.xml.gz").write_text("old")
    configure(runtime, '<output><save-state.times value="1"/>'
                       '<save-state.prefix value="state"/></output>')
    assert "already exists" in runner.run_simulation(runtime.config)["error"]
    runtime.popen.assert_not_called()

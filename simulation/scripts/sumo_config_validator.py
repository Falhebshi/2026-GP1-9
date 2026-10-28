from decimal import Decimal
import glob
import gzip
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


def _validate_allow_overwrite(allow_overwrite):
    """Require an explicit choice before permitting existing outputs to be replaced."""
    if not isinstance(allow_overwrite, bool):
        raise ValueError("allow_overwrite must be an explicit boolean")


def prepare_execution(config_path, *, sumo_bin, end_time_s, seed, step_length_s, allow_overwrite=False):
    """Validate execution settings and build the SUMO command."""
    _validate_allow_overwrite(allow_overwrite)
    config_path = Path(config_path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"SUMO configuration file not found: {config_path}")
    root = ET.parse(config_path).getroot()
    if root.tag not in ("configuration", "sumoConfiguration"):
        raise ValueError("Expected a SUMO <configuration> document")

    def configured(path, fallback=None):
        element = root.find(path)
        return element.get("value", fallback) if element is not None else fallback

    end_time_s = end_time_s if end_time_s is not None else configured("time/end")
    step_length_s = step_length_s if step_length_s is not None else configured("time/step-length", "1")
    seed = seed if seed is not None else configured("random_number/seed", "23423")
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer between 0 and 2147483647")
    random_seed = int(seed)
    if str(seed).strip() != str(random_seed) or not 0 <= random_seed <= 2147483647:
        raise ValueError("seed must be an integer between 0 and 2147483647")
    for name, value in (("end_time_s", end_time_s), ("step_length_s", step_length_s)):
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{name} must be finite and positive")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{name} must be finite and positive")
    deadline = Decimal(str(end_time_s))
    simulation_step = Decimal(str(step_length_s))
    if simulation_step % Decimal("0.001") or deadline % simulation_step:
        raise ValueError("step must use whole milliseconds and end time must be a whole number of steps")
    executable = shutil.which(str(sumo_bin))
    if executable is None:
        raise FileNotFoundError(f"SUMO executable not found: {sumo_bin}")
    command = [
        executable, "-c", str(config_path),
        "--begin", "0", "--end", str(deadline),
        "--step-length", str(simulation_step), "--seed", str(random_seed),
        "--random", "false", "--num-clients", "1",
    ]
    return {
        "command": command,
        "end_time_s": float(deadline),
        "step_length_s": float(simulation_step),
        "total_steps": int(deadline / simulation_step),
        "seed": random_seed,
    }


def build_sumo_command(config_path, *, sumo_bin, end_time_s, seed, step_length_s):
    """Return the command alone for existing callers."""
    return prepare_execution(
        config_path, sumo_bin=sumo_bin, end_time_s=end_time_s,
        seed=seed, step_length_s=step_length_s,
    )["command"]


def _sumo_xml(command):
    """Ask SUMO for XML metadata/configuration, without executing a simulation."""
    result = subprocess.run(command, capture_output=True, timeout=10)
    if result.returncode:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"SUMO configuration inspection failed: {diagnostic}")
    return ET.fromstring(result.stdout)


def _expand_filename_variables(value, *, pattern=False):
    def expand(match):
        name = match.group(1)
        if pattern and name in ("LOCALTIME", "UTC", "PID"):
            return "*"
        if name not in os.environ:
            raise ValueError(f"Cannot resolve filename variable ${{{name}}}")
        return os.environ[name]

    return re.sub(r"\$\{([^}]+)\}", expand, value)


def _file_path(value, base, *, pattern=False):
    value = _expand_filename_variables(value, pattern=pattern)
    path = Path(value).expanduser()
    return (base / path).resolve()


def _read_effective_configuration(command):
    """Use SUMO's own option metadata and resolved configuration."""
    config = Path(command[command.index("-c") + 1])
    template = _sumo_xml([command[0], "--save-template", "stdout"])
    options = {}
    for group in template:
        for option in group:
            for name in (option.tag, *option.get("synonymes", "").split()):
                options[name] = (group.tag, option)
    # An inherited export action could write a file during inspection itself.
    for item in ET.parse(config).iter():
        group, option = options.get(item.tag, (None, None))
        if group == "configuration" and option.get("type") == "FILE" and item.get("value"):
            raise ValueError(f"Remove configuration export/load action {item.tag}={item.get('value')}")
    effective = _sumo_xml(command + ["--save-configuration", "stdout"])
    values = {item.tag: item.get("value", "") for group in effective for item in group}
    return options, values


def _validate_baseline_duration(values):
    duration = values.get("lanechange.duration", "0")
    if not math.isfinite(float(duration)) or float(duration) != 0:
        raise ValueError(f"Baseline conflict: lanechange.duration={duration}; expected 0")


def _collect_configuration_files(config, options, values):
    inputs = {config.resolve()}
    outputs = []
    xml_inputs = []
    for name, value in values.items():
        group, option = options.get(name, (None, None))
        if not value or option is None or name == "save-state.prefix":
            continue
        device_output = name.endswith(".file") and "output" in option.get("help", "").lower()
        if option.get("type") != "FILE" and not device_output:
            continue
        is_output = (device_output or group in ("output", "report") or "output" in name) and not name.endswith(".input-file")
        for filename in value.split(","):
            if is_output:
                outputs.append((name, filename.strip(), config.parent))
            else:
                path = _file_path(filename.strip(), config.parent)
                inputs.add(path)
                if name in ("route-files", "additional-files", "load-state"):
                    xml_inputs.append(path)
    return inputs, outputs, xml_inputs


def _collect_xml_files(xml_inputs, inputs, outputs):
    visited = set()
    while xml_inputs:
        path = xml_inputs.pop()
        if path in visited:
            continue
        visited.add(path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as stream:
            for _, item in ET.iterparse(stream):
                gain = item.get("lcSpeedGain")
                if gain is not None and (not math.isfinite(float(gain)) or float(gain) != 1):
                    raise ValueError(f"Baseline conflict in {path}: lcSpeedGain={gain}; expected 1")
                if item.tag == "include" and item.get("href"):
                    child = _file_path(item.get("href"), path.parent)
                    inputs.add(child)
                    xml_inputs.append(child)
                for attribute in ("file", "dest", "output"):
                    filename = item.get(attribute)
                    if not filename:
                        continue
                    if attribute == "file" and item.tag in ("rerouter", "calibrator", "variableSpeedSign"):
                        child = _file_path(filename, path.parent)
                        inputs.add(child)
                        xml_inputs.append(child)
                    else:
                        outputs.append((f"{path.name}: {item.tag}.{attribute}", filename, path.parent))
                item.clear()


def _add_generated_state_output(config, values, outputs):
    if values.get("save-state.times") or float(values.get("save-state.period", "-1")) > 0:
        if not values.get("save-state.files"):
            outputs.append(("save-state.prefix", values.get("save-state.prefix", "state") + "_*" +
                            values.get("save-state.suffix", ".xml.gz"),
                            config.parent if "save-state.prefix" in values else Path.cwd()))


def _output_pattern(source, filename, base, prefix, suffix):
    """Mirror SUMO's prefix/suffix placement and generated output names."""
    path = _file_path(filename, base, pattern=True)
    parts = (prefix + path.name).split(".")
    for index in range(len(parts) - 1, -1, -1):
        if index == 0 or len(parts[index]) > 4:
            parts[index] += suffix
            break
    path = Path(str(path.parent) + os.sep + ".".join(parts)).resolve()
    if source == "vtk-output":
        path = path.parent / (path.name + "_*.vtp")
    return path


def _check_output_collisions(config, values, inputs, outputs, allow_overwrite):
    _add_generated_state_output(config, values, outputs)
    prefix = _expand_filename_variables(values.get("output-prefix", ""), pattern=True).replace("TIME", "*", 1)
    suffix = _expand_filename_variables(values.get("output-suffix", ""), pattern=True).replace("TIME", "*", 1)
    for source, filename, base in outputs:
        if filename.lower() in ("stdout", "stderr", "nul", "/dev/null", "-") or re.match(r"^(?:[^:]{2,}|\[.*\]):\d+$", filename):
            continue
        path = _output_pattern(source, filename, base, prefix, suffix)
        matches = [Path(p).resolve() for p in glob.glob(str(path))] if "*" in str(path) else [path.resolve()]
        # A generated filename family must still be checked against input paths.
        for candidate in inputs:
            if candidate.match(str(path)) and candidate not in matches:
                matches.append(candidate)
        for destination in matches:
            if destination in inputs or any(destination.exists() and p.exists() and os.path.samefile(destination, p) for p in inputs):
                raise ValueError(f"Output {source} collides with simulation input: {destination}")
            if destination.exists() and (destination.is_dir() or not allow_overwrite):
                raise ValueError(f"Output {source} already exists: {destination}; choose a new path or authorize --allow-overwrite")


def preflight_configuration(command, *, allow_overwrite=False):
    """Reject baseline conflicts and unsafe output destinations before launch."""
    _validate_allow_overwrite(allow_overwrite)
    config = Path(command[command.index("-c") + 1])
    options, values = _read_effective_configuration(command)
    _validate_baseline_duration(values)
    inputs, outputs, xml_inputs = _collect_configuration_files(config, options, values)
    _collect_xml_files(xml_inputs, inputs, outputs)
    _check_output_collisions(config, values, inputs, outputs, allow_overwrite)

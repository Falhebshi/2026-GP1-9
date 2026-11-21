"""
One segment of the live chain: a bounded SUMO run that continues from
the state the previous segment saved (Issue #48, option A2).

A segment simulates from begin_s to end_s (seconds from the chain's
second 0, the start of the warm-up). The first segment starts at 0 with
an empty network; every later one loads the previous segment's state
file, so the vehicles on the road, the signal state and the random
number generators carry on where they stopped. The segment saves the
state at end_s for the next one.

Times, as SUMO handles them (checked on SUMO 1.27.1):

- SUMO writes a state for time t only if the run goes on past t, so a
  segment is run one step beyond end_s (--end end_s + step), and its
  outputs include the timestep at end_s.
- The next segment starts at that state's time and writes the timestep
  at its begin_s again, with the same values. That timestep belongs to
  the earlier segment; whoever combines segment outputs keeps the
  earlier copy (simulation/live/outputs.py).
- A vehicle with a departure time up to end_s is inserted by the
  segment, so a segment's route file holds the departures after
  begin_s up to and including end_s (the first segment's from 0).

Rules applied, and why:

- SUMO is started directly, not stepped through TraCI: a segment needs
  no control during the run, and Experiment 5 of #48 found TraCI
  stepping to be most of the simulation time.
- The random number generators are saved with the state
  (--save-state.rng) at 8 decimals (--save-state.precision): without
  them, a reloaded run draws different random numbers than an
  uninterrupted one would. With them, Experiment 5 measured a chain of
  79 segments within 2.8 % of one uninterrupted run, well inside the
  11-12.5 % that another seed gives.
- The settings that decide what is simulated are the baseline runner's
  (simulation/scripts/run_scenario.py): the same network, step length,
  seed and output attributes, and --random false. Only the begin and
  end times and the state options are added.
- Nothing is overwritten: a segment folder must not exist yet. A
  segment that fails leaves its folder and SUMO's log for diagnosis,
  and saves no state, so the chain cannot continue from a broken run.
"""

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

STATE_FILE = "state.xml.gz"
ROUTE_FILE = "routes.rou.xml"
CONFIG_FILE = "segment.sumocfg"
LOG_FILE = "sumo.log"
RAW_DIR = "raw"
FCD_FILE = "fcd.xml"
TRIPINFO_FILE = "tripinfo.xml"
TLS_STATES_FILE = "tls_states.xml"
TLS_ADDITIONAL_FILE = "tls_states.add.xml"

# FCD attributes written by the baseline runner (run_scenario.py); the KPI
# measurements and the playback builder read these.
FCD_ATTRIBUTES = "id,x,y,angle,type,speed,lane,pos,odometer,signals"
STATE_PRECISION = 8
SEGMENT_TIMEOUT_S = 600


class SegmentError(RuntimeError):
    """Raised when a segment cannot be prepared or SUMO fails."""


@dataclass(frozen=True)
class SegmentFiles:
    """The files of one finished segment."""

    folder: Path
    begin_s: float
    end_s: float
    route_file: Path
    state_file: Path
    fcd_file: Path
    tripinfo_file: Path
    tls_states_file: Path


def segment_files(folder: str | Path, begin_s: float, end_s: float) -> SegmentFiles:
    """Where a segment's files are, whether or not it has run."""

    folder = Path(folder).resolve()
    raw = folder / RAW_DIR

    return SegmentFiles(
        folder=folder,
        begin_s=begin_s,
        end_s=end_s,
        route_file=folder / ROUTE_FILE,
        state_file=folder / STATE_FILE,
        fcd_file=raw / FCD_FILE,
        tripinfo_file=raw / TRIPINFO_FILE,
        tls_states_file=raw / TLS_STATES_FILE,
    )


def check_times(begin_s: float, end_s: float, step_length_s: float) -> None:
    """A segment starts and ends on the step grid, and ends after it starts."""

    step = Decimal(str(step_length_s))

    for name, value in (("begin", begin_s), ("end", end_s)):
        if Decimal(str(value)) % step:
            raise SegmentError(f"segment {name} {value} s is not a whole number of {step_length_s} s steps")

    if end_s <= begin_s or begin_s < 0:
        raise SegmentError(f"segment must run forward from 0 or later, got {begin_s} to {end_s} s")


def write_config(files: SegmentFiles, network_path: str | Path) -> Path:
    """The segment's SUMO configuration, with the baseline runner's outputs."""

    tls_additional = files.folder / TLS_ADDITIONAL_FILE
    additional = ET.Element("additional")
    ET.SubElement(
        additional, "timedEvent", type="SaveTLSSwitchStates", dest=str(files.tls_states_file)
    )
    tls_additional.write_bytes(ET.tostring(additional, encoding="utf-8", xml_declaration=True))

    config = ET.Element("configuration")
    inputs = ET.SubElement(config, "input")
    ET.SubElement(inputs, "net-file", value=str(Path(network_path).resolve()))
    ET.SubElement(inputs, "route-files", value=str(files.route_file))
    ET.SubElement(inputs, "additional-files", value=str(tls_additional))
    outputs = ET.SubElement(config, "output")
    ET.SubElement(outputs, "precision", value="3")
    ET.SubElement(outputs, "fcd-output", value=str(files.fcd_file))
    ET.SubElement(outputs, "fcd-output.geo", value="true")
    ET.SubElement(outputs, "fcd-output.attributes", value=FCD_ATTRIBUTES)
    ET.SubElement(outputs, "tripinfo-output", value=str(files.tripinfo_file))
    ET.SubElement(outputs, "tripinfo-output.write-unfinished", value="true")
    ET.SubElement(outputs, "tripinfo-output.write-undeparted", value="true")

    path = files.folder / CONFIG_FILE
    path.write_bytes(ET.tostring(config, encoding="utf-8", xml_declaration=True))
    return path


def sumo_command(
    config_path: Path,
    files: SegmentFiles,
    *,
    sumo_bin: str,
    seed: int,
    step_length_s: float,
    load_state: Path | None,
) -> list[str]:
    """The command that runs one segment and saves its state at the end."""

    command = [
        sumo_bin, "-c", str(config_path),
        "--begin", str(files.begin_s),
        "--end", str(Decimal(str(files.end_s)) + Decimal(str(step_length_s))),
        "--step-length", str(step_length_s), "--seed", str(seed),
        "--random", "false",
        "--save-state.times", str(files.end_s),
        "--save-state.files", str(files.state_file),
        "--save-state.rng", "true",
        "--save-state.precision", str(STATE_PRECISION),
        "--no-step-log", "true",
    ]

    if load_state is not None:
        command += ["--load-state", str(load_state)]

    return command


def run_segment(
    folder: str | Path,
    route_xml: bytes,
    *,
    begin_s: float,
    end_s: float,
    network_path: str | Path,
    seed: int,
    step_length_s: float,
    load_state: str | Path | None,
    sumo_bin: str = "sumo",
    timeout_s: float = SEGMENT_TIMEOUT_S,
) -> SegmentFiles:
    """
    Run one segment in a new folder and return its files. load_state is
    the previous segment's state file, or None for the chain's first
    segment, which must start at 0.

    Raises SegmentError when the folder exists, the times are not on the
    step grid, the state to load is missing, or SUMO fails or saves no
    state.
    """

    check_times(begin_s, end_s, step_length_s)
    files = segment_files(folder, begin_s, end_s)

    if files.folder.exists():
        raise SegmentError(f"segment folder already exists: {files.folder}")
    if load_state is None and begin_s != 0:
        raise SegmentError("only a segment that starts at 0 can run without a saved state")
    if load_state is not None:
        load_state = Path(load_state).resolve()
        if not load_state.is_file():
            raise SegmentError(f"saved state not found: {load_state}")

    (files.folder / RAW_DIR).mkdir(parents=True)
    files.route_file.write_bytes(route_xml)
    config_path = write_config(files, network_path)
    command = sumo_command(
        config_path, files, sumo_bin=sumo_bin, seed=seed,
        step_length_s=step_length_s, load_state=load_state,
    )

    log_path = files.folder / LOG_FILE
    try:
        with log_path.open("wb") as log:
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s, check=False,
            )
    except FileNotFoundError as exc:
        raise SegmentError(f"SUMO executable not found: {sumo_bin}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SegmentError(f"SUMO did not finish the segment within {timeout_s:.0f} s") from exc

    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
        raise SegmentError(f"SUMO failed (exit code {result.returncode}): " + " | ".join(tail))
    if not files.state_file.is_file():
        raise SegmentError(f"SUMO finished but saved no state: {files.state_file}")

    return files

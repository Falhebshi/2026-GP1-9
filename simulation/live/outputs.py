"""
Combine the SUMO outputs of consecutive live segments into one file
each, so the KPI measurements and the playback builder read them exactly
as they read the outputs of one uninterrupted run.

Each segment writes its own fcd.xml, tripinfo.xml and tls_states.xml
(simulation/live/segments.py). Joined in order, they describe one run,
with two kinds of repeat to remove:

- FCD and signal states: a segment that continues from a saved state
  writes the timestep, and the signal state, at its begin time again;
  the segment before it already wrote them. The earlier copy is kept: a
  later segment's timesteps and signal records at or before its begin
  time are dropped.
- Trip information: every segment writes the vehicles still driving at
  its end as unfinished (tripinfo-output.write-unfinished), and the
  vehicles waiting to enter as undeparted. A vehicle can therefore appear
  in several segments; the last record is the newest and is kept. A trip
  that ended in an earlier segment never appears again, so it is kept as
  written.

The files are combined as text, line by line, without building an XML
tree: the FCD of 45 minutes of peak traffic is several hundred megabytes.
SUMO writes one element or tag per line, which is what the line rules
rely on; a file in another layout is refused rather than read wrongly.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

TIMESTEP = re.compile(rb'^\s*<timestep time="([^"]+)"(/?)>\s*$')
TIMESTEP_END = re.compile(rb"^\s*</timestep>\s*$")
FCD_ROOT = re.compile(rb"^\s*<fcd-export\b")
FCD_ROOT_END = re.compile(rb"^\s*</fcd-export>\s*$")
TLS_STATE = re.compile(rb'^\s*<tlsState time="([^"]+)"')
TLS_ROOT = re.compile(rb"^\s*<tlsStates\b")
TLS_ROOT_END = re.compile(rb"^\s*</tlsStates>\s*$")

XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'


class SegmentOutputError(ValueError):
    """Raised when segment outputs cannot be combined."""


def _body_lines(path: Path, root: re.Pattern, root_end: re.Pattern):
    """The lines between a file's root start tag and its end tag."""

    inside = closed = False

    with path.open("rb") as file:
        for line in file:
            if not inside:
                if root.match(line):
                    inside = True
                continue
            if root_end.match(line):
                closed = True
                break
            yield line

    if not inside:
        raise SegmentOutputError(f"{path}: root element not found")
    if not closed:
        raise SegmentOutputError(f"{path}: the file ends before its root element closes")


def combine_fcd(paths: list[Path], output: Path) -> Path:
    """
    Join the FCD files of consecutive segments into output, keeping the
    first copy of each timestep. Raises SegmentOutputError for a file
    that is not SUMO's line layout or for timesteps that go backwards.
    """

    last_time = None

    with Path(output).open("wb") as out:
        out.write(XML_DECLARATION + b"<fcd-export>\n")

        for path in paths:
            keep = True
            in_step = False

            for line in _body_lines(Path(path), FCD_ROOT, FCD_ROOT_END):
                step = TIMESTEP.match(line)
                if step:
                    if in_step:
                        raise SegmentOutputError(f"{path}: a timestep starts inside another")
                    time_s = float(step.group(1))
                    keep = last_time is None or time_s > last_time + 1e-9
                    if keep:
                        last_time = time_s
                    in_step = not step.group(2)
                    if keep:
                        out.write(line)
                    continue
                if TIMESTEP_END.match(line):
                    if not in_step:
                        raise SegmentOutputError(f"{path}: a timestep ends that never started")
                    in_step = False
                    if keep:
                        out.write(line)
                    continue
                if not in_step:
                    if line.strip():
                        raise SegmentOutputError(f"{path}: unexpected line outside a timestep")
                    continue
                if keep:
                    out.write(line)

            if in_step:
                raise SegmentOutputError(f"{path}: the last timestep is not closed")

        out.write(b"</fcd-export>\n")

    return Path(output)


def combine_tls_states(paths: list[Path], begin_times: list[float], output: Path) -> Path:
    """
    Join the signal-state files of consecutive segments into output.
    begin_times are the segments' begin times: a segment that continues
    from a saved state first writes the signal state at its begin time,
    which the segment before it recorded already, so a later segment's
    records at or before its begin time are dropped.
    """

    if len(paths) != len(begin_times):
        raise SegmentOutputError("one begin time is needed for each signal-state file")

    with Path(output).open("wb") as out:
        out.write(XML_DECLARATION + b"<tlsStates>\n")

        for number, (path, begin_s) in enumerate(zip(paths, begin_times)):
            for line in _body_lines(Path(path), TLS_ROOT, TLS_ROOT_END):
                record = TLS_STATE.match(line)
                if not record:
                    if line.strip():
                        raise SegmentOutputError(f"{path}: unexpected line in signal states")
                    continue
                if number and float(record.group(1)) <= begin_s + 1e-9:
                    continue
                out.write(line)

        out.write(b"</tlsStates>\n")

    return Path(output)


def combine_tripinfo(paths: list[Path], output: Path) -> Path:
    """
    Join the trip-information files of consecutive segments into output,
    one record per vehicle: the record of the latest segment that wrote
    it.
    """

    latest: dict[str, bytes] = {}

    for path in paths:
        for element in ET.parse(path).getroot():
            if element.tag != "tripinfo":
                continue
            vehicle_id = element.get("id")
            latest.pop(vehicle_id, None)
            element.tail = None
            latest[vehicle_id] = ET.tostring(element, encoding="utf-8")

    with Path(output).open("wb") as out:
        out.write(XML_DECLARATION + b"<tripinfos>\n")
        for record in latest.values():
            out.write(b"    " + record + b"\n")
        out.write(b"</tripinfos>\n")

    return Path(output)

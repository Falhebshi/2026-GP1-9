"""
Write a DemandPlan as SUMO input.

One call writes three files into an output folder, each named after
the folder (for simulation/outputs/baseline/):

- baseline_routes.rou.xml: the SUMO route file, read by SUMO only;
- baseline_manifest.json: the DemandPlan, linking every vehicle to its
  demand record, read by Jaadah components instead of the SUMO file;
- baseline_demand.json: the SimulationDemand records the plan was made
  from, stored once so that demand_id can be looked up.

Rules applied, and why:

- Vehicle type: SUMO's passenger-car defaults, written out so that a
  change of SUMO default cannot change the baseline unnoticed. No
  calibration data exists yet to justify other values.
- Insertion: departLane="best" and departSpeed="max", so each vehicle
  starts in a lane that leads to its turn and at the lane's speed
  limit, as the free-flow departure shift assumes.
- Lane changes stay instantaneous (SUMO default): no lane-change
  duration is set, so a vehicle never stops between two lanes.
- Same bytes on every computer: files are written as bytes with "\\n"
  line endings, so their SHA-256 fingerprints do not depend on the
  operating system.
- No partial output: every input is checked before anything is
  written, and all problems are reported together. The files are first
  written under temporary names and renamed only once all three exist,
  so a failure while writing leaves the previous files in place.
"""

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..models.mappings import NetworkMappingConfig
from ..models.traffic import SimulationDemand
from .planner import DemandPlan


VEHICLE_TYPE = {
    "id": "car",
    "vClass": "passenger",
    "accel": "2.6",
    "decel": "4.5",
    "sigma": "0.5",
    "length": "5.0",
    "minGap": "2.5",
    "speedDev": "0.1",
}
DEPART_LANE = "best"
DEPART_SPEED = "max"


# ============================================================
# ERRORS AND RESULT
# ============================================================

class DemandWritingError(ValueError):
    """Raised when SUMO demand cannot be written; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot write SUMO demand:\n" + "\n".join(problems))


class GeneratedDemand(BaseModel):
    """Paths and SHA-256 fingerprints of the files written, returned to the caller."""

    model_config = ConfigDict(extra="forbid")

    route_file: Path
    manifest_file: Path
    demand_file: Path
    route_file_sha256: str
    manifest_sha256: str
    demand_sha256: str


# ============================================================
# CHECKS
# ============================================================

def _check_inputs(
    plan: DemandPlan,
    demands: list[SimulationDemand],
    routes: dict[str, list[str]],
) -> None:
    problems = []

    seen_ids = set()
    for demand in demands:
        if demand.demand_id in seen_ids:
            problems.append(f"{demand.demand_id}: duplicate demand_id")
        seen_ids.add(demand.demand_id)
        if demand.movement_id not in routes:
            problems.append(
                f"{demand.demand_id} ({demand.movement_id}): movement is not in the mapping"
            )

    previous = 0.0
    for departure in plan.departures:
        if departure.demand_id not in seen_ids:
            problems.append(
                f"{departure.vehicle_id}: demand_id {departure.demand_id} "
                "is not among the demand records"
            )
        if departure.depart_s < previous:
            problems.append(
                f"{departure.vehicle_id}: departures are not sorted by time "
                f"({departure.depart_s:.2f} s after {previous:.2f} s)"
            )
        previous = departure.depart_s

    if problems:
        raise DemandWritingError(problems)


# ============================================================
# FILE CONTENTS
# ============================================================

def _route_file_bytes(
    plan: DemandPlan,
    movement_of: dict[str, str],
    routes: dict[str, list[str]],
) -> bytes:
    root = ET.Element("routes")
    ET.SubElement(root, "vType", VEHICLE_TYPE)

    used = sorted({movement_of[item.demand_id] for item in plan.departures})
    for movement_id in used:
        ET.SubElement(root, "route", {
            "id": movement_id,
            "edges": " ".join(routes[movement_id]),
        })

    for departure in plan.departures:
        ET.SubElement(root, "vehicle", {
            "id": departure.vehicle_id,
            "type": VEHICLE_TYPE["id"],
            "route": movement_of[departure.demand_id],
            "depart": f"{departure.depart_s:.2f}",
            "departLane": DEPART_LANE,
            "departSpeed": DEPART_SPEED,
        })

    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _manifest_bytes(plan: DemandPlan) -> bytes:
    return plan.model_dump_json(indent=2).encode("utf-8") + b"\n"


def _demand_bytes(demands: list[SimulationDemand]) -> bytes:
    ordered = sorted(
        demands,
        key=lambda item: (item.interval_start, item.movement_id, item.demand_id),
    )
    records = [
        item.model_dump(mode="json", exclude_computed_fields=True)
        for item in ordered
    ]
    return json.dumps(records, indent=2).encode("utf-8") + b"\n"


# ============================================================
# WRITING
# ============================================================

def _write_all(contents: dict[Path, bytes]) -> None:
    """Write every file under a temporary name, then rename them all."""

    temporary = {path: path.with_name(path.name + ".tmp") for path in contents}
    try:
        for path, data in contents.items():
            temporary[path].write_bytes(data)
        for path in contents:
            os.replace(temporary[path], path)
    except OSError as exc:
        for temp_path in temporary.values():
            temp_path.unlink(missing_ok=True)
        raise DemandWritingError([f"could not write {exc.filename}: {exc.strerror}"]) from exc


def write_sumo_demand(
    plan: DemandPlan,
    demands: Iterable[SimulationDemand],
    mapping: NetworkMappingConfig,
    output_dir: str | Path,
) -> GeneratedDemand:
    """Check the inputs, write the three files and return their paths and fingerprints."""

    demands = list(demands)
    routes = {
        item.movement_id: list(item.sumo_route_edge_ids)
        for item in mapping.movement_mappings
    }
    _check_inputs(plan, demands, routes)

    movement_of = {item.demand_id: item.movement_id for item in demands}
    folder = Path(output_dir).resolve()
    prefix = folder.name
    paths = {
        "route": folder / f"{prefix}_routes.rou.xml",
        "manifest": folder / f"{prefix}_manifest.json",
        "demand": folder / f"{prefix}_demand.json",
    }
    contents = {
        paths["route"]: _route_file_bytes(plan, movement_of, routes),
        paths["manifest"]: _manifest_bytes(plan),
        paths["demand"]: _demand_bytes(demands),
    }

    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DemandWritingError([f"could not create folder {folder}: {exc.strerror}"]) from exc
    _write_all(contents)

    return GeneratedDemand(
        route_file=paths["route"],
        manifest_file=paths["manifest"],
        demand_file=paths["demand"],
        route_file_sha256=hashlib.sha256(contents[paths["route"]]).hexdigest(),
        manifest_sha256=hashlib.sha256(contents[paths["manifest"]]).hexdigest(),
        demand_sha256=hashlib.sha256(contents[paths["demand"]]).hexdigest(),
    )

"""
Check a folder of generated SUMO demand before it is simulated.

The check reads the three files written by write_sumo_demand back from
the folder, so it verifies exactly what SUMO and Jaadah components will
read, and it can be repeated on a folder at any time without planning
again. It confirms that:

- every demand record has exactly its vehicle_count vehicles;
- the manifest and the route file list the same vehicles, in the same
  order, with the same departure times;
- every vehicle uses its own movement's route, and every route equals
  the mapped route of its movement;
- the mapped routes are valid in the SUMO network, using the mapping
  validator;
- the vehicle type and insertion settings are the agreed ones.

All problems are reported together.
"""

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from ..mapping.validator import validate_network_mappings
from ..models.mappings import NetworkMappingConfig
from ..models.traffic import SimulationDemand
from .planner import DemandPlan
from .writer import DEPART_LANE, DEPART_SPEED, VEHICLE_TYPE


# ============================================================
# ERRORS AND RESULT
# ============================================================

class DemandCheckError(ValueError):
    """Raised when generated SUMO demand is not correct; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Generated SUMO demand is not correct:\n" + "\n".join(problems))


class DemandCheckSummary(BaseModel):
    """What a successful check covered."""

    model_config = ConfigDict(extra="forbid")

    records: int
    vehicles: int
    routes: int


# ============================================================
# READING
# ============================================================

def _read_files(folder: Path, problems: list[str]):
    prefix = folder.name
    route_path = folder / f"{prefix}_routes.rou.xml"
    manifest_path = folder / f"{prefix}_manifest.json"
    demand_path = folder / f"{prefix}_demand.json"

    root = plan = demands = None
    missing = [
        path for path in (route_path, manifest_path, demand_path)
        if not path.is_file()
    ]
    for path in missing:
        problems.append(f"{path.name}: file not found")
    if missing:
        return None, None, None

    try:
        root = ET.parse(route_path).getroot()
    except ET.ParseError as exc:
        problems.append(f"{route_path.name}: not valid XML ({exc})")
    try:
        plan = DemandPlan.model_validate_json(manifest_path.read_bytes())
    except ValidationError as exc:
        problems.append(f"{manifest_path.name}: not a valid manifest ({exc.error_count()} errors)")
    try:
        demands = TypeAdapter(list[SimulationDemand]).validate_json(demand_path.read_bytes())
    except ValidationError as exc:
        problems.append(f"{demand_path.name}: not valid demand records ({exc.error_count()} errors)")
    return root, plan, demands


# ============================================================
# CHECKS
# ============================================================

def _check_counts(plan, demands, problems):
    counts = Counter(item.demand_id for item in plan.departures)
    known = {item.demand_id for item in demands}

    for demand in demands:
        found = counts.get(demand.demand_id, 0)
        if found != demand.vehicle_count:
            problems.append(
                f"{demand.demand_id}: {found} vehicles, expected {demand.vehicle_count}"
            )
    for departure in plan.departures:
        if departure.demand_id not in known:
            problems.append(
                f"{departure.vehicle_id}: unknown demand_id {departure.demand_id}"
            )


def _check_vehicles(root, plan, demands, problems):
    movement_of = {item.demand_id: item.movement_id for item in demands}
    vehicles = root.findall("vehicle")

    if len(vehicles) != len(plan.departures):
        problems.append(
            f"route file has {len(vehicles)} vehicles, manifest has {len(plan.departures)}"
        )

    previous = 0.0
    for element, departure in zip(vehicles, plan.departures):
        name = departure.vehicle_id
        if element.get("id") != name:
            problems.append(
                f"vehicle {element.get('id')} in route file, {name} in manifest at the same position"
            )
            continue
        depart = f"{departure.depart_s:.2f}"
        if element.get("depart") != depart:
            problems.append(
                f"{name}: depart {element.get('depart')} in route file, {depart} in manifest"
            )
        expected_route = movement_of.get(departure.demand_id)
        if expected_route is not None and element.get("route") != expected_route:
            problems.append(f"{name}: route {element.get('route')}, expected {expected_route}")
        for attribute, expected in (
            ("type", VEHICLE_TYPE["id"]),
            ("departLane", DEPART_LANE),
            ("departSpeed", DEPART_SPEED),
        ):
            if element.get(attribute) != expected:
                problems.append(
                    f"{name}: {attribute} is {element.get(attribute)}, expected {expected}"
                )
        if departure.depart_s < previous:
            problems.append(f"{name}: departs before the previous vehicle")
        previous = departure.depart_s


def _check_routes(root, mapping, problems):
    mapped = {
        item.movement_id: item.sumo_route_edge_ids
        for item in mapping.movement_mappings
    }
    defined = Counter(item.get("id") for item in root.findall("route"))
    used = {item.get("route") for item in root.findall("vehicle")}

    for route_id, count in sorted(defined.items()):
        if count > 1:
            problems.append(f"route {route_id}: defined {count} times")
    for element in root.findall("route"):
        route_id = element.get("id")
        if route_id not in mapped:
            problems.append(f"route {route_id}: not a mapped movement")
        elif element.get("edges", "").split() != mapped[route_id]:
            problems.append(f"route {route_id}: edges differ from the mapping")
        if route_id not in used:
            problems.append(f"route {route_id}: not used by any vehicle")
    for route_id in sorted(used - set(defined)):
        problems.append(f"route {route_id}: used by vehicles but not defined")


def _check_vehicle_type(root, problems):
    vtypes = root.findall("vType")
    if len(vtypes) != 1:
        problems.append(f"route file has {len(vtypes)} vehicle types, expected 1")
        return
    for attribute, expected in VEHICLE_TYPE.items():
        found = vtypes[0].get(attribute)
        if found != expected:
            problems.append(f"vType: {attribute} is {found}, expected {expected}")
    for attribute in sorted(set(vtypes[0].attrib) - set(VEHICLE_TYPE)):
        problems.append(f"vType: unexpected attribute {attribute}")


def check_generated_demand(
    output_dir: str | Path,
    mapping: NetworkMappingConfig,
    network_path: str | Path,
) -> DemandCheckSummary:
    """Check the files of one generated folder; raise DemandCheckError listing every problem."""

    folder = Path(output_dir).resolve()
    problems: list[str] = []

    problems.extend(validate_network_mappings(mapping, network_path))

    root, plan, demands = _read_files(folder, problems)
    if root is None or plan is None or demands is None:
        raise DemandCheckError(problems)

    _check_counts(plan, demands, problems)
    _check_vehicles(root, plan, demands, problems)
    _check_routes(root, mapping, problems)
    _check_vehicle_type(root, problems)

    if problems:
        raise DemandCheckError(problems)

    return DemandCheckSummary(
        records=len(demands),
        vehicles=len(plan.departures),
        routes=len(root.findall("route")),
    )

"""
Check a folder of generated SUMO demand before it is simulated.

The check reads the three files written by write_sumo_demand back from
the folder, so it verifies exactly what SUMO and Jaadah components will
read, and it can be repeated on a folder at any time without planning
again. It is given the run window and seed, and confirms that:

- the manifest is exactly the plan the planner produces for this run
  from the stored demand records, which also requires every demand
  movement to have exactly one record for every interval of the run
  window, so files from another day, another window or another seed,
  or with incomplete demand, cannot pass;
- every demand ID, movement–interval pair and vehicle ID is unique,
  checked before any lookup by ID so duplicates cannot be merged;
- every demand record has exactly its vehicle_count vehicles;
- the manifest and the route file list the same vehicles, in the same
  order, with the same departure times;
- every vehicle uses its own movement's route, and every route equals
  the mapped route of its movement;
- the mapped routes are valid in the SUMO network, using the mapping
  validator;
- the vehicle type and insertion settings are the agreed ones;
- the route file contains nothing else: only the elements and
  attributes the writer produces are accepted, so no other way of
  creating vehicles (such as flow or trip elements) can pass.

All problems are reported together.
"""

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from ..mapping.validator import validate_network_mappings
from ..models.mappings import NetworkMappingConfig
from ..models.traffic import SimulationDemand
from .planner import (
    DemandPlan,
    DemandPlanningError,
    RunWindow,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
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

ALLOWED_ATTRIBUTES = {
    "route": {"id", "edges"},
    "vehicle": {"id", "type", "route", "depart", "departLane", "departSpeed"},
}


def _check_structure(root, problems):
    """Accept only the elements and attributes the writer produces."""

    for element in root:
        tag = element.tag
        name = element.get("id", tag)
        if tag not in ("vType", "route", "vehicle"):
            problems.append(f"unsupported element <{tag}> in route file")
            continue
        for child in element:
            problems.append(f"{name}: unexpected element <{child.tag}>")
        if tag in ALLOWED_ATTRIBUTES:
            label = name if tag == "vehicle" else f"route {name}"
            for attribute in sorted(set(element.attrib) - ALLOWED_ATTRIBUTES[tag]):
                problems.append(f"{label}: unexpected attribute {attribute}")


def _check_uniqueness(root, plan, demands, problems):
    """Report repeated identities before any lookup by ID could merge them."""

    for demand_id, count in sorted(Counter(item.demand_id for item in demands).items()):
        if count > 1:
            problems.append(f"{demand_id}: demand_id appears {count} times in the demand file")
    records = Counter((item.movement_id, item.interval_start) for item in demands)
    for (movement_id, start), count in sorted(records.items()):
        if count > 1:
            problems.append(
                f"{movement_id} {start.isoformat()}: {count} demand records "
                "for one movement and interval"
            )
    for vehicle_id, count in sorted(Counter(item.vehicle_id for item in plan.departures).items()):
        if count > 1:
            problems.append(f"{vehicle_id}: vehicle_id appears {count} times in the manifest")
    for vehicle_id, count in sorted(Counter(item.get("id") for item in root.findall("vehicle")).items()):
        if count > 1:
            problems.append(f"{vehicle_id}: vehicle id appears {count} times in the route file")


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


MAX_PLAN_DIFFERENCES = 20


def _check_against_run(plan, demands, mapping, network_path, window, seed, problems):
    """Re-plan this run from the stored records and require the manifest to equal it."""

    try:
        expected = plan_departures(
            demands,
            window=window,
            routes=movement_routes(mapping),
            expected_movements=demand_movement_ids(mapping),
            free_flow_s=compute_free_flow_times(mapping, network_path),
            seed=seed,
        )
    except DemandPlanningError as exc:
        problems.extend(f"run window: {problem}" for problem in exc.problems)
        return

    planned = {item.vehicle_id: item for item in expected.departures}
    stored = {item.vehicle_id: item for item in plan.departures}
    differences = []
    for vehicle_id in sorted(set(stored) - set(planned)):
        differences.append(f"{vehicle_id}: in the manifest but not planned for this run")
    for vehicle_id in sorted(set(planned) - set(stored)):
        differences.append(f"{vehicle_id}: planned for this run but missing from the manifest")
    for vehicle_id in sorted(set(stored) & set(planned)):
        found, wanted = stored[vehicle_id], planned[vehicle_id]
        if found.demand_id != wanted.demand_id:
            differences.append(
                f"{vehicle_id}: demand_id {found.demand_id} in the manifest, "
                f"{wanted.demand_id} planned for this run"
            )
        if found.depart_s != wanted.depart_s:
            differences.append(
                f"{vehicle_id}: depart {found.depart_s:.2f} in the manifest, "
                f"{wanted.depart_s:.2f} planned for this run"
            )

    problems.extend(differences[:MAX_PLAN_DIFFERENCES])
    if len(differences) > MAX_PLAN_DIFFERENCES:
        problems.append(
            f"... and {len(differences) - MAX_PLAN_DIFFERENCES} more differences "
            "from the plan for this run"
        )


def check_generated_demand(
    output_dir: str | Path,
    mapping: NetworkMappingConfig,
    network_path: str | Path,
    *,
    window: RunWindow,
    seed: int,
) -> DemandCheckSummary:
    """
    Check the files of one generated folder against the run they are for;
    raise DemandCheckError listing every problem.
    """

    folder = Path(output_dir).resolve()
    problems: list[str] = []

    problems.extend(validate_network_mappings(mapping, network_path))

    root, plan, demands = _read_files(folder, problems)
    if root is None or plan is None or demands is None:
        raise DemandCheckError(problems)

    _check_structure(root, problems)
    before = len(problems)
    _check_uniqueness(root, plan, demands, problems)
    if len(problems) > before:
        # Counting by ID would merge the duplicates and hide them.
        raise DemandCheckError(problems)
    _check_against_run(plan, demands, mapping, network_path, window, seed, problems)
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

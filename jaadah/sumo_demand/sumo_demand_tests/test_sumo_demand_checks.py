import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.checks import DemandCheckError, check_generated_demand
from jaadah.sumo_demand.planner import DemandPlan, PlannedDeparture
from jaadah.sumo_demand.writer import write_sumo_demand

RIYADH = timezone(timedelta(hours=3))


def at(hour, minute):
    return datetime(2026, 10, 20, hour, minute, tzinfo=RIYADH)


# ============================================================
# HELPERS
# ============================================================

# Two unsignalised movements on a four-edge network:
# MOV_S_E_BYPASS = s_in -> e_out, MOV_W_E = w_in -> e_out.
NETWORK = """<net>
    <edge id="s_in" from="n_s" to="c"><lane id="s_in_0" index="0" speed="13.89" length="100.00"/></edge>
    <edge id="w_in" from="n_w" to="c"><lane id="w_in_0" index="0" speed="19.44" length="100.00"/></edge>
    <edge id="e_out" from="c" to="n_e"><lane id="e_out_0" index="0" speed="19.44" length="100.00"/></edge>
    <edge id="n_out" from="c" to="n_n"><lane id="n_out_0" index="0" speed="13.89" length="100.00"/></edge>
    <connection from="s_in" to="e_out" fromLane="0" toLane="0"/>
    <connection from="w_in" to="e_out" fromLane="0" toLane="0"/>
</net>"""


@pytest.fixture
def network(tmp_path):
    path = tmp_path / "small.net.xml"
    path.write_text(NETWORK, encoding="utf-8")
    return path


def mapping_for(network, bypass_edges=("s_in", "e_out")):
    movement = {"intersection_id": "INT_001", "signal_controlled": False}
    sha256 = hashlib.sha256(network.read_bytes()).hexdigest()
    return NetworkMappingConfig.model_validate({
        "schema_version": "2.0",
        "mapping_version": "test",
        "network": {"version": "small", "path": network.name, "sha256": sha256},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "movement_mappings": [
            {"movement_id": "MOV_S_E_BYPASS", "sumo_route_edge_ids": list(bypass_edges), **movement},
            {"movement_id": "MOV_W_E", "sumo_route_edge_ids": ["w_in", "e_out"], **movement},
        ],
    })


def demand(demand_id, movement_id, count):
    return SimulationDemand(
        demand_id=demand_id,
        interval_start=at(8, 0),
        interval_end=at(8, 15),
        movement_id=movement_id,
        vehicle_count=count,
        source="synthetic",
        source_observation_ids=[f"OBS_{demand_id}"],
    )


DEMANDS = [
    demand("DEM_BYPASS_0815", "MOV_S_E_BYPASS", 2),
    demand("DEM_WE_0815", "MOV_W_E", 1),
]


def car(vehicle_id, demand_id, depart_s):
    return PlannedDeparture(vehicle_id=vehicle_id, demand_id=demand_id, depart_s=depart_s)


PLAN = DemandPlan(departures=[
    car("MOV_S_E_BYPASS__20261020T0815__001", "DEM_BYPASS_0815", 853.01),
    car("MOV_W_E__20261020T0815__001", "DEM_WE_0815", 900.0),
    car("MOV_S_E_BYPASS__20261020T0815__002", "DEM_BYPASS_0815", 966.57),
])


@pytest.fixture
def folder(tmp_path, network):
    return write_sumo_demand(PLAN, DEMANDS, mapping_for(network), tmp_path / "baseline").route_file.parent


def route_file(folder):
    return folder / "baseline_routes.rou.xml"


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def check(folder, network, mapping=None):
    return check_generated_demand(folder, mapping or mapping_for(network), network)


def problems_of(exc_info):
    return "\n".join(exc_info.value.problems)


# ============================================================
# CORRECT FOLDER
# ============================================================

def test_correct_folder_passes_with_summary(folder, network):
    summary = check(folder, network)

    assert summary.model_dump() == {"records": 2, "vehicles": 3, "routes": 2}


# ============================================================
# BROKEN FILES
# ============================================================

def test_missing_file_is_reported(folder, network):
    (folder / "baseline_manifest.json").unlink()

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "baseline_manifest.json: file not found"


def test_deleted_vehicle_breaks_the_count_and_the_match(folder, network):
    edit(
        route_file(folder),
        '    <vehicle id="MOV_W_E__20261020T0815__001" type="car" route="MOV_W_E" '
        'depart="900.00" departLane="best" departSpeed="max" />\n',
        "",
    )

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "route file has 2 vehicles, manifest has 3" in problems_of(exc)


def test_record_with_too_few_vehicles_is_reported(folder, network):
    demand_file = folder / "baseline_demand.json"
    edit(demand_file, '"vehicle_count": 2', '"vehicle_count": 3')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "DEM_BYPASS_0815: 2 vehicles, expected 3"


def test_changed_departure_is_reported(folder, network):
    edit(route_file(folder), 'depart="966.57"', 'depart="966.75"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == (
        "MOV_S_E_BYPASS__20261020T0815__002: depart 966.75 in route file, 966.57 in manifest"
    )


def test_vehicle_on_the_wrong_route_is_reported(folder, network):
    edit(
        route_file(folder),
        'id="MOV_W_E__20261020T0815__001" type="car" route="MOV_W_E"',
        'id="MOV_W_E__20261020T0815__001" type="car" route="MOV_S_E_BYPASS"',
    )

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "MOV_W_E__20261020T0815__001: route MOV_S_E_BYPASS, expected MOV_W_E" in problems_of(exc)
    assert "route MOV_W_E: not used by any vehicle" in problems_of(exc)


def test_route_that_differs_from_the_mapping_is_reported(folder, network):
    edit(route_file(folder), 'edges="s_in e_out"', 'edges="s_in n_out"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "route MOV_S_E_BYPASS: edges differ from the mapping"


def test_unknown_demand_id_is_reported(folder, network):
    edit(folder / "baseline_manifest.json", '"demand_id": "DEM_WE_0815"', '"demand_id": "DEM_X"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "MOV_W_E__20261020T0815__001: unknown demand_id DEM_X" in problems_of(exc)
    assert "DEM_WE_0815: 0 vehicles, expected 1" in problems_of(exc)


def test_changed_vehicle_type_is_reported(folder, network):
    edit(route_file(folder), 'accel="2.6"', 'accel="3.0"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "vType: accel is 3.0, expected 2.6"


def test_added_lane_change_tuning_is_reported(folder, network):
    edit(route_file(folder), 'speedDev="0.1"', 'speedDev="0.1" lcSpeedGain="0.3"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "vType: unexpected attribute lcSpeedGain"


def test_changed_insertion_setting_is_reported(folder, network):
    edit(
        route_file(folder),
        'depart="900.00" departLane="best" departSpeed="max"',
        'depart="900.00" departLane="best" departSpeed="0"',
    )

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "MOV_W_E__20261020T0815__001: departSpeed is 0, expected max"


def test_vehicles_out_of_time_order_are_reported(folder, network):
    manifest = folder / "baseline_manifest.json"
    edit(manifest, '"depart_s": 900.0', '"depart_s": 800.0')
    edit(route_file(folder), 'depart="900.00"', 'depart="800.00"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "MOV_W_E__20261020T0815__001: departs before the previous vehicle"


def test_route_not_valid_in_the_network_is_reported(folder, network):
    # s_in -> n_out exists as edges but has no connection in the network.
    mapping = mapping_for(network, bypass_edges=("s_in", "n_out"))

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network, mapping=mapping)

    assert "Movement MOV_S_E_BYPASS: no legal SUMO connection s_in -> n_out" in problems_of(exc)
    assert "route MOV_S_E_BYPASS: edges differ from the mapping" in problems_of(exc)

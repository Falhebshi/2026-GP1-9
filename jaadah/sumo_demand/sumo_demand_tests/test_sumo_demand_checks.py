import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.scenario import Scenario, SimulationConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.checks import DemandCheckError, check_generated_demand
from jaadah.sumo_demand.planner import (
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import write_sumo_demand

RIYADH = timezone(timedelta(hours=3))
SEED = 42


def at(hour, minute, day=20):
    return datetime(2026, 10, day, hour, minute, tzinfo=RIYADH)


# ============================================================
# HELPERS
# ============================================================

# Two unsignalised demand movements on a four-edge network:
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
    sha256 = hashlib.sha256(network.read_bytes()).hexdigest()
    movement = {"intersection_id": "INT_001", "signal_controlled": False}
    detector = {"source": "synthetic", "site_id": "9", "intersection_id": "INT_001",
                "mapping_status": "usable"}
    return NetworkMappingConfig.model_validate({
        "schema_version": "2.0",
        "mapping_version": "test",
        "network": {"version": "small", "path": network.name, "sha256": sha256},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "approach_mappings": [
            {"approach_id": "APP_S", "intersection_id": "INT_001", "approach_side": "south"},
            {"approach_id": "APP_W", "intersection_id": "INT_001", "approach_side": "west"},
        ],
        "approach_lanes": [
            {"lane_id": "LANE_S_1", "approach_id": "APP_S", "lane_index": 1,
             "served_movement_ids": ["MOV_S_E_BYPASS"], "lane_width_m": 3.2},
            {"lane_id": "LANE_W_1", "approach_id": "APP_W", "lane_index": 1,
             "served_movement_ids": ["MOV_W_E"], "lane_width_m": 3.2},
        ],
        "lane_mappings": [
            {"lane_id": "LANE_S_1", "sumo_lane_ids": ["s_in_0"]},
            {"lane_id": "LANE_W_1", "sumo_lane_ids": ["w_in_0"]},
        ],
        "detector_mappings": [
            {"detector_id": "1", "lane_id": "LANE_S_1", "movement_ids": ["MOV_S_E_BYPASS"], **detector},
            {"detector_id": "2", "lane_id": "LANE_W_1", "movement_ids": ["MOV_W_E"], **detector},
        ],
        "movement_mappings": [
            {"movement_id": "MOV_S_E_BYPASS", "approach_id": "APP_S",
             "sumo_route_edge_ids": list(bypass_edges), **movement},
            {"movement_id": "MOV_W_E", "approach_id": "APP_W",
             "sumo_route_edge_ids": ["w_in", "e_out"], **movement},
        ],
    })


def make_window():
    # Analysis 08:00-08:15 with 15 min warm-up and clearance: 07:45-08:30.
    scenario = Scenario(
        scenario_id="SCN_TEST", intersection_id="INT_001", time_context="historical",
        control_mode="baseline", start_time=at(8, 0), end_time=at(8, 15),
    )
    config = SimulationConfig(warmup_duration_s=900, clearance_duration_s=900)
    return build_run_window(scenario, config)


COUNTS = {
    ("MOV_S_E_BYPASS", (7, 45)): 1, ("MOV_S_E_BYPASS", (8, 0)): 2, ("MOV_S_E_BYPASS", (8, 15)): 0,
    ("MOV_W_E", (7, 45)): 1, ("MOV_W_E", (8, 0)): 1, ("MOV_W_E", (8, 15)): 1,
}


def demands():
    records = []
    for (movement_id, (hour, minute)), count in COUNTS.items():
        start = at(hour, minute)
        end = start + timedelta(minutes=15)
        records.append(SimulationDemand(
            demand_id=f"DEM_{movement_id}_{end:%H%M}",
            interval_start=start,
            interval_end=end,
            movement_id=movement_id,
            vehicle_count=count,
            source="synthetic",
            source_observation_ids=[f"OBS_{movement_id}_{end:%H%M}"],
        ))
    return records


@pytest.fixture
def folder(tmp_path, network):
    mapping = mapping_for(network)
    records = demands()
    plan = plan_departures(
        records,
        window=make_window(),
        routes=movement_routes(mapping),
        expected_movements=demand_movement_ids(mapping),
        free_flow_s=compute_free_flow_times(mapping, network),
        seed=SEED,
    )
    return write_sumo_demand(plan, records, mapping, tmp_path / "baseline").route_file.parent


def route_file(folder):
    return folder / "baseline_routes.rou.xml"


def manifest(folder):
    return folder / "baseline_manifest.json"


def demand_file(folder):
    return folder / "baseline_demand.json"


def vehicle_line(folder, vehicle_id):
    """The route-file line of one vehicle, exactly as written."""

    for line in route_file(folder).read_text(encoding="utf-8").splitlines():
        if f'<vehicle id="{vehicle_id}"' in line:
            return line
    raise AssertionError(vehicle_id)


def depart_of(folder, vehicle_id):
    return re.search(r'depart="([0-9.]+)"', vehicle_line(folder, vehicle_id)).group(1)


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def check(folder, network, mapping=None, seed=SEED):
    return check_generated_demand(
        folder, mapping or mapping_for(network), network, window=make_window(), seed=seed
    )


def problems_of(exc_info):
    return "\n".join(exc_info.value.problems)


BYPASS_1 = "MOV_S_E_BYPASS__20261020T0815__001"
BYPASS_2 = "MOV_S_E_BYPASS__20261020T0815__002"
WEST = "MOV_W_E__20261020T0815__001"


# ============================================================
# CORRECT FOLDER
# ============================================================

def test_correct_folder_passes_with_summary(folder, network):
    summary = check(folder, network)

    assert summary.model_dump() == {"records": 6, "vehicles": 6, "routes": 2}


# ============================================================
# BROKEN FILES
# ============================================================

def test_missing_file_is_reported(folder, network):
    manifest(folder).unlink()

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "baseline_manifest.json: file not found"


def test_deleted_vehicle_breaks_the_match(folder, network):
    edit(route_file(folder), vehicle_line(folder, WEST) + "\n", "")

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "route file has 5 vehicles, manifest has 6" in problems_of(exc)


def test_record_with_too_few_vehicles_is_reported(folder, network):
    edit(demand_file(folder), '"vehicle_count": 2', '"vehicle_count": 3')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "DEM_MOV_S_E_BYPASS_0815: 2 vehicles, expected 3" in problems_of(exc)


def test_changed_departure_is_reported(folder, network):
    depart = depart_of(folder, BYPASS_2)
    changed = f"{float(depart) + 0.18:.2f}"
    edit(route_file(folder), f'id="{BYPASS_2}" type="car" route="MOV_S_E_BYPASS" depart="{depart}"',
         f'id="{BYPASS_2}" type="car" route="MOV_S_E_BYPASS" depart="{changed}"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{BYPASS_2}: depart {changed} in route file, {depart} in manifest"


def test_vehicle_on_the_wrong_route_is_reported(folder, network):
    edit(route_file(folder), f'id="{WEST}" type="car" route="MOV_W_E"',
         f'id="{WEST}" type="car" route="MOV_S_E_BYPASS"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert f"{WEST}: route MOV_S_E_BYPASS, expected MOV_W_E" in problems_of(exc)


def test_route_that_differs_from_the_mapping_is_reported(folder, network):
    edit(route_file(folder), 'edges="s_in e_out"', 'edges="s_in n_out"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "route MOV_S_E_BYPASS: edges differ from the mapping"


def test_unknown_demand_id_is_reported(folder, network):
    edit(manifest(folder), '"demand_id": "DEM_MOV_W_E_0815"', '"demand_id": "DEM_X"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert f"{WEST}: unknown demand_id DEM_X" in problems_of(exc)
    assert "DEM_MOV_W_E_0815: 0 vehicles, expected 1" in problems_of(exc)


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
    line = vehicle_line(folder, WEST)
    edit(route_file(folder), line, line.replace('departSpeed="max"', 'departSpeed="0"'))

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{WEST}: departSpeed is 0, expected max"


def test_vehicles_out_of_time_order_are_reported(folder, network):
    # Moving the last vehicle to second 0 in both files breaks the order.
    last = json.loads(manifest(folder).read_text(encoding="utf-8"))["departures"][-1]
    depart = depart_of(folder, last["vehicle_id"])
    edit(manifest(folder), f'"depart_s": {last["depart_s"]}', '"depart_s": 0.0')
    edit(route_file(folder), f'depart="{depart}"', 'depart="0.00"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert f"{last['vehicle_id']}: departs before the previous vehicle" in problems_of(exc)


def test_route_not_valid_in_the_network_is_reported(folder, network):
    # s_in -> n_out exists as edges but has no connection in the network.
    mapping = mapping_for(network, bypass_edges=("s_in", "n_out"))

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network, mapping=mapping)

    assert "Lane LANE_S_1: terminal lane cannot serve movement MOV_S_E_BYPASS" in problems_of(exc)
    assert "route MOV_S_E_BYPASS: edges differ from the mapping" in problems_of(exc)


# ============================================================
# OTHER WAYS OF CREATING VEHICLES
# ============================================================

def first_vehicle_line(folder):
    first = json.loads(manifest(folder).read_text(encoding="utf-8"))["departures"][0]
    return vehicle_line(folder, first["vehicle_id"])


def test_extra_flow_is_rejected(folder, network):
    # A flow before the vehicles would make SUMO insert 2 more vehicles.
    line = first_vehicle_line(folder)
    edit(route_file(folder), line,
         '    <flow id="extra" type="car" route="MOV_W_E" begin="0" end="100" number="2" />\n' + line)

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "unsupported element <flow> in route file"


def test_extra_trip_is_rejected(folder, network):
    line = first_vehicle_line(folder)
    edit(route_file(folder), line,
         '    <trip id="extra" type="car" depart="0" from="w_in" to="e_out" />\n' + line)

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == "unsupported element <trip> in route file"


def test_extra_vehicle_attribute_is_rejected(folder, network):
    line = vehicle_line(folder, WEST)
    edit(route_file(folder), line, line.replace('departLane="best"', 'departLane="best" departPos="50"'))

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{WEST}: unexpected attribute departPos"


def test_element_inside_a_vehicle_is_rejected(folder, network):
    line = vehicle_line(folder, WEST)
    edit(route_file(folder), line,
         line.replace(" />", '><stop lane="e_out_0" duration="60" /></vehicle>'))

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{WEST}: unexpected element <stop>"


# ============================================================
# UNIQUE IDENTITIES
# ============================================================

def records_in(folder):
    return json.loads(demand_file(folder).read_text(encoding="utf-8"))


def save_records(folder, records):
    demand_file(folder).write_text(json.dumps(records, indent=2), encoding="utf-8")


def test_demand_record_stored_twice_is_reported(folder, network):
    records = records_in(folder)
    save_records(folder, records + [records[0]])

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert f"{records[0]['demand_id']}: demand_id appears 2 times in the demand file" in problems_of(exc)


def test_second_record_for_one_movement_and_interval_is_reported(folder, network):
    records = records_in(folder)
    copy = dict(records[0], demand_id="DEM_COPY")
    save_records(folder, records + [copy])

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == (
        f"{records[0]['movement_id']} {records[0]['interval_start']}: "
        "2 demand records for one movement and interval"
    )


def test_duplicate_vehicle_id_in_the_manifest_is_reported(folder, network):
    edit(manifest(folder), f'"vehicle_id": "{WEST}"', f'"vehicle_id": "{BYPASS_1}"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{BYPASS_1}: vehicle_id appears 2 times in the manifest"


def test_duplicate_vehicle_id_in_the_route_file_is_reported(folder, network):
    edit(route_file(folder), f'id="{WEST}"', f'id="{BYPASS_1}"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{BYPASS_1}: vehicle id appears 2 times in the route file"


# ============================================================
# THE RUN THE FILES BELONG TO
# ============================================================

def test_record_moved_to_the_next_day_is_reported(folder, network):
    records = records_in(folder)
    moved = records[-1]
    for field in ("interval_start", "interval_end"):
        moved[field] = moved[field].replace("2026-10-20", "2026-10-21")
    save_records(folder, records)

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert "outside the run window" in problems_of(exc)
    assert "run window: missing demand:" in problems_of(exc)


def test_departures_shifted_after_the_run_are_reported(folder, network):
    # Both files shifted by the same 6,000 s still agree with each other.
    data = json.loads(manifest(folder).read_text(encoding="utf-8"))
    for item in data["departures"]:
        item["depart_s"] = round(item["depart_s"] + 6000, 2)
    manifest(folder).write_text(json.dumps(data, indent=2), encoding="utf-8")
    text = route_file(folder).read_text(encoding="utf-8")
    text = re.sub(r'depart="([0-9.]+)"', lambda m: f'depart="{float(m.group(1)) + 6000:.2f}"', text)
    route_file(folder).write_text(text, encoding="utf-8")

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert f"{WEST}: depart" in problems_of(exc)
    assert "planned for this run" in problems_of(exc)


def test_missing_interval_is_reported(folder, network):
    # The 0-vehicle record leaves no vehicles behind, so only the run window shows it.
    save_records(folder, [item for item in records_in(folder) if item["vehicle_count"] != 0])

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == (
        "run window: missing demand: MOV_S_E_BYPASS "
        "2026-10-20T08:15:00+03:00 - 2026-10-20T08:30:00+03:00"
    )


def test_departure_changed_by_one_hundredth_is_reported(folder, network):
    depart = depart_of(folder, WEST)
    changed = f"{float(depart) + 0.01:.2f}"
    edit(manifest(folder), f'"depart_s": {float(depart)}', f'"depart_s": {float(changed)}')
    edit(route_file(folder), f'depart="{depart}"', f'depart="{changed}"')

    with pytest.raises(DemandCheckError) as exc:
        check(folder, network)

    assert problems_of(exc) == f"{WEST}: depart {changed} in the manifest, {depart} planned for this run"


def test_files_made_with_another_seed_are_reported(folder, network):
    with pytest.raises(DemandCheckError) as exc:
        check(folder, network, seed=SEED + 1)

    assert "planned for this run" in problems_of(exc)

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter

from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import DemandPlan, PlannedDeparture
from jaadah.sumo_demand.writer import DemandWritingError, write_sumo_demand

RIYADH = timezone(timedelta(hours=3))


def at(hour, minute):
    return datetime(2026, 10, 20, hour, minute, tzinfo=RIYADH)


# ============================================================
# HELPERS
# ============================================================

def mapping():
    movement = {"intersection_id": "INT_001", "signal_controlled": False}
    return NetworkMappingConfig.model_validate({
        "schema_version": "2.0",
        "mapping_version": "test",
        "network": {"version": "small", "path": "small.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "movement_mappings": [
            {"movement_id": "MOV_S_E_BYPASS", "sumo_route_edge_ids": ["E3", "539502456#5"], **movement},
            {"movement_id": "MOV_W_E", "sumo_route_edge_ids": ["133793727#0", "382508030#1"], **movement},
            {"movement_id": "MOV_N_E", "sumo_route_edge_ids": ["586185409#6.147", "382508030#1"], **movement},
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
    demand("DEM_NE_0815", "MOV_N_E", 0),
]


def car(vehicle_id, demand_id, depart_s):
    return PlannedDeparture(vehicle_id=vehicle_id, demand_id=demand_id, depart_s=depart_s)


PLAN = DemandPlan(departures=[
    car("MOV_S_E_BYPASS__20261020T0815__001", "DEM_BYPASS_0815", 853.01),
    car("MOV_W_E__20261020T0815__001", "DEM_WE_0815", 900.0),
    car("MOV_S_E_BYPASS__20261020T0815__002", "DEM_BYPASS_0815", 966.57),
])


def write(tmp_path, plan=PLAN, demands=DEMANDS, folder="baseline"):
    return write_sumo_demand(plan, demands, mapping(), tmp_path / folder)


def problems_of(exc_info):
    return "\n".join(exc_info.value.problems)


# ============================================================
# ROUTE FILE
# ============================================================

def test_route_file_has_the_agreed_vehicle_type(tmp_path):
    root = ET.parse(write(tmp_path).route_file).getroot()
    vtypes = root.findall("vType")

    assert len(vtypes) == 1
    assert vtypes[0].attrib == {
        "id": "car", "vClass": "passenger", "accel": "2.6", "decel": "4.5",
        "sigma": "0.5", "length": "5.0", "minGap": "2.5", "speedDev": "0.1",
    }


def test_route_file_defines_each_used_route_once(tmp_path):
    root = ET.parse(write(tmp_path).route_file).getroot()
    routes = {item.get("id"): item.get("edges") for item in root.findall("route")}

    # MOV_N_E has a record with 0 cars, so it needs no route.
    assert routes == {
        "MOV_S_E_BYPASS": "E3 539502456#5",
        "MOV_W_E": "133793727#0 382508030#1",
    }


def test_route_file_lists_every_car_in_departure_order(tmp_path):
    root = ET.parse(write(tmp_path).route_file).getroot()
    vehicles = [item.attrib for item in root.findall("vehicle")]

    assert vehicles == [
        {"id": "MOV_S_E_BYPASS__20261020T0815__001", "type": "car",
         "route": "MOV_S_E_BYPASS", "depart": "853.01",
         "departLane": "best", "departSpeed": "max"},
        {"id": "MOV_W_E__20261020T0815__001", "type": "car",
         "route": "MOV_W_E", "depart": "900.00",
         "departLane": "best", "departSpeed": "max"},
        {"id": "MOV_S_E_BYPASS__20261020T0815__002", "type": "car",
         "route": "MOV_S_E_BYPASS", "depart": "966.57",
         "departLane": "best", "departSpeed": "max"},
    ]


def test_vehicle_type_adds_no_lane_change_tuning(tmp_path):
    # Instant lane changes, SUMO default: no lcSpeedGain, no lateral speed.
    text = write(tmp_path).route_file.read_text(encoding="utf-8")

    assert "lcSpeedGain" not in text
    assert "maxSpeedLat" not in text


# ============================================================
# MANIFEST AND DEMAND FILES
# ============================================================

def test_manifest_reads_back_as_the_same_plan(tmp_path):
    result = write(tmp_path)

    assert DemandPlan.model_validate_json(result.manifest_file.read_bytes()) == PLAN


def test_demand_file_reads_back_as_the_same_records(tmp_path):
    result = write(tmp_path)
    records = TypeAdapter(list[SimulationDemand]).validate_json(result.demand_file.read_bytes())

    assert sorted(records, key=lambda item: item.demand_id) == sorted(
        DEMANDS, key=lambda item: item.demand_id
    )


def test_demand_file_keeps_zero_count_records(tmp_path):
    records = json.loads(write(tmp_path).demand_file.read_text(encoding="utf-8"))

    assert {"DEM_NE_0815": 0} == {
        item["demand_id"]: item["vehicle_count"]
        for item in records if item["vehicle_count"] == 0
    }


# ============================================================
# FINGERPRINTS AND FILE NAMES
# ============================================================

def test_fingerprints_match_the_written_files(tmp_path):
    result = write(tmp_path)

    assert result.route_file_sha256 == hashlib.sha256(result.route_file.read_bytes()).hexdigest()
    assert result.manifest_sha256 == hashlib.sha256(result.manifest_file.read_bytes()).hexdigest()
    assert result.demand_sha256 == hashlib.sha256(result.demand_file.read_bytes()).hexdigest()


def test_writing_twice_gives_identical_fingerprints(tmp_path):
    first = write(tmp_path, folder="first")
    second = write(tmp_path, folder="first")

    assert first == second


def test_record_order_does_not_change_the_demand_file(tmp_path):
    forward = write(tmp_path, folder="run")
    backward = write(tmp_path, demands=list(reversed(DEMANDS)), folder="run")

    assert forward.demand_sha256 == backward.demand_sha256


def test_files_are_named_after_their_folder(tmp_path):
    result = write(tmp_path, folder="baseline_left_minus_20")

    assert result.route_file.name == "baseline_left_minus_20_routes.rou.xml"
    assert result.manifest_file.name == "baseline_left_minus_20_manifest.json"
    assert result.demand_file.name == "baseline_left_minus_20_demand.json"
    assert result.route_file.parent == (tmp_path / "baseline_left_minus_20").resolve()


def test_files_use_unix_line_endings_only(tmp_path):
    result = write(tmp_path)

    for path in (result.route_file, result.manifest_file, result.demand_file):
        assert b"\r" not in path.read_bytes()


def test_no_temporary_files_are_left(tmp_path):
    folder = write(tmp_path).route_file.parent

    assert sorted(item.name for item in folder.iterdir()) == [
        "baseline_demand.json", "baseline_manifest.json", "baseline_routes.rou.xml",
    ]


# ============================================================
# INVALID INPUT
# ============================================================

@pytest.mark.parametrize("plan, demands, message", [
    (
        DemandPlan(departures=[car("MOV_X__20261020T0815__001", "DEM_UNKNOWN", 1.0)]),
        DEMANDS,
        "MOV_X__20261020T0815__001: demand_id DEM_UNKNOWN is not among the demand records",
    ),
    (
        PLAN,
        DEMANDS + [demand("DEM_X_0815", "MOV_X", 3)],
        "DEM_X_0815 (MOV_X): movement is not in the mapping",
    ),
    (
        PLAN,
        DEMANDS + [demand("DEM_WE_0815", "MOV_W_E", 1)],
        "DEM_WE_0815: duplicate demand_id",
    ),
    (
        DemandPlan(departures=list(reversed(PLAN.departures))),
        DEMANDS,
        "departures are not sorted by time",
    ),
])
def test_invalid_input_is_reported_and_nothing_is_written(tmp_path, plan, demands, message):
    with pytest.raises(DemandWritingError) as exc:
        write(tmp_path, plan=plan, demands=demands)

    assert message in problems_of(exc)
    assert not (tmp_path / "baseline").exists()


def test_all_problems_are_reported_together(tmp_path):
    plan = DemandPlan(departures=[car("MOV_X__20261020T0815__001", "DEM_UNKNOWN", 1.0)])
    demands = DEMANDS + [demand("DEM_X_0815", "MOV_X", 3)]

    with pytest.raises(DemandWritingError) as exc:
        write(tmp_path, plan=plan, demands=demands)

    assert len(exc.value.problems) == 2
    assert str(exc.value).startswith("Cannot write SUMO demand:\n")


def test_failure_while_writing_keeps_the_previous_files(tmp_path, monkeypatch):
    first = write(tmp_path)
    before = first.route_file.read_bytes()

    def fail(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(first.route_file))

    monkeypatch.setattr("jaadah.sumo_demand.writer.os.replace", fail)
    changed = DemandPlan(departures=PLAN.departures[:1])

    with pytest.raises(DemandWritingError) as exc:
        write(tmp_path, plan=changed)

    assert "could not write" in problems_of(exc)
    assert first.route_file.read_bytes() == before
    assert not list(first.route_file.parent.glob("*.tmp"))

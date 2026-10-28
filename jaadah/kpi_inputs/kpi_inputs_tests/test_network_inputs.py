from pathlib import Path

import pytest

from jaadah.kpi_inputs.network_inputs import NetworkInputsError, build_network_inputs
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"

ANALYSED = {
    "MOV_E_W", "MOV_E_S", "MOV_S_W", "MOV_W_E", "MOV_W_N", "MOV_N_E",
    "MOV_S_E_BYPASS", "MOV_W_S_SLIP", "MOV_N_W_SLIP",
}


@pytest.fixture
def config():
    return load_network_mappings(MAPPING_PATH)


def changed(config, **updates):
    data = config.model_dump()
    data.update(updates)
    return NetworkMappingConfig.model_validate(data)


def test_study_area_inputs(config):
    inputs = build_network_inputs(config)

    assert len(inputs.lanes) == 16
    assert set(inputs.movements) == set(inputs.movement_attributes) == ANALYSED
    assert inputs.movements["MOV_S_W"].approach_id == "APP_S"
    assert inputs.movement_attributes["MOV_S_W"].movement_type.value == "left"


def test_ramps_u_turns_and_tunnels_are_left_out(config):
    movements = build_network_inputs(config).movements

    assert not {"MOV_E_E_UTURN", "MOV_E_W_ONRAMP", "MOV_N_S_TUNNEL"} & set(movements)


def test_lane_serving_a_movement_without_attributes_rejected(config):
    """A draft whose attributes are not complete yet."""
    attributes = [a for a in config.model_dump()["movement_attributes"] if a["movement_id"] != "MOV_E_S"]

    with pytest.raises(NetworkInputsError) as raised:
        build_network_inputs(changed(config, movement_attributes=attributes))

    assert raised.value.problems == [
        "MOV_E_S: served by an approach lane but has no movement attributes"]


def test_analysed_movement_without_lane_rejected(config):
    lanes = [lane for lane in config.model_dump()["approach_lanes"] if lane["lane_id"] != "LANE_W_4"]
    mappings = [m for m in config.model_dump()["lane_mappings"] if m["lane_id"] != "LANE_W_4"]
    detectors = [d for d in config.model_dump()["detector_mappings"] if d.get("lane_id") != "LANE_W_4"]

    with pytest.raises(NetworkInputsError) as raised:
        build_network_inputs(changed(
            config, approach_lanes=lanes, lane_mappings=mappings, detector_mappings=detectors))

    assert raised.value.problems == [
        "MOV_W_S_SLIP: has movement attributes but no approach lane serves it"]


def test_every_gap_is_listed(config):
    attributes = [a for a in config.model_dump()["movement_attributes"]
                  if a["movement_id"] not in {"MOV_E_S", "MOV_N_E"}]

    with pytest.raises(NetworkInputsError) as raised:
        build_network_inputs(changed(config, movement_attributes=attributes))

    assert len(raised.value.problems) == 2

import json

import pytest
from pydantic import ValidationError

from jaadah.mapping.mapping_loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig


@pytest.fixture
def valid_config():
    return {
        "schema_version": "1.0",
        "mapping_version": "1.0",
        "network": {
            "version": "test_network_v1",
            "path": "data/processed/road_network/test.net.xml",
            "sha256": "a" * 64,
        },
        "intersection_mapping": {
            "intersection_id": "INT_001",
        },
        "approach_mappings": [],
        "detector_mappings": [],
        "movement_mappings": [],
    }


def write_json(tmp_path, content):
    path = tmp_path / "network_mappings.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_load_valid_json(tmp_path, valid_config):
    result = load_network_mappings(write_json(tmp_path, valid_config))
    assert isinstance(result, NetworkMappingConfig)
    assert result.network.version == "test_network_v1"
    assert result.movement_mappings == []


def test_load_from_string_path(tmp_path, valid_config):
    path = write_json(tmp_path, valid_config)
    assert load_network_mappings(str(path)).mapping_version == "1.0"


def test_load_with_movement(tmp_path, valid_config):
    valid_config["approach_mappings"] = [{
        "approach_id": "APP_E",
        "intersection_id": "INT_001",
        "direction": "east",
        "queue_detection_lane_ids": [],
    }]
    valid_config["movement_mappings"] = [{
        "movement_id": "MOV_E_W",
        "intersection_id": "INT_001",
        "approach_id": "APP_E",
        "sumo_route_edge_ids": ["edge_a", "edge_b"],
        "signal_controlled": False,
    }]
    result = load_network_mappings(write_json(tmp_path, valid_config))
    assert result.movement_mappings[0].sumo_route_edge_ids == ["edge_a", "edge_b"]


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_network_mappings(tmp_path / "does_not_exist.json")


def test_malformed_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version": ', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_network_mappings(path)


@pytest.mark.parametrize("missing_field", [
    "schema_version", "mapping_version", "network", "intersection_mapping"
])
def test_missing_required_field(tmp_path, valid_config, missing_field):
    del valid_config[missing_field]
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, valid_config))


def test_invalid_sha256(tmp_path, valid_config):
    valid_config["network"]["sha256"] = "not-a-fingerprint"
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, valid_config))


def test_extra_field_rejected(tmp_path, valid_config):
    valid_config["unsupported_field"] = 123
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, valid_config))


def test_duplicate_movement_rejected(tmp_path, valid_config):
    item = {
        "movement_id": "MOV_E_W",
        "intersection_id": "INT_001",
        "sumo_route_edge_ids": ["a", "b"],
        "signal_controlled": False,
    }
    valid_config["movement_mappings"] = [item, dict(item)]
    with pytest.raises(ValidationError, match="duplicate movement_id"):
        load_network_mappings(write_json(tmp_path, valid_config))


def test_json_array_not_config(tmp_path):
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, []))


def test_empty_json_object(tmp_path):
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, {}))

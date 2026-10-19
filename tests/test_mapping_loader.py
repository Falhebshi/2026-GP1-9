import json
import hashlib

import pytest
from pydantic import ValidationError

from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig


@pytest.fixture
def valid_config():
    return {
        "schema_version": "2.0",
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
    assert result.detector_mappings == []


@pytest.mark.parametrize("site_fields", [
    {}, {"site_id": None}, {"site_id": ""}, {"site_id": "   "},
])
def test_loader_rejects_detector_without_nonblank_site(tmp_path, valid_config, site_fields):
    valid_config["detector_mappings"] = [{
        "source": "synthetic", "detector_id": "D1", "intersection_id": "INT_001",
        "mapping_status": "unresolved", **site_fields,
    }]
    with pytest.raises(ValidationError) as exc:
        load_network_mappings(write_json(tmp_path, valid_config))
    assert exc.value.errors()[0]["loc"] == ("detector_mappings", 0, "site_id")


def test_loader_preserves_detector_with_explicit_site(tmp_path, valid_config):
    valid_config["detector_mappings"] = [{
        "source": "synthetic", "site_id": "9", "detector_id": "D1",
        "intersection_id": "INT_001", "mapping_status": "unresolved",
    }]
    result = load_network_mappings(write_json(tmp_path, valid_config))
    assert result.detector_mappings[0].site_id == "9"


def test_load_from_string_path(tmp_path, valid_config):
    path = write_json(tmp_path, valid_config)
    assert load_network_mappings(str(path)).mapping_version == "1.0"


def test_load_with_movement(tmp_path, valid_config):
    valid_config["approach_mappings"] = [{
        "approach_id": "APP_E",
        "intersection_id": "INT_001",
        "approach_side": "east",
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


def test_loader_exposes_canonical_objects_without_sumo_fields(tmp_path, valid_config):
    config = load_network_mappings(write_json(tmp_path, valid_config))
    assert config.canonical_intersection.intersection_id == 'INT_001'
    assert config.canonical_approaches == {}
    assert config.canonical_movements == {}
    assert config.approach_lanes == config.lane_mappings == []


def test_loader_can_validate_the_actual_sumo_network(tmp_path, valid_config):
    path = tmp_path / 'network.net.xml'
    path.write_bytes(b'<net/>')
    valid_config['network']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    mapping_file = write_json(tmp_path, valid_config)
    assert load_network_mappings(mapping_file, network_path=path).movement_mappings == []
    path.write_bytes(b'<net changed="true"/>')
    with pytest.raises(ValueError, match='SHA-256'):
        load_network_mappings(mapping_file, network_path=path)


def test_loader_rejects_missing_network_when_static_validation_requested(tmp_path, valid_config):
    with pytest.raises(ValueError, match='SUMO network file not found'):
        load_network_mappings(write_json(tmp_path, valid_config), network_path=tmp_path/'missing.xml')


def test_loader_rejects_invalid_canonical_lane_reference(tmp_path, valid_config):
    valid_config['lane_mappings'] = [{'lane_id': 'UNKNOWN', 'sumo_lane_ids': ['a_0']}]
    with pytest.raises(ValidationError, match='unknown lane_id'):
        load_network_mappings(write_json(tmp_path, valid_config))


@pytest.mark.parametrize('position', [0, 4.5, 10])
def test_loader_preserves_and_validates_explicit_detector_location(tmp_path, valid_config, position):
    network = tmp_path / 'network.net.xml'
    network.write_text('<net><edge id="a"><lane id="a_0" index="0" length="10"/></edge></net>')
    valid_config['network']['sha256'] = hashlib.sha256(network.read_bytes()).hexdigest()
    valid_config['detector_mappings'] = [{
        'source': 'synthetic', 'site_id': '9', 'detector_id': 'D1',
        'intersection_id': 'INT_001', 'mapping_status': 'unresolved',
        'sumo_lane_id': ' a_0 ', 'sumo_position_m': position,
    }]
    mapping_file = write_json(tmp_path, valid_config)
    for network_path in [None, network]:
        detector = load_network_mappings(mapping_file, network_path=network_path).detector_mappings[0]
        assert detector.sumo_lane_id == 'a_0'
        assert detector.sumo_position_m == position
        assert detector.movement_ids == []


@pytest.mark.parametrize('location', [
    {'sumo_lane_id': 'a_0'}, {'sumo_position_m': 0},
    {'sumo_lane_id': 'a_0', 'sumo_position_m': True},
])
def test_loader_rejects_structurally_invalid_detector_location(tmp_path, valid_config, location):
    valid_config['detector_mappings'] = [{
        'source': 'synthetic', 'site_id': '9', 'detector_id': 'D1',
        'intersection_id': 'INT_001', 'mapping_status': 'unresolved', **location,
    }]
    with pytest.raises(ValidationError):
        load_network_mappings(write_json(tmp_path, valid_config))


@pytest.mark.parametrize('lane,position,message', [
    ('a_0', 10.01, 'outside lane'), ('missing_0', 1, 'lane not found'),
])
def test_loader_requires_network_for_detector_location_reference_checks(
    tmp_path, valid_config, lane, position, message,
):
    network = tmp_path / 'network.net.xml'
    network.write_text('<net><edge id="a"><lane id="a_0" index="0" length="10"/></edge></net>')
    valid_config['network']['sha256'] = hashlib.sha256(network.read_bytes()).hexdigest()
    valid_config['detector_mappings'] = [{
        'source': 'synthetic', 'site_id': '9', 'detector_id': 'D1',
        'intersection_id': 'INT_001', 'mapping_status': 'unresolved',
        'sumo_lane_id': lane, 'sumo_position_m': position,
    }]
    mapping_file = write_json(tmp_path, valid_config)
    assert load_network_mappings(mapping_file).detector_mappings[0].sumo_lane_id == lane
    with pytest.raises(ValueError, match=message):
        load_network_mappings(mapping_file, network_path=network)

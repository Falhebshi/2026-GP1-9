from pathlib import Path
import hashlib
import json

import pytest

from jaadah.mapping.loader import load_network_mappings
from jaadah.mapping.validator import validate_network_mappings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_DIR = PROJECT_ROOT / "data" / "processed" / "road_network"
MAPPING_FILE = NETWORK_DIR / "network_mappings.json"
NETWORK_FILE = NETWORK_DIR / "jaadah_study_area.net.xml"

APPROVED_MOVEMENTS = {
    "MOV_E_W", "MOV_E_S", "MOV_S_W", "MOV_W_E", "MOV_W_N", "MOV_N_E",
    "MOV_S_E_BYPASS", "MOV_W_S_SLIP", "MOV_N_W_SLIP", "MOV_W_W_UTURN",
    "MOV_E_E_UTURN", "MOV_S_S_UTURN", "MOV_N_N_UTURN",
    "MOV_E_W_ONRAMP", "MOV_W_E_OFFRAMP", "MOV_N_S_TUNNEL",
    "MOV_S_N_TUNNEL", "MOV_TUNNEL_ONRAMP",
}


@pytest.fixture(scope="module")
def config():
    assert MAPPING_FILE.is_file(), f"Missing mapping file: {MAPPING_FILE}"
    return load_network_mappings(MAPPING_FILE, network_path=NETWORK_FILE)


def test_approved_movement_catalog(config):
    mapped_ids = [item.movement_id for item in config.movement_mappings]
    assert len(mapped_ids) == 18
    assert len(set(mapped_ids)) == 18
    assert set(mapped_ids) == APPROVED_MOVEMENTS


def test_complete_route_fields_present(config):
    for movement in config.movement_mappings:
        assert movement.sumo_route_edge_ids, movement.movement_id
        assert all(movement.sumo_route_edge_ids), movement.movement_id


def test_four_approaches_exist(config):
    assert {item.approach_id for item in config.approach_mappings} == {
        "APP_E", "APP_W", "APP_N", "APP_S"
    }


def test_signal_crossings_consistent(config):
    signaled = [m for m in config.movement_mappings if m.signal_controlled]
    assert len(signaled) == 9
    assert all(m.signal_crossings for m in signaled)
    assert all(not m.signal_crossings for m in config.movement_mappings if not m.signal_controlled)
    east_uturn = next(m for m in signaled if m.movement_id == "MOV_E_E_UTURN")
    assert [c.controlled_link_indices for c in east_uturn.signal_crossings] == [
        [0, 1, 2], [9, 10, 11]
    ]


def test_network_version_and_static_references(config):
    assert NETWORK_FILE.is_file(), f"Missing SUMO network file: {NETWORK_FILE}"
    assert config.network.version == "jaadah_network_v2"
    errors = validate_network_mappings(config, NETWORK_FILE)
    assert errors == [], "\n".join(errors)


def test_review_changes_preserve_all_original_movement_records():
    # Frozen semantic digest of the reviewed pre-change 18-record catalog.
    # Includes IDs, parents, edge order, lanes, control flags, TLS, and crossings.
    # Only change this baseline after an independently reviewed routing change.
    data = json.loads(MAPPING_FILE.read_text(encoding='utf-8'))
    encoded = json.dumps(data['movement_mappings'], sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        'e18cda9abdedcf1b352720086684a3e7698ba196735ef6aa72ebb2e7e8e69b08'
    )


def test_authoritative_config_contains_no_unapproved_lane_or_detector_data(config):
    assert config.schema_version == '2.0'
    assert config.approach_lanes == config.lane_mappings == config.detector_mappings == []
    assert all(not item.queue_detection_lane_ids for item in config.approach_mappings)


def test_canonical_views_preserve_declared_ownership(config):
    assert config.canonical_intersection.intersection_id == 'INT_001'
    assert set(config.canonical_approaches) == {'APP_E', 'APP_W', 'APP_N', 'APP_S'}
    assert set(config.canonical_movements) == APPROVED_MOVEMENTS
    assert config.canonical_movements['MOV_E_W'].approach_id == 'APP_E'
    assert config.canonical_movements['MOV_N_S_TUNNEL'].approach_id is None


def test_approach_side_describes_location_not_travel_direction(config):
    assert {item.approach_id: item.approach_side.value for item in config.approach_mappings} == {
        'APP_E': 'east', 'APP_W': 'west', 'APP_N': 'north', 'APP_S': 'south',
    }

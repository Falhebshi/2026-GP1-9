from pathlib import Path
from collections import Counter
from decimal import Decimal
import hashlib
import json
import xml.etree.ElementTree as ET

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


# Approved bounded lane identities, Option A maneuvers, and synthetic
# detector assignments. Placement checks below apply only to this baseline.
APPROVED_LANES = [
    ('LANE_E_1', ['MOV_E_S'], ['713369663#1.469_3', '713369663#2-AddedOnRampEdge_3', '713369663#2_3'], '9'),
    ('LANE_E_2', ['MOV_E_S', 'MOV_E_W'], ['713369663#1.469_2', '713369663#2-AddedOnRampEdge_2', '713369663#2_2'], '10'),
    ('LANE_E_3', ['MOV_E_W'], ['713369663#1.469_1', '713369663#2-AddedOnRampEdge_1', '713369663#2_1'], '11'),
    ('LANE_E_4', ['MOV_E_W'], ['713369663#1.469_0', '713369663#2-AddedOnRampEdge_0', '713369663#2_0'], '12'),
    ('LANE_S_1', ['MOV_S_W'], ['539502456#8_3', '569790079#0_1'], '7'),
    ('LANE_S_2', ['MOV_S_W'], ['539502456#8_2', '569790079#0_0'], '8'),
    ('LANE_S_3', ['MOV_S_E_BYPASS'], ['539502456#8_1', '133973513_1'], '15'),
    ('LANE_S_4', ['MOV_S_E_BYPASS'], ['539502456#8_0', '133973513_0'], '16'),
    ('LANE_W_1', ['MOV_W_N'], ['133793906#0-AddedOffRampEdge.26_3', '133793906#2_2'], '1'),
    ('LANE_W_2', ['MOV_W_N', 'MOV_W_E'], ['133793906#0-AddedOffRampEdge.26_2', '133793906#2_1'], '2'),
    ('LANE_W_3', ['MOV_W_E'], ['133793906#0-AddedOffRampEdge.26_1', '133793906#2_0'], '3'),
    ('LANE_W_4', ['MOV_W_S_SLIP'], ['133793906#0-AddedOffRampEdge.26_0', '133973488#0_0'], '13'),
    ('LANE_N_1', ['MOV_N_E'], ['133973525#1.51_3', '569788806_2'], '4'),
    ('LANE_N_2', ['MOV_N_E'], ['133973525#1.51_2', '569788806_1'], '5'),
    ('LANE_N_3', ['MOV_N_E'], ['133973525#1.51_1', '569788806_0'], '6'),
    ('LANE_N_4', ['MOV_N_W_SLIP'], ['133973525#1.51_0', '1311808806_0'], '14'),
]


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


def test_approved_lane_catalog_and_deferred_collections(config):
    assert config.schema_version == '2.0'
    assert config.mapping_version == '2.2-movement-attributes'
    expected_ids = {item[0] for item in APPROVED_LANES}
    assert len(config.approach_lanes) == len(config.lane_mappings) == 16
    assert {lane.lane_id for lane in config.approach_lanes} == expected_ids
    assert {mapping.lane_id for mapping in config.lane_mappings} == expected_ids
    for approach in config.approach_mappings:
        assert {lane.lane_index for lane in config.approach_lanes
                if lane.approach_id == approach.approach_id} == {1, 2, 3, 4}
    assert config.intersection_mapping.source_sites == []
    assert all(not item.queue_detection_lane_ids for item in config.approach_mappings)


def test_populated_synthetic_detector_catalog(config):
    identities = [(d.source.value, d.site_id, d.detector_id) for d in config.detector_mappings]
    assert len(identities) == len(set(identities)) == 16
    assert set(identities) == {('synthetic', '9', str(i)) for i in range(1, 17)}
    assert Counter(d.mapping_status.value for d in config.detector_mappings) == {
        'usable': 14, 'requires_allocation': 2,
    }
    assert {d.detector_id for d in config.detector_mappings
            if d.mapping_status.value == 'requires_allocation'} == {'2', '10'}


@pytest.fixture(scope='module')
def network_lanes():
    root = ET.parse(NETWORK_FILE).getroot()
    return {lane.get('id'): (edge, lane)
            for edge in root.findall('edge') for lane in edge.findall('lane')}


@pytest.mark.parametrize(
    'lane_id,movement_ids,sumo_lane_ids,detector_id', APPROVED_LANES,
    ids=[item[0] for item in APPROVED_LANES],
)
def test_approved_lane_definition_and_detector_location(
    config, network_lanes, lane_id, movement_ids, sumo_lane_ids, detector_id,
):
    lane = next(item for item in config.approach_lanes if item.lane_id == lane_id)
    mapping = next(item for item in config.lane_mappings if item.lane_id == lane_id)
    _, side, index = lane_id.split('_')
    assert lane.approach_id == f'APP_{side}'
    assert lane.lane_index == int(index)
    assert set(lane.served_movement_ids) == set(movement_ids)
    assert lane.lane_width_m == 3.2  # Approved modeled width, not a survey value.
    assert lane.storage_length_m is None
    assert mapping.sumo_lane_ids == sumo_lane_ids, f'detector {detector_id}'

    detector = next(item for item in config.detector_mappings if item.detector_id == detector_id)
    assert detector.intersection_id == config.intersection_mapping.intersection_id
    assert detector.lane_id == lane_id
    assert detector.approach_id == lane.approach_id
    assert set(detector.movement_ids) == set(movement_ids)
    expected_status = 'requires_allocation' if detector_id in {'2', '10'} else 'usable'
    assert detector.mapping_status.value == expected_status
    assert detector.sumo_lane_id == sumo_lane_ids[-1]
    assert detector.sumo_lane_id in mapping.sumo_lane_ids
    assert detector.sumo_position_m is not None
    edge, sumo_lane = network_lanes[detector.sumo_lane_id]
    assert edge.get('function') != 'internal'
    length = Decimal(sumo_lane.get('length'))
    position = Decimal(str(detector.sumo_position_m))
    assert 0 <= position <= length
    # Approved synthetic placement, not a general DetectorMapping restriction.
    assert position == length - Decimal('1.0')


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


APPROVED_MOVEMENT_ATTRIBUTES = {
    'MOV_E_W': ('through', 'signalized'),
    'MOV_E_S': ('left', 'signalized'),
    # Protected left from APP_S: SUMO labels it dir="s", which is not the HCM classification.
    'MOV_S_W': ('left', 'signalized'),
    'MOV_W_E': ('through', 'signalized'),
    'MOV_W_N': ('left', 'signalized'),
    'MOV_N_E': ('left', 'signalized'),
    'MOV_S_E_BYPASS': ('right', 'uncontrolled'),
    'MOV_W_S_SLIP': ('right', 'uncontrolled'),
    'MOV_N_W_SLIP': ('right', 'uncontrolled'),
}


def test_approved_movement_attributes(config):
    """
    The analysed movements are exactly those served by the approach lanes.
    Ramps, U-turns and tunnel paths are outside the KPI analysis and have none.
    """
    assert {
        item.movement_id: (item.movement_type.value, item.control.value)
        for item in config.movement_attributes
    } == APPROVED_MOVEMENT_ATTRIBUTES
    served = {m for lane in config.approach_lanes for m in lane.served_movement_ids}
    assert served == set(APPROVED_MOVEMENT_ATTRIBUTES)

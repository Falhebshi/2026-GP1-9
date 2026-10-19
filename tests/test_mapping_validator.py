import hashlib

import pytest

from jaadah.mapping.validator import (
    network_checksum_matches,
    require_lane_mapping,
    validate_network_mappings,
)
from jaadah.models.mappings import NetworkMappingConfig


NETWORK = '''<net>
  <edge id="a"><lane id="a_0" index="0"/><lane id="a_1" index="1"/></edge>
  <edge id="b"><lane id="b_0" index="0"/></edge>
  <edge id="c"><lane id="c_0" index="0"/></edge>
  <edge id="d"><lane id="d_0" index="0"/></edge>
  <tlLogic id="signal_1" type="static" programID="0" offset="0"><phase duration="30" state="G"/></tlLogic>
  <connection from="a" to="b" fromLane="0" toLane="0" tl="signal_1" linkIndex="0"/>
  <connection from="b" to="c" fromLane="0" toLane="0"/>
</net>'''


def case(tmp_path, *, route=None, controlled=True, lane='a_0', tls='signal_1', index=0):
    path = tmp_path / 'network.net.xml'
    path.write_text(NETWORK, encoding='utf-8')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {
        'schema_version': '2.0', 'mapping_version': '1',
        'network': {'version': 'test', 'path': str(path), 'sha256': sha},
        'intersection_mapping': {'intersection_id': 'INT_001', 'sumo_tls_id': 'signal_1'},
        'approach_mappings': [{'approach_id': 'APP_A', 'intersection_id': 'INT_001',
                               'approach_side': 'west', 'queue_detection_lane_ids': [lane]}],
        'movement_mappings': [{
            'movement_id': 'MOV_A_C', 'intersection_id': 'INT_001', 'approach_id': 'APP_A',
            'sumo_route_edge_ids': route or ['a','b','c'], 'signal_controlled': controlled,
            **({'sumo_tls_id': tls, 'signal_crossings': [{'crossing_order': 0,
                'sumo_tls_id': tls, 'controlled_link_indices': [index]}]} if controlled else {})
        }]
    }
    return NetworkMappingConfig.model_validate(data), path


def test_valid_network(tmp_path):
    c, path = case(tmp_path)
    assert validate_network_mappings(c, path) == []


def test_network_hash_mismatch(tmp_path):
    c, path = case(tmp_path)
    path.write_text(NETWORK + '\n', encoding='utf-8')
    assert 'SHA-256' in '\n'.join(validate_network_mappings(c, path))


def test_missing_file(tmp_path):
    c, path = case(tmp_path)
    assert 'not found' in '\n'.join(validate_network_mappings(c, path.with_name('missing.net.xml')))


def test_invalid_xml(tmp_path):
    c, path = case(tmp_path)
    path.write_text('<net>', encoding='utf-8')
    assert 'Invalid SUMO network XML' in '\n'.join(validate_network_mappings(c, path))


def test_missing_edge(tmp_path):
    c, path = case(tmp_path, route=['a','unknown'])
    assert 'route edge' in '\n'.join(validate_network_mappings(c, path))


def test_disconnected_edges(tmp_path):
    c, path = case(tmp_path, route=['a','d'])
    assert 'no legal SUMO connection' in '\n'.join(validate_network_mappings(c, path))


def test_missing_queue_lane(tmp_path):
    c, path = case(tmp_path, lane='missing_0')
    assert 'lane not found' in '\n'.join(validate_network_mappings(c, path))


def test_missing_tls(tmp_path):
    c, path = case(tmp_path, tls='other_tls')
    assert 'TLS not found' in '\n'.join(validate_network_mappings(c, path))


def test_missing_link_index(tmp_path):
    c, path = case(tmp_path, index=9)
    assert 'missing link index' in '\n'.join(validate_network_mappings(c, path))


def test_link_not_on_route(tmp_path):
    c, path = case(tmp_path, route=['b','c'])
    assert 'not on the mapped route' in '\n'.join(validate_network_mappings(c, path))


def test_controlled_route_marked_uncontrolled(tmp_path):
    c, path = case(tmp_path, controlled=False)
    assert 'signal_controlled is false' in '\n'.join(validate_network_mappings(c, path))


def test_uncontrolled_route(tmp_path):
    c, path = case(tmp_path, route=['b','c'], controlled=False)
    assert validate_network_mappings(c, path) == []


def with_canonical_lane(config, lane_ids):
    data = config.model_dump()
    data['approach_lanes'] = [{
        'lane_id': 'TEST_LANE', 'approach_id': 'APP_A', 'lane_index': 1,
        'served_movement_ids': ['MOV_A_C'], 'lane_width_m': 3.5,
    }]
    data['lane_mappings'] = [{'lane_id': 'TEST_LANE', 'sumo_lane_ids': lane_ids}]
    return NetworkMappingConfig.model_validate(data)


def test_require_lane_mapping_returns_requested_mapping(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['a_0', 'b_0'])
    mapping = require_lane_mapping(config, 'TEST_LANE')
    assert mapping is config.lane_mappings[0]
    assert mapping.sumo_lane_ids == ['a_0', 'b_0']
    assert validate_network_mappings(config, path) == []


def test_require_lane_mapping_rejects_pending_mapping(tmp_path):
    config, path = case(tmp_path)
    data = with_canonical_lane(config, ['a_0']).model_dump()
    data['lane_mappings'] = []
    config = NetworkMappingConfig.model_validate(data)
    assert validate_network_mappings(config, path) == []
    with pytest.raises(ValueError, match='^Missing SUMO lane mapping for lane TEST_LANE$'):
        require_lane_mapping(config, 'TEST_LANE')


def test_require_lane_mapping_does_not_fall_back_for_unknown_lane(tmp_path):
    config, _ = case(tmp_path)
    config = with_canonical_lane(config, ['a_0'])
    with pytest.raises(ValueError, match='^Missing SUMO lane mapping for lane UNKNOWN$'):
        require_lane_mapping(config, 'UNKNOWN')


def test_required_mapping_still_needs_network_validation(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['missing_0'])
    assert require_lane_mapping(config, 'TEST_LANE').sumo_lane_ids == ['missing_0']
    assert 'lane not found' in '\n'.join(validate_network_mappings(config, path))


def test_connected_lane_segments_support_movement(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['a_0', 'b_0'])
    assert validate_network_mappings(config, path) == []


def test_canonical_lane_mapping_checks_sumo_lane_existence(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['missing_0'])
    assert 'lane not found' in '\n'.join(validate_network_mappings(config, path))


def test_disconnected_lane_segments_are_rejected(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['a_0', 'c_0'])
    assert 'no legal SUMO lane connection' in '\n'.join(validate_network_mappings(config, path))


def test_existing_lane_on_unrelated_edge_is_rejected(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['d_0'])
    assert 'not on movement route' in '\n'.join(validate_network_mappings(config, path))


def test_existing_lane_on_route_cannot_serve_illegal_turn(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['a_1'])
    assert 'cannot serve movement' in '\n'.join(validate_network_mappings(config, path))


def test_canonical_lane_chain_preserves_route_order(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['b_0', 'a_0'])
    errors = '\n'.join(validate_network_mappings(config, path))
    assert 'no legal SUMO lane connection' in errors
    assert 'not on movement route' in errors


def test_internal_lane_is_not_a_canonical_approach_lane(tmp_path):
    config, path = case(tmp_path)
    path.write_text(NETWORK.replace(
        '<edge id="d">', '<edge id="d" function="internal">'
    ), encoding='utf-8')
    config.network.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    config = with_canonical_lane(config, ['d_0'])
    assert 'internal SUMO lane' in '\n'.join(validate_network_mappings(config, path))


def test_lane_mapping_is_checked_against_every_served_movement(tmp_path):
    config, path = case(tmp_path)
    config = with_canonical_lane(config, ['a_0'])
    data = config.model_dump()
    data['movement_mappings'].append({
        'movement_id': 'MOV_D_C', 'intersection_id': 'INT_001', 'approach_id': 'APP_A',
        'sumo_route_edge_ids': ['d', 'c'], 'signal_controlled': False,
    })
    data['approach_lanes'][0]['served_movement_ids'].append('MOV_D_C')
    errors = validate_network_mappings(NetworkMappingConfig.model_validate(data), path)
    assert 'lane segments are not on movement route MOV_D_C' in '\n'.join(errors)


def test_lane_chain_continuation_is_checked_at_correct_occurrence_in_loop(tmp_path):
    config, path = case(tmp_path, route=['a', 'b', 'c', 'a', 'd'])
    path.write_text(NETWORK.replace('</net>', '''
      <connection from="c" to="a" fromLane="0" toLane="0"/>
      <connection from="a" to="d" fromLane="1" toLane="0"/>
    </net>'''), encoding='utf-8')
    config.network.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    config = with_canonical_lane(config, ['c_0', 'a_0'])
    # a_0 can go to b on the first visit, but cannot go to d after c -> a.
    assert 'terminal lane cannot serve' in '\n'.join(validate_network_mappings(config, path))


def test_movement_sumo_lane_must_be_connected_along_route(tmp_path):
    config, path = case(tmp_path)
    config.movement_mappings[0].sumo_lanes = ['d_0', 'a_1']
    errors = '\n'.join(validate_network_mappings(config, path))
    assert 'not connected along the mapped route: d_0' in errors
    assert 'not connected along the mapped route: a_1' in errors


def test_valid_movement_sumo_lane(tmp_path):
    config, path = case(tmp_path)
    config.movement_mappings[0].sumo_lanes = ['a_0']
    assert validate_network_mappings(config, path) == []


@pytest.mark.parametrize('expected_crlf', [False, True])
@pytest.mark.parametrize('checkout_crlf', [False, True])
def test_network_checksum_is_portable_across_line_endings(tmp_path, expected_crlf, checkout_crlf):
    config, path = case(tmp_path)
    lf = NETWORK.replace('\r\n', '\n').encode('utf-8')
    crlf = lf.replace(b'\n', b'\r\n')
    config.network.sha256 = hashlib.sha256(crlf if expected_crlf else lf).hexdigest()
    path.write_bytes(crlf if checkout_crlf else lf)
    assert validate_network_mappings(config, path) == []


def test_checksum_policy_does_not_ignore_other_content_changes():
    original = b'<net>\n<edge id="a"/>\n</net>\n'
    digest = hashlib.sha256(original).hexdigest()
    assert network_checksum_matches(original.replace(b'\n', b'\r\n'), digest)
    assert not network_checksum_matches(original.replace(b'id="a"', b'id="b"'), digest)
    assert not network_checksum_matches(original.replace(b'<edge', b' <edge'), digest)

import hashlib

from jaadah.mapping.validator import validate_network_mappings
from jaadah.models.mappings import NetworkMappingConfig


NETWORK = '''<net>
  <edge id="a"><lane id="a_0" index="0"/></edge>
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
        'schema_version': '1', 'mapping_version': '1',
        'network': {'version': 'test', 'path': str(path), 'sha256': sha},
        'intersection_mapping': {'intersection_id': 'INT_001', 'sumo_tls_id': 'signal_1'},
        'approach_mappings': [{'approach_id': 'APP_A', 'intersection_id': 'INT_001',
                               'direction': 'west', 'queue_detection_lane_ids': [lane]}],
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

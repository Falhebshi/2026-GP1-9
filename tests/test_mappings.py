from copy import deepcopy

import pytest
from pydantic import ValidationError

from jaadah.models.mappings import (
    ApproachMapping,
    DetectorMapping,
    IntersectionMapping,
    MappingStatus,
    MovementMapping,
    NetworkMappingConfig,
    NetworkMetadata,
    SegmentMapping,
    SignalCrossingMapping,
)
from jaadah.models.traffic import TrafficObservationSource


def valid_config():
    return {
        "schema_version": "1.0",
        "mapping_version": "1.0",
        "network": {"version": "v2", "path": "study.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {
            "intersection_id": "INT_001", "source_sites": ["1028"], "sumo_tls_id": "tls"
        },
        "approach_mappings": [
            {"approach_id": "APP_E", "intersection_id": "INT_001", "direction": "east"},
            {"approach_id": "APP_W", "intersection_id": "INT_001", "direction": "west"},
        ],
        "detector_mappings": [],
        "movement_mappings": [
            {"movement_id": "MOV_E_W", "intersection_id": "INT_001",
             "approach_id": "APP_E", "sumo_route_edge_ids": ["entry", "exit"],
             "signal_controlled": False},
        ],
    }


VALID = {
    NetworkMetadata: {"version": "v2", "path": "study.net.xml", "sha256": "a" * 64},
    IntersectionMapping: {"intersection_id": "INT_001"},
    ApproachMapping: {"approach_id": "APP_E", "intersection_id": "INT_001", "direction": "east"},
    DetectorMapping: {"source": "synthetic", "detector_id": "D1", "intersection_id": "INT_001", "mapping_status": "unresolved"},
    SignalCrossingMapping: {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]},
    MovementMapping: {"movement_id": "MOV_E_W", "intersection_id": "INT_001", "sumo_route_edge_ids": ["edge1", "edge2"], "signal_controlled": False},
    SegmentMapping: {"segment_id": "SEG_1"},
    NetworkMappingConfig: valid_config(),
}


def makes(model, **updates):
    data = deepcopy(VALID[model]); data.update(updates)
    return model.model_validate(data)


@pytest.mark.parametrize("model", list(VALID), ids=lambda m: m.__name__)
def test_valid_minimal_models(model):
    assert isinstance(makes(model), model)


@pytest.mark.parametrize("model", list(VALID), ids=lambda m: m.__name__)
def test_forbids_unknown_fields(model):
    with pytest.raises(ValidationError):
        makes(model, invented_field="unexpected")


@pytest.mark.parametrize("model", list(VALID), ids=lambda m: m.__name__)
def test_json_round_trip(model):
    obj = makes(model)
    assert model.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("model", list(VALID), ids=lambda m: m.__name__)
def test_missing_required_field(model):
    required = next(name for name, field in model.model_fields.items() if field.is_required())
    data = deepcopy(VALID[model]); del data[required]
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model,field", [
    (NetworkMetadata, "version"), (NetworkMetadata, "path"),
    (IntersectionMapping, "intersection_id"),
    (ApproachMapping, "approach_id"), (ApproachMapping, "intersection_id"), (ApproachMapping, "direction"),
    (DetectorMapping, "detector_id"), (DetectorMapping, "intersection_id"),
    (SignalCrossingMapping, "sumo_tls_id"),
    (MovementMapping, "movement_id"), (MovementMapping, "intersection_id"),
    (SegmentMapping, "segment_id"),
    (NetworkMappingConfig, "schema_version"), (NetworkMappingConfig, "mapping_version"),
])
@pytest.mark.parametrize("blank", ["", "  ", "\n\t"])
def test_required_strings_reject_blank(model, field, blank):
    with pytest.raises(ValidationError):
        makes(model, **{field: blank})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "sumo_tls_id"),
    (DetectorMapping, "site_id"), (DetectorMapping, "approach_id"),
    (MovementMapping, "approach_id"), (MovementMapping, "sumo_tls_id"),
])
@pytest.mark.parametrize("blank", ["", "   "])
def test_optional_identifiers_reject_blank_if_supplied(model, field, blank):
    with pytest.raises(ValidationError):
        makes(model, **{field: blank})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "source_sites"),
    (ApproachMapping, "source_detectors"), (ApproachMapping, "queue_detection_lane_ids"),
    (DetectorMapping, "movement_ids"),
    (MovementMapping, "sumo_lanes"),
    (SegmentMapping, "sumo_edges"), (SegmentMapping, "osm_ids"), (SegmentMapping, "tomtom_ids"),
])
@pytest.mark.parametrize("items", [["x", "x"], ["x", " x "], ["", "y"], ["  "]])
def test_identifier_lists_reject_invalid_entries(model, field, items):
    with pytest.raises(ValidationError):
        makes(model, **{field: items})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "source_sites"),
    (ApproachMapping, "source_detectors"), (ApproachMapping, "queue_detection_lane_ids"),
    (MovementMapping, "sumo_lanes"),
    (SegmentMapping, "sumo_edges"), (SegmentMapping, "osm_ids"), (SegmentMapping, "tomtom_ids"),
])
def test_optional_lists_default_to_independent_empty_lists(model, field):
    first, second = makes(model), makes(model)
    assert getattr(first, field) == getattr(second, field) == []
    getattr(first, field).append("new")
    assert getattr(second, field) == []


@pytest.mark.parametrize("value", ["not-a-hash", "a" * 63, "g" * 64, "a" * 65, "", None])
def test_network_hash_rejected(value):
    with pytest.raises(ValidationError):
        makes(NetworkMetadata, sha256=value)


@pytest.mark.parametrize("value", ["a" * 64, "A" * 64, "0123456789abcdef" * 4])
def test_network_hash_accepted(value):
    assert makes(NetworkMetadata, sha256=value).sha256 == value


@pytest.mark.parametrize("status,ids", [
    ("usable", ["MOV_E_W"]),
    ("requires_allocation", ["MOV_E_W", "MOV_E_S"]),
    ("unresolved", []),
])
def test_detector_status_valid(status, ids):
    assert makes(DetectorMapping, mapping_status=status, movement_ids=ids).mapping_status == status


@pytest.mark.parametrize("status,ids", [
    ("usable", []), ("usable", ["A", "B"]),
    ("requires_allocation", []), ("requires_allocation", ["A"]),
    ("unresolved", ["A"]), ("unknown", []),
])
def test_detector_status_inconsistent(status, ids):
    with pytest.raises(ValidationError):
        makes(DetectorMapping, mapping_status=status, movement_ids=ids)


def test_detector_enum_reuses_traffic_model():
    assert makes(DetectorMapping).source is TrafficObservationSource.SYNTHETIC
    assert makes(DetectorMapping, source="rcrc").source is TrafficObservationSource.RCRC


@pytest.mark.parametrize("value", ["forecast", "invalid", ""])
def test_detector_rejects_non_observation_source(value):
    with pytest.raises(ValidationError):
        makes(DetectorMapping, source=value)


def test_approach_only_detector_is_valid():
    assert makes(DetectorMapping, approach_id="APP_E").movement_ids == []


def test_detector_multiple_movement_ids_are_only_candidates():
    d = makes(DetectorMapping, movement_ids=["MOV_E_W", "MOV_E_S"], mapping_status="requires_allocation")
    assert d.movement_ids == ["MOV_E_W", "MOV_E_S"]
    assert not hasattr(d, "vehicle_count")


@pytest.mark.parametrize("value", [-1, -2, True, False, "text", 1.5])
def test_signal_crossing_rejects_invalid_order(value):
    with pytest.raises(ValidationError):
        makes(SignalCrossingMapping, crossing_order=value)


@pytest.mark.parametrize("values", [[], [0, 0], [0, -1], [-2], [1, 1, 2], ["bad"]])
def test_signal_indices_reject_invalid(values):
    with pytest.raises(ValidationError):
        makes(SignalCrossingMapping, controlled_link_indices=values)


@pytest.mark.parametrize("values", [[True], [0, False]])
def test_signal_indices_must_reject_boolean_values(values):
    with pytest.raises(ValidationError):
        makes(SignalCrossingMapping, controlled_link_indices=values)


def test_signal_crossing_accepts_multiple_indices():
    assert makes(SignalCrossingMapping, controlled_link_indices=[0, 1, 2]).controlled_link_indices == [0, 1, 2]


@pytest.mark.parametrize("edges", [[], ["one"], ["one", ""], [" ", "two"]])
def test_movement_route_rejects_invalid_edges(edges):
    with pytest.raises(ValidationError):
        makes(MovementMapping, sumo_route_edge_ids=edges)


def test_movement_route_allows_repeated_edges_for_loops():
    assert makes(MovementMapping, sumo_route_edge_ids=["a", "b", "a"]).sumo_route_edge_ids == ["a", "b", "a"]


def test_movement_route_trims_edges():
    assert makes(MovementMapping, sumo_route_edge_ids=[" a ", " b "]).sumo_route_edge_ids == ["a", "b"]


def test_signal_controlled_single_crossing():
    m = makes(MovementMapping, signal_controlled=True, sumo_tls_id="tls",
              signal_crossings=[{"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0, 1]}])
    assert m.signal_crossings[0].controlled_link_indices == [0, 1]


def test_signal_controlled_multiple_crossings():
    m = makes(MovementMapping, signal_controlled=True, sumo_tls_id="tls",
              signal_crossings=[
                  {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0, 1]},
                  {"crossing_order": 1, "sumo_tls_id": "tls", "controlled_link_indices": [9, 10]},
              ])
    assert [c.crossing_order for c in m.signal_crossings] == [0, 1]


@pytest.mark.parametrize("updates", [
    {"signal_controlled": True},
    {"signal_controlled": True, "sumo_tls_id": "tls"},
    {"signal_controlled": False, "sumo_tls_id": "tls"},
    {"signal_controlled": False, "signal_crossings": [{"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]}]},
    {"signal_controlled": True, "sumo_tls_id": "tls", "signal_crossings": [{"crossing_order": 0, "sumo_tls_id": "other", "controlled_link_indices": [0]}]},
    {"signal_controlled": True, "sumo_tls_id": "tls", "signal_crossings": [{"crossing_order": 1, "sumo_tls_id": "tls", "controlled_link_indices": [0]}]},
    {"signal_controlled": True, "sumo_tls_id": "tls", "signal_crossings": [
        {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]},
        {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [1]},
    ]},
])
def test_movement_signal_metadata_rejects_inconsistent_values(updates):
    with pytest.raises(ValidationError):
        makes(MovementMapping, **updates)


def test_config_valid_defaults_and_round_trip():
    obj = NetworkMappingConfig.model_validate(valid_config())
    assert obj.detector_mappings == obj.segment_mappings == []
    assert NetworkMappingConfig.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("collection,duplicate", [
    ("approach_mappings", {"approach_id": "APP_E", "intersection_id": "INT_001", "direction": "east"}),
    ("movement_mappings", {"movement_id": "MOV_E_W", "intersection_id": "INT_001", "sumo_route_edge_ids": ["a", "b"], "signal_controlled": False}),
    ("segment_mappings", {"segment_id": "SEG_1"}),
])
def test_config_rejects_duplicate_entity_keys(collection, duplicate):
    d = valid_config()
    if collection == "segment_mappings":
        d[collection] = [duplicate, deepcopy(duplicate)]
    else:
        d[collection].append(duplicate)
    with pytest.raises(ValidationError, match="duplicate"):
        NetworkMappingConfig.model_validate(d)


@pytest.mark.parametrize("source,site,detector", [
    ("synthetic", None, "D1"), ("rcrc", "1028", "D1")
])
def test_config_rejects_duplicate_detector_key(source, site, detector):
    d = valid_config()
    item = {"source": source, "site_id": site, "detector_id": detector,
            "intersection_id": "INT_001", "mapping_status": "unresolved"}
    d["detector_mappings"] = [item, deepcopy(item)]
    with pytest.raises(ValidationError, match="duplicate detector key"):
        NetworkMappingConfig.model_validate(d)


def test_detector_keys_allow_same_id_for_different_sources_or_sites():
    d = valid_config()
    d["detector_mappings"] = [
        {"source": "rcrc", "site_id": "A", "detector_id": "D", "intersection_id": "INT_001", "mapping_status": "unresolved"},
        {"source": "rcrc", "site_id": "B", "detector_id": "D", "intersection_id": "INT_001", "mapping_status": "unresolved"},
        {"source": "synthetic", "site_id": "A", "detector_id": "D", "intersection_id": "INT_001", "mapping_status": "unresolved"},
    ]
    assert len(NetworkMappingConfig.model_validate(d).detector_mappings) == 3


@pytest.mark.parametrize("collection", ["approach_mappings", "movement_mappings", "detector_mappings"])
def test_config_rejects_wrong_intersection(collection):
    d = valid_config()
    if collection == "detector_mappings":
        d[collection] = [{"source": "synthetic", "detector_id": "D", "intersection_id": "OTHER", "mapping_status": "unresolved"}]
    else:
        d[collection][0]["intersection_id"] = "OTHER"
    with pytest.raises(ValidationError, match="different intersection"):
        NetworkMappingConfig.model_validate(d)


@pytest.mark.parametrize("collection", ["movement_mappings", "detector_mappings"])
def test_config_rejects_unknown_approach(collection):
    d = valid_config()
    if collection == "detector_mappings":
        d[collection] = [{"source": "synthetic", "detector_id": "D", "intersection_id": "INT_001",
                          "approach_id": "APP_UNKNOWN", "mapping_status": "unresolved"}]
    else:
        d[collection][0]["approach_id"] = "APP_UNKNOWN"
    with pytest.raises(ValidationError, match="unknown approach_id"):
        NetworkMappingConfig.model_validate(d)


def test_config_rejects_missing_detector_target_movement():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "detector_id": "D", "intersection_id": "INT_001",
                               "movement_ids": ["MOV_UNKNOWN"], "mapping_status": "usable"}]
    with pytest.raises(ValidationError, match="unmapped movement"):
        NetworkMappingConfig.model_validate(d)


def test_config_rejects_detector_movement_approach_mismatch():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "detector_id": "D", "intersection_id": "INT_001",
                               "approach_id": "APP_W", "movement_ids": ["MOV_E_W"], "mapping_status": "usable"}]
    with pytest.raises(ValidationError, match="approach mismatch"):
        NetworkMappingConfig.model_validate(d)


def test_config_allows_resolved_detector_to_movement_without_approach():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "detector_id": "D", "intersection_id": "INT_001",
                               "movement_ids": ["MOV_E_W"], "mapping_status": "usable"}]
    assert len(NetworkMappingConfig.model_validate(d).detector_mappings) == 1


def test_config_does_not_require_detector_for_each_movement():
    d = valid_config()
    d["movement_mappings"].append({"movement_id": "MOV_TUNNEL", "intersection_id": "INT_001",
                                   "sumo_route_edge_ids": ["t1", "t2"], "signal_controlled": False})
    assert len(NetworkMappingConfig.model_validate(d).movement_mappings) == 2


def test_config_does_not_mutate_input_data():
    d = valid_config(); before = deepcopy(d)
    NetworkMappingConfig.model_validate(d)
    assert d == before


def test_mapping_status_serializes_as_string():
    assert makes(DetectorMapping, mapping_status=MappingStatus.UNRESOLVED).model_dump(mode="json")["mapping_status"] == "unresolved"

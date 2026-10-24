from copy import deepcopy

import pytest
from pydantic import ValidationError

from jaadah.models.mappings import (
    ApproachMapping,
    DetectorMapping,
    IntersectionMapping,
    LaneMapping,
    MappingStatus,
    MovementMapping,
    NetworkMappingConfig,
    NetworkMetadata,
    SignalCrossingMapping,
)
from jaadah.models.traffic import TrafficObservationSource


def valid_config():
    return {
        "schema_version": "2.0",
        "mapping_version": "1.0",
        "network": {"version": "v2", "path": "study.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {
            "intersection_id": "INT_001", "source_sites": ["1028"], "sumo_tls_id": "tls"
        },
        "approach_mappings": [
            {"approach_id": "APP_E", "intersection_id": "INT_001", "approach_side": "east"},
            {"approach_id": "APP_W", "intersection_id": "INT_001", "approach_side": "west"},
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
    LaneMapping: {"lane_id": "TEST_LANE", "sumo_lane_ids": ["entry_0"]},
    ApproachMapping: {"approach_id": "APP_E", "intersection_id": "INT_001", "approach_side": "east"},
    DetectorMapping: {"source": "synthetic", "site_id": "9", "detector_id": "D1", "intersection_id": "INT_001", "mapping_status": "unresolved"},
    SignalCrossingMapping: {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]},
    MovementMapping: {"movement_id": "MOV_E_W", "intersection_id": "INT_001", "sumo_route_edge_ids": ["edge1", "edge2"], "signal_controlled": False},
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
    (ApproachMapping, "approach_id"), (ApproachMapping, "intersection_id"), (ApproachMapping, "approach_side"),
    (DetectorMapping, "site_id"), (DetectorMapping, "detector_id"), (DetectorMapping, "intersection_id"),
    (SignalCrossingMapping, "sumo_tls_id"),
    (MovementMapping, "movement_id"), (MovementMapping, "intersection_id"),
    (NetworkMappingConfig, "schema_version"), (NetworkMappingConfig, "mapping_version"),
])
@pytest.mark.parametrize("blank", ["", "  ", "\n\t"])
def test_required_strings_reject_blank(model, field, blank):
    with pytest.raises(ValidationError):
        makes(model, **{field: blank})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "sumo_tls_id"),
    (DetectorMapping, "approach_id"),
    (DetectorMapping, "lane_id"),
    (MovementMapping, "approach_id"), (MovementMapping, "sumo_tls_id"),
])
@pytest.mark.parametrize("blank", ["", "   "])
def test_optional_identifiers_reject_blank_if_supplied(model, field, blank):
    with pytest.raises(ValidationError):
        makes(model, **{field: blank})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "source_sites"),
    (ApproachMapping, "queue_detection_lane_ids"),
    (DetectorMapping, "movement_ids"),
    (MovementMapping, "sumo_lanes"),
])
@pytest.mark.parametrize("items", [["x", "x"], ["x", " x "], ["", "y"], ["  "]])
def test_identifier_lists_reject_invalid_entries(model, field, items):
    with pytest.raises(ValidationError):
        makes(model, **{field: items})


@pytest.mark.parametrize("model,field", [
    (IntersectionMapping, "source_sites"),
    (ApproachMapping, "queue_detection_lane_ids"),
    (MovementMapping, "sumo_lanes"),
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


@pytest.mark.parametrize("fields", [{}, {"sumo_lane_id": None, "sumo_position_m": None}])
def test_detector_location_can_be_unknown(fields):
    detector = makes(DetectorMapping, **fields)
    assert detector.sumo_lane_id is None
    assert detector.sumo_position_m is None


@pytest.mark.parametrize("position", [0, 1, 1.27, 110.71])
def test_detector_location_accepts_finite_positions_and_normalizes_lane(position):
    detector = makes(DetectorMapping, sumo_lane_id=" entry_0 \n", sumo_position_m=position)
    assert detector.sumo_lane_id == "entry_0"
    assert detector.sumo_position_m == position
    assert detector.mapping_status == MappingStatus.UNRESOLVED
    assert DetectorMapping.model_validate_json(detector.model_dump_json()) == detector


@pytest.mark.parametrize("fields", [
    {"sumo_lane_id": "entry_0"},
    {"sumo_position_m": 0},
    {"sumo_lane_id": "entry_0", "sumo_position_m": None},
    {"sumo_lane_id": None, "sumo_position_m": 0},
])
def test_detector_location_requires_both_fields(fields):
    with pytest.raises(ValidationError, match="must be supplied together"):
        makes(DetectorMapping, **fields)


@pytest.mark.parametrize("lane", ["", " \n\t", 9, False])
def test_detector_location_rejects_invalid_lane_ids(lane):
    with pytest.raises(ValidationError):
        makes(DetectorMapping, sumo_lane_id=lane, sumo_position_m=1)


@pytest.mark.parametrize("position", [
    -1, -0.01, float("nan"), float("inf"), float("-inf"), True, False,
    "not-a-number", "NaN", "Infinity",
])
def test_detector_location_rejects_invalid_positions(position):
    with pytest.raises(ValidationError):
        makes(DetectorMapping, sumo_lane_id="entry_0", sumo_position_m=position)


def test_detector_site_id_is_required():
    data = deepcopy(VALID[DetectorMapping])
    del data["site_id"]
    with pytest.raises(ValidationError) as exc:
        DetectorMapping.model_validate(data)
    assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
        (("site_id",), "missing"),
    ]


@pytest.mark.parametrize("value", [None, 9, False])
def test_detector_site_id_requires_a_string(value):
    with pytest.raises(ValidationError) as exc:
        makes(DetectorMapping, site_id=value)
    assert exc.value.errors()[0]["loc"] == ("site_id",)
    assert exc.value.errors()[0]["type"] == "string_type"


@pytest.mark.parametrize("value,expected", [
    ("9", "9"), ("1028", "1028"), ("SITE_A", "SITE_A"), (" 9 \n", "9"),
])
def test_detector_site_id_preserves_valid_ids_and_trims_whitespace(value, expected):
    assert makes(DetectorMapping, site_id=value).site_id == expected


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
    assert obj.detector_mappings == []
    assert NetworkMappingConfig.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize("collection,duplicate", [
    ("approach_mappings", {"approach_id": "APP_E", "intersection_id": "INT_001", "approach_side": "east"}),
    ("movement_mappings", {"movement_id": "MOV_E_W", "intersection_id": "INT_001", "sumo_route_edge_ids": ["a", "b"], "signal_controlled": False}),
])
def test_config_rejects_duplicate_entity_keys(collection, duplicate):
    d = valid_config()
    d[collection].append(duplicate)
    with pytest.raises(ValidationError, match="duplicate"):
        NetworkMappingConfig.model_validate(d)


@pytest.mark.parametrize("source,site,detector", [
    ("synthetic", "9", "D1"), ("rcrc", "1028", "D1")
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


def test_detector_keys_use_normalized_site_ids():
    d = valid_config()
    first = deepcopy(VALID[DetectorMapping])
    second = dict(first, site_id=" 9 ")
    d["detector_mappings"] = [first, second]
    with pytest.raises(ValidationError, match="duplicate detector key"):
        NetworkMappingConfig.model_validate(d)


@pytest.mark.parametrize("collection", ["approach_mappings", "movement_mappings", "detector_mappings"])
def test_config_rejects_wrong_intersection(collection):
    d = valid_config()
    if collection == "detector_mappings":
        d[collection] = [{"source": "synthetic", "site_id": "9", "detector_id": "D", "intersection_id": "OTHER", "mapping_status": "unresolved"}]
    else:
        d[collection][0]["intersection_id"] = "OTHER"
    with pytest.raises(ValidationError, match="different intersection"):
        NetworkMappingConfig.model_validate(d)


@pytest.mark.parametrize("collection", ["movement_mappings", "detector_mappings"])
def test_config_rejects_unknown_approach(collection):
    d = valid_config()
    if collection == "detector_mappings":
        d[collection] = [{"source": "synthetic", "site_id": "9", "detector_id": "D", "intersection_id": "INT_001",
                          "approach_id": "APP_UNKNOWN", "mapping_status": "unresolved"}]
    else:
        d[collection][0]["approach_id"] = "APP_UNKNOWN"
    with pytest.raises(ValidationError, match="unknown approach_id"):
        NetworkMappingConfig.model_validate(d)


def test_config_rejects_missing_detector_target_movement():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "site_id": "9", "detector_id": "D", "intersection_id": "INT_001",
                               "movement_ids": ["MOV_UNKNOWN"], "mapping_status": "usable"}]
    with pytest.raises(ValidationError, match="unmapped movement"):
        NetworkMappingConfig.model_validate(d)


def test_config_rejects_detector_movement_approach_mismatch():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "site_id": "9", "detector_id": "D", "intersection_id": "INT_001",
                               "approach_id": "APP_W", "movement_ids": ["MOV_E_W"], "mapping_status": "usable"}]
    with pytest.raises(ValidationError, match="approach mismatch"):
        NetworkMappingConfig.model_validate(d)


def test_config_allows_resolved_detector_to_movement_without_approach():
    d = valid_config()
    d["detector_mappings"] = [{"source": "synthetic", "site_id": "9", "detector_id": "D", "intersection_id": "INT_001",
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


@pytest.mark.parametrize("side", ["east", "west", "north", "south"])
def test_valid_approach_sides(side):
    assert makes(ApproachMapping, approach_side=side).approach_side == side


@pytest.mark.parametrize("side", ["EB", "WB", "NB", "SB", "East", "eastbound", " northeast ", ""])
def test_travel_directions_and_invalid_sides_are_rejected(side):
    with pytest.raises(ValidationError):
        makes(ApproachMapping, approach_side=side)


@pytest.mark.parametrize("field,value", [("source_detectors", []), ("direction", "east")])
def test_removed_approach_fields_are_rejected(field, value):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        makes(ApproachMapping, **{field: value})


@pytest.mark.parametrize("version", ["1.0", "1.1", "3.0", "unknown"])
def test_unsupported_mapping_schema_versions_are_rejected(version):
    with pytest.raises(ValidationError, match="schema_version"):
        makes(NetworkMappingConfig, schema_version=version)


@pytest.mark.parametrize("values", [[], [""], [" "], ["a_0", "a_0"], ["a_0", " a_0 "]])
def test_invalid_lane_mapping_segments(values):
    with pytest.raises(ValidationError):
        makes(LaneMapping, sumo_lane_ids=values)


def test_lane_mapping_cleans_identifiers_and_preserves_path_order():
    mapping = makes(LaneMapping, lane_id=" TEST_LANE ", sumo_lane_ids=[" b_0 ", "a_0"])
    assert mapping.lane_id == "TEST_LANE"
    assert mapping.sumo_lane_ids == ["b_0", "a_0"]


def lane_config(shared=False):
    """Artificial unit-test data, not approved study-area lane definitions."""
    data = valid_config()
    movement_ids = ["MOV_E_W"]
    if shared:
        data["movement_mappings"].append({
            "movement_id": "MOV_E_S", "intersection_id": "INT_001", "approach_id": "APP_E",
            "sumo_route_edge_ids": ["entry", "south_exit"], "signal_controlled": False,
        })
        movement_ids.append("MOV_E_S")
    data["approach_lanes"] = [{
        "lane_id": "TEST_LANE", "approach_id": "APP_E", "lane_index": 1,
        "served_movement_ids": movement_ids, "lane_width_m": 3.5,
    }]
    data["lane_mappings"] = [{"lane_id": "TEST_LANE", "sumo_lane_ids": ["entry_0"]}]
    data["detector_mappings"] = [{
        "source": "synthetic", "site_id": "TEST_SITE", "detector_id": "TEST_DETECTOR",
        "intersection_id": "INT_001", "approach_id": "APP_E", "lane_id": "TEST_LANE",
        "movement_ids": list(movement_ids),
        "mapping_status": "requires_allocation" if shared else "usable",
    }]
    return data


@pytest.mark.parametrize("shared", [False, True])
def test_lane_linked_detector_preserves_m7_candidate_and_status_interface(shared):
    obj = NetworkMappingConfig.model_validate(lane_config(shared))
    detector = obj.detector_mappings[0]
    assert set(detector.movement_ids) == set(obj.approach_lanes[0].served_movement_ids)
    assert detector.mapping_status == ("requires_allocation" if shared else "usable")
    assert NetworkMappingConfig.model_validate_json(obj.model_dump_json()) == obj


def test_canonical_entities_are_views_without_duplicate_serialized_declarations():
    from jaadah.models.network import Approach, Intersection, Movement

    obj = NetworkMappingConfig.model_validate(lane_config())
    assert isinstance(obj.canonical_intersection, Intersection)
    assert isinstance(obj.canonical_approaches["APP_E"], Approach)
    assert isinstance(obj.canonical_movements["MOV_E_W"], Movement)
    assert obj.canonical_movements["MOV_E_W"].approach_id == "APP_E"
    assert not hasattr(obj.canonical_movements["MOV_E_W"], "sumo_route_edge_ids")
    assert not any(key.startswith("canonical_") for key in obj.model_dump())
    # Mutating a returned snapshot must not change the authoritative declarations.
    obj.canonical_movements["MOV_E_W"].approach_id = "APP_W"
    assert obj.canonical_movements["MOV_E_W"].approach_id == "APP_E"


@pytest.mark.parametrize("collection", ["approach_lanes", "lane_mappings"])
def test_duplicate_lane_ids_are_rejected(collection):
    data = lane_config()
    data[collection].append(deepcopy(data[collection][0]))
    with pytest.raises(ValidationError, match="duplicate"):
        NetworkMappingConfig.model_validate(data)


def test_duplicate_lane_index_within_approach_is_rejected():
    data = lane_config()
    lane = deepcopy(data["approach_lanes"][0])
    lane["lane_id"] = "ANOTHER_TEST_LANE"
    data["approach_lanes"].append(lane)
    with pytest.raises(ValidationError, match="duplicate approach lane index"):
        NetworkMappingConfig.model_validate(data)


@pytest.mark.parametrize("collection,field,value,match", [
    ("approach_lanes", "approach_id", "UNKNOWN", "unknown approach_id"),
    ("approach_lanes", "served_movement_ids", ["UNKNOWN"], "unmapped movement"),
    ("approach_lanes", "approach_id", "APP_W", "lane/movement approach mismatch"),
    ("lane_mappings", "lane_id", "UNKNOWN", "unknown lane_id"),
    ("detector_mappings", "lane_id", "UNKNOWN", "unknown lane_id"),
    ("detector_mappings", "approach_id", "APP_W", "detector/lane approach mismatch"),
])
def test_invalid_lane_references_and_ownership(collection, field, value, match):
    data = lane_config()
    data[collection][0][field] = value
    with pytest.raises(ValidationError, match=match):
        NetworkMappingConfig.model_validate(data)


@pytest.mark.parametrize("status", ["usable", "requires_allocation", "unresolved"])
def test_lane_linked_detector_allows_pending_sumo_mapping(status):
    data = lane_config(shared=status == "requires_allocation")
    data["lane_mappings"] = []
    if status == "unresolved":
        data["detector_mappings"][0].update(mapping_status=status, movement_ids=[])
    config = NetworkMappingConfig.model_validate(data)
    assert config.detector_mappings[0].lane_id == config.approach_lanes[0].lane_id
    assert config.detector_mappings[0].mapping_status == status
    assert config.lane_mappings == []


@pytest.mark.parametrize("field,value,match", [
    ("lane_id", "UNKNOWN", "unknown lane_id"),
    ("approach_id", "APP_W", "detector/lane approach mismatch"),
    ("movement_ids", ["UNKNOWN"], "must match the lane's served movements"),
])
def test_pending_sumo_mapping_keeps_detector_lane_checks(field, value, match):
    data = lane_config()
    data["lane_mappings"] = []
    data["detector_mappings"][0][field] = value
    with pytest.raises(ValidationError, match=match):
        NetworkMappingConfig.model_validate(data)


def test_shared_lane_cannot_claim_a_single_usable_candidate():
    data = lane_config(shared=True)
    data["detector_mappings"][0].update(mapping_status="usable", movement_ids=["MOV_E_W"])
    with pytest.raises(ValidationError, match="must match the lane's served movements"):
        NetworkMappingConfig.model_validate(data)


def test_shared_lane_candidates_are_compared_as_a_set():
    data = lane_config(shared=True)
    data["detector_mappings"][0]["movement_ids"].reverse()
    NetworkMappingConfig.model_validate(data)


def test_detector_approach_can_be_resolved_from_lane():
    data = lane_config()
    del data["detector_mappings"][0]["approach_id"]
    assert NetworkMappingConfig.model_validate(data).detector_mappings[0].approach_id is None


def test_unresolved_detector_can_reference_known_lane_without_asserting_candidates():
    data = lane_config(shared=True)
    data["detector_mappings"][0].update(mapping_status="unresolved", movement_ids=[])
    NetworkMappingConfig.model_validate(data)


def test_approach_owned_lane_cannot_serve_approachless_movement():
    data = lane_config()
    data["movement_mappings"][0]["approach_id"] = None
    with pytest.raises(ValidationError, match="lane/movement approach mismatch"):
        NetworkMappingConfig.model_validate(data)


def test_approach_detector_cannot_assert_approachless_movement():
    data = lane_config()
    data["approach_lanes"] = []
    data["lane_mappings"] = []
    data["detector_mappings"][0].pop("lane_id")
    data["movement_mappings"][0]["approach_id"] = None
    with pytest.raises(ValidationError, match="detector/movement approach mismatch"):
        NetworkMappingConfig.model_validate(data)


# ============================================================
# MOVEMENT ATTRIBUTES
# ============================================================


def attributes_config():
    """Artificial unit-test data: one signalized and one uncontrolled movement on separate lanes."""
    data = lane_config()
    data["movement_mappings"][0].update(
        signal_controlled=True, sumo_tls_id="tls",
        signal_crossings=[{"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]}],
    )
    data["movement_mappings"].append({
        "movement_id": "MOV_E_S", "intersection_id": "INT_001", "approach_id": "APP_E",
        "sumo_route_edge_ids": ["entry", "south_exit"], "signal_controlled": False,
    })
    data["approach_lanes"].append({
        "lane_id": "TEST_SLIP", "approach_id": "APP_E", "lane_index": 2,
        "served_movement_ids": ["MOV_E_S"], "lane_width_m": 3.5,
    })
    data["lane_mappings"].append({"lane_id": "TEST_SLIP", "sumo_lane_ids": ["entry_1"]})
    data["movement_attributes"] = [
        {"movement_id": "MOV_E_W", "movement_type": "through", "control": "signalized"},
        {"movement_id": "MOV_E_S", "movement_type": "right", "control": "uncontrolled"},
    ]
    return data


def test_movement_attributes_are_accepted():
    obj = NetworkMappingConfig.model_validate(attributes_config())
    assert [(a.movement_id, a.movement_type.value, a.control.value) for a in obj.movement_attributes] == [
        ("MOV_E_W", "through", "signalized"), ("MOV_E_S", "right", "uncontrolled"),
    ]
    assert NetworkMappingConfig.model_validate_json(obj.model_dump_json()) == obj


def test_movement_attributes_default_to_independent_empty_lists():
    """A file written before movement attributes existed still loads."""
    first = NetworkMappingConfig.model_validate(valid_config())
    second = NetworkMappingConfig.model_validate(valid_config())
    assert first.movement_attributes == []
    first.movement_attributes.append("sentinel")
    assert second.movement_attributes == []


def test_draft_with_some_movement_attributes_is_allowed():
    """Completeness is checked by the integration tests, not by the model."""
    data = attributes_config()
    data["movement_attributes"] = data["movement_attributes"][:1]
    assert len(NetworkMappingConfig.model_validate(data).movement_attributes) == 1


def test_movement_attributes_for_unmapped_movement_rejected():
    data = attributes_config()
    data["movement_attributes"][0]["movement_id"] = "MOV_X"
    with pytest.raises(ValidationError, match="unmapped movement: MOV_X"):
        NetworkMappingConfig.model_validate(data)


def test_duplicate_movement_attributes_rejected():
    data = attributes_config()
    data["movement_attributes"].append(dict(data["movement_attributes"][0]))
    with pytest.raises(ValidationError, match="duplicate movement attributes"):
        NetworkMappingConfig.model_validate(data)


def test_movement_attributes_require_an_approach():
    data = valid_config()
    data["movement_mappings"][0]["approach_id"] = None
    data["movement_attributes"] = [
        {"movement_id": "MOV_E_W", "movement_type": "through", "control": "uncontrolled"},
    ]
    with pytest.raises(ValidationError, match="has no approach_id: MOV_E_W"):
        NetworkMappingConfig.model_validate(data)


@pytest.mark.parametrize("index, control", [(0, "uncontrolled"), (1, "signalized")])
def test_control_must_agree_with_signal_controlled(index, control):
    data = attributes_config()
    data["movement_attributes"][index]["control"] = control
    with pytest.raises(ValidationError, match="disagrees with signal_controlled"):
        NetworkMappingConfig.model_validate(data)


def test_lane_cannot_serve_signalized_and_uncontrolled_movements():
    data = attributes_config()
    data["approach_lanes"][0]["served_movement_ids"] = ["MOV_E_W", "MOV_E_S"]
    data["detector_mappings"] = []
    with pytest.raises(ValidationError, match="serves both signalized and uncontrolled"):
        NetworkMappingConfig.model_validate(data)


def test_lane_mixing_is_not_checked_without_attributes():
    """A draft lane with a movement that has no attributes yet is allowed."""
    data = attributes_config()
    data["approach_lanes"][0]["served_movement_ids"] = ["MOV_E_W", "MOV_E_S"]
    data["detector_mappings"] = []
    data["movement_attributes"] = data["movement_attributes"][:1]
    NetworkMappingConfig.model_validate(data)

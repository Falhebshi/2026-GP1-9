from datetime import datetime

import pytest

from backend.demand.mapper import (
    find_detector_mapping,
    map_observation_to_movement,
)
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import TrafficObservation


def make_valid_config() -> NetworkMappingConfig:
    """
    Return a small mapping for mapper tests: one usable detector,
    one shared lane and one unresolved detector.
    """

    return NetworkMappingConfig.model_validate(
        {
            "schema_version": "1.0",
            "mapping_version": "test",
            "network": {
                "version": "test",
                "path": "test.net.xml",
                "sha256": "a" * 64,
            },
            "intersection_mapping": {
                "intersection_id": "INT_001",
                "source_sites": ["9"],
            },
            "approach_mappings": [
                {
                    "approach_id": "APP_N",
                    "intersection_id": "INT_001",
                    "direction": "north",
                },
                {
                    "approach_id": "APP_W",
                    "intersection_id": "INT_001",
                    "direction": "west",
                },
            ],
            "movement_mappings": [
                {
                    "movement_id": "MOV_N_E",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_N",
                    "sumo_route_edge_ids": [
                        "north_in",
                        "east_out",
                    ],
                    "signal_controlled": False,
                },
                {
                    "movement_id": "MOV_W_N",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_W",
                    "sumo_route_edge_ids": [
                        "west_in",
                        "north_out",
                    ],
                    "signal_controlled": False,
                },
                {
                    "movement_id": "MOV_W_E",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_W",
                    "sumo_route_edge_ids": [
                        "west_in",
                        "east_out",
                    ],
                    "signal_controlled": False,
                },
            ],
            "detector_mappings": [
                {
                    "source": "synthetic",
                    "site_id": "9",
                    "detector_id": "4",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_N",
                    "movement_ids": ["MOV_N_E"],
                    "mapping_status": "usable",
                },
                {
                    "source": "synthetic",
                    "site_id": "9",
                    "detector_id": "2",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_W",
                    "movement_ids": [
                        "MOV_W_N",
                        "MOV_W_E",
                    ],
                    "mapping_status": "requires_allocation",
                },
                {
                    "source": "synthetic",
                    "site_id": "9",
                    "detector_id": "3",
                    "intersection_id": "INT_001",
                    "approach_id": "APP_W",
                    "movement_ids": [],
                    "mapping_status": "unresolved",
                },
            ],
        }
    )


def make_observation(
    detector_id: str = "4",
    site_id: str = "9",
    source: str = "synthetic",
) -> TrafficObservation:
    """Return one valid 15-minute observation for mapper tests."""

    return TrafficObservation(
        observation_id=f"OBS_SYN_{site_id}_{detector_id}_20261014T0815",
        source=source,
        site_id=site_id,
        detector_id=detector_id,
        interval_start=datetime.fromisoformat(
            "2026-10-14T08:00:00+03:00"
        ),
        interval_end=datetime.fromisoformat(
            "2026-10-14T08:15:00+03:00"
        ),
        vehicle_count=20,
    )


def test_usable_detector_returns_its_movement() -> None:
    observation = make_observation(detector_id="4")

    movement_id = map_observation_to_movement(
        observation,
        make_valid_config(),
    )

    assert movement_id == "MOV_N_E"


def test_matching_detector_mapping_is_found() -> None:
    observation = make_observation(detector_id="2")

    mapping = find_detector_mapping(
        observation,
        make_valid_config(),
    )

    assert mapping is not None
    assert mapping.detector_id == "2"


def test_unknown_detector_has_no_mapping() -> None:
    observation = make_observation(detector_id="99")

    mapping = find_detector_mapping(
        observation,
        make_valid_config(),
    )

    assert mapping is None


def test_unknown_detector_is_rejected() -> None:
    observation = make_observation(detector_id="99")

    with pytest.raises(
        ValueError,
        match="detector has no mapping",
    ):
        map_observation_to_movement(
            observation,
            make_valid_config(),
        )


def test_same_detector_at_another_site_is_rejected() -> None:
    observation = make_observation(
        detector_id="4",
        site_id="1028",
    )

    with pytest.raises(
        ValueError,
        match="detector has no mapping",
    ):
        map_observation_to_movement(
            observation,
            make_valid_config(),
        )


def test_same_detector_from_another_source_is_rejected() -> None:
    observation = make_observation(
        detector_id="4",
        source="rcrc",
    )

    with pytest.raises(
        ValueError,
        match="detector has no mapping",
    ):
        map_observation_to_movement(
            observation,
            make_valid_config(),
        )


def test_unresolved_detector_is_rejected() -> None:
    observation = make_observation(detector_id="3")

    with pytest.raises(
        ValueError,
        match="detector mapping is unresolved",
    ):
        map_observation_to_movement(
            observation,
            make_valid_config(),
        )


def test_shared_lane_detector_is_rejected_with_its_movements() -> None:
    observation = make_observation(detector_id="2")

    with pytest.raises(
        ValueError,
        match="detector serves MOV_W_N, MOV_W_E",
    ):
        map_observation_to_movement(
            observation,
            make_valid_config(),
        )

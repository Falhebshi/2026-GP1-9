from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.demand.service import (
    build_demand_id,
    transform_observations,
)
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import (
    TrafficObservation,
    TrafficObservationSource,
)


FIRST_START = datetime.fromisoformat("2026-10-14T08:00:00+03:00")


def make_detector_mapping(
    detector_id: str,
    approach_id: str,
    movement_ids: list[str],
    mapping_status: str,
) -> dict:
    """Return one synthetic detector mapping at site 9."""

    return {
        "source": "synthetic",
        "site_id": "9",
        "detector_id": detector_id,
        "intersection_id": "INT_001",
        "approach_id": approach_id,
        "movement_ids": movement_ids,
        "mapping_status": mapping_status,
    }


def make_movement_mapping(
    movement_id: str,
    approach_id: str,
) -> dict:
    """Return one movement mapping with placeholder route edges."""

    return {
        "movement_id": movement_id,
        "intersection_id": "INT_001",
        "approach_id": approach_id,
        "sumo_route_edge_ids": [
            f"{movement_id.lower()}_in",
            f"{movement_id.lower()}_out",
        ],
        "signal_controlled": False,
    }


def make_valid_config(
    detector_mappings: list[dict] | None = None,
) -> NetworkMappingConfig:
    """
    Return a small mapping for service tests. By default the north left
    turn MOV_N_E is counted by detectors 4, 5 and 6, detector 2 is a
    shared lane and detector 3 is unresolved.
    """

    if detector_mappings is None:
        detector_mappings = [
            make_detector_mapping(
                detector_id="4",
                approach_id="APP_N",
                movement_ids=["MOV_N_E"],
                mapping_status="usable",
            ),
            make_detector_mapping(
                detector_id="5",
                approach_id="APP_N",
                movement_ids=["MOV_N_E"],
                mapping_status="usable",
            ),
            make_detector_mapping(
                detector_id="6",
                approach_id="APP_N",
                movement_ids=["MOV_N_E"],
                mapping_status="usable",
            ),
            make_detector_mapping(
                detector_id="2",
                approach_id="APP_W",
                movement_ids=["MOV_W_N", "MOV_W_E"],
                mapping_status="requires_allocation",
            ),
            make_detector_mapping(
                detector_id="3",
                approach_id="APP_W",
                movement_ids=[],
                mapping_status="unresolved",
            ),
        ]

    return NetworkMappingConfig.model_validate(
        {
            "schema_version": "2.0",
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
                    "approach_side": "north",
                },
                {
                    "approach_id": "APP_W",
                    "intersection_id": "INT_001",
                    "approach_side": "west",
                },
            ],
            "movement_mappings": [
                make_movement_mapping("MOV_N_E", "APP_N"),
                make_movement_mapping("MOV_W_N", "APP_W"),
                make_movement_mapping("MOV_W_E", "APP_W"),
            ],
            "detector_mappings": detector_mappings,
        }
    )


def make_observation(
    detector_id: str,
    vehicle_count: int,
    interval_start: datetime = FIRST_START,
) -> TrafficObservation:
    """Return one synthetic 15-minute observation at site 9."""

    interval_end = interval_start + timedelta(minutes=15)

    return TrafficObservation(
        observation_id=(
            f"OBS_SYN_9_{detector_id}_"
            f"{interval_end.strftime('%Y%m%dT%H%M')}"
        ),
        source=TrafficObservationSource.SYNTHETIC,
        site_id="9",
        detector_id=detector_id,
        interval_start=interval_start,
        interval_end=interval_end,
        vehicle_count=vehicle_count,
    )


def make_north_left_observations(
    interval_start: datetime = FIRST_START,
) -> list[TrafficObservation]:
    """Return observations from all three north left-turn detectors."""

    return [
        make_observation(
            detector_id="4",
            vehicle_count=10,
            interval_start=interval_start,
        ),
        make_observation(
            detector_id="5",
            vehicle_count=12,
            interval_start=interval_start,
        ),
        make_observation(
            detector_id="6",
            vehicle_count=7,
            interval_start=interval_start,
        ),
    ]


def test_demand_id_uses_source_movement_and_interval_end() -> None:
    demand_id = build_demand_id(
        source=TrafficObservationSource.SYNTHETIC,
        movement_id="MOV_N_E",
        interval_end=datetime.fromisoformat("2026-10-14T08:15:00+03:00"),
    )

    assert demand_id == "DEM_SYN_MOV_N_E_20261014T0815"


def test_rcrc_demand_id_uses_rcrc_code() -> None:
    demand_id = build_demand_id(
        source=TrafficObservationSource.RCRC,
        movement_id="MOV_N_E",
        interval_end=datetime.fromisoformat("2026-10-14T08:15:00+03:00"),
    )

    assert demand_id == "DEM_RCRC_MOV_N_E_20261014T0815"


def test_same_inputs_give_same_demand_id() -> None:
    interval_end = datetime.fromisoformat(
        "2026-10-14T08:15:00+03:00"
    )

    first = build_demand_id(
        source=TrafficObservationSource.SYNTHETIC,
        movement_id="MOV_N_E",
        interval_end=interval_end,
    )
    second = build_demand_id(
        source=TrafficObservationSource.SYNTHETIC,
        movement_id="MOV_N_E",
        interval_end=interval_end,
    )

    assert first == second


def test_usable_detectors_are_summed_into_one_demand() -> None:
    result = transform_observations(
        observations=make_north_left_observations(),
        config=make_valid_config(),
    )

    assert result.errors == []
    assert result.demand_count == 1

    demand = result.demands[0]

    assert demand.demand_id == "DEM_SYN_MOV_N_E_20261014T0815"
    assert demand.movement_id == "MOV_N_E"
    assert demand.vehicle_count == 29
    assert demand.source.value == "synthetic"
    assert demand.interval_start == FIRST_START
    assert demand.interval_end == FIRST_START + timedelta(minutes=15)


def test_demand_keeps_every_source_observation_id() -> None:
    observations = make_north_left_observations()

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert sorted(result.demands[0].source_observation_ids) == sorted(
        observation.observation_id
        for observation in observations
    )


def test_each_interval_gets_its_own_demand() -> None:
    second_start = FIRST_START + timedelta(minutes=15)

    result = transform_observations(
        observations=(
            make_north_left_observations(FIRST_START)
            + make_north_left_observations(second_start)
        ),
        config=make_valid_config(),
    )

    assert [
        demand.interval_start
        for demand in result.demands
    ] == [
        FIRST_START,
        second_start,
    ]


def test_vehicle_counts_are_conserved() -> None:
    observations = []

    for index in range(4):
        observations += make_north_left_observations(
            FIRST_START + timedelta(minutes=15 * index)
        )

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert result.demand_count == 4
    assert sum(
        demand.vehicle_count
        for demand in result.demands
    ) == sum(
        observation.vehicle_count
        for observation in observations
    )


def test_missing_detector_is_reported_and_gets_no_demand() -> None:
    observations = make_north_left_observations()[:2]

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.error_count == 1

    error = result.errors[0]

    assert error.message == "no observation from detector(s) 6"
    assert error.movement_id == "MOV_N_E"
    assert len(error.observation_ids) == 2


def test_identical_duplicate_is_used_once_and_reported() -> None:
    observations = make_north_left_observations()
    observations.append(make_observation(detector_id="4", vehicle_count=10))

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert result.demands[0].vehicle_count == 29
    assert result.error_count == 1
    assert result.errors[0].message == "duplicate observation ignored"


def test_conflicting_duplicate_is_reported_and_gets_no_demand() -> None:
    observations = make_north_left_observations()
    observations.append(make_observation(detector_id="4", vehicle_count=14))

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.error_count == 1
    assert result.errors[0].message == (
        "detector sent different counts: 10 and 14"
    )
    assert result.errors[0].movement_id == "MOV_N_E"


def test_shared_lane_observation_is_reported() -> None:
    result = transform_observations(
        observations=[make_observation(detector_id="2", vehicle_count=40)],
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.errors[0].detector_id == "2"
    assert "MOV_W_N, MOV_W_E" in result.errors[0].message


def test_movement_with_shared_detector_gets_no_demand() -> None:
    config = make_valid_config(
        detector_mappings=[
            make_detector_mapping(
                detector_id="1",
                approach_id="APP_W",
                movement_ids=["MOV_W_N"],
                mapping_status="usable",
            ),
            make_detector_mapping(
                detector_id="2",
                approach_id="APP_W",
                movement_ids=["MOV_W_N", "MOV_W_E"],
                mapping_status="requires_allocation",
            ),
        ]
    )

    result = transform_observations(
        observations=[
            make_observation(
                detector_id="1",
                vehicle_count=30,
            ),
            make_observation(
                detector_id="2",
                vehicle_count=40,
            ),
        ],
        config=config,
    )

    assert result.demands == []

    movement_errors = [
        error
        for error in result.errors
        if error.movement_id == "MOV_W_N"
    ]

    assert len(movement_errors) == 1
    assert movement_errors[0].message == (
        "movement also uses shared detector(s) 2; "
        "no allocation rule adopted"
    )
    assert movement_errors[0].observation_ids == (
        "OBS_SYN_9_1_20261014T0815",
    )


def test_shared_detector_does_not_block_other_movements() -> None:
    observations = make_north_left_observations()
    observations.append(make_observation(detector_id="2", vehicle_count=40))

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert [
        demand.movement_id
        for demand in result.demands
    ] == ["MOV_N_E"]
    assert result.demands[0].vehicle_count == 29


def test_unresolved_observation_is_reported() -> None:
    result = transform_observations(
        observations=[make_observation(detector_id="3", vehicle_count=25)],
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.errors[0].message == "detector mapping is unresolved"


def test_unmapped_detector_is_reported() -> None:
    result = transform_observations(
        observations=[make_observation(detector_id="99", vehicle_count=5)],
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.errors[0].message == "detector has no mapping"


def test_good_observations_still_become_demand_next_to_errors() -> None:
    observations = make_north_left_observations()
    observations += [
        make_observation(detector_id="2", vehicle_count=40),
        make_observation(detector_id="3", vehicle_count=25),
        make_observation(detector_id="99", vehicle_count=5),
    ]

    result = transform_observations(
        observations=observations,
        config=make_valid_config(),
    )

    assert result.demand_count == 1
    assert result.demands[0].vehicle_count == 29
    assert result.error_count == 3


def test_empty_batch_gives_empty_result() -> None:
    result = transform_observations(
        observations=[],
        config=make_valid_config(),
    )

    assert result.demands == []
    assert result.errors == []


def test_detector_mapped_to_unknown_movement_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="unmapped movement",
    ):
        make_valid_config(
            detector_mappings=[
                make_detector_mapping(
                    detector_id="4",
                    approach_id="APP_N",
                    movement_ids=["MOV_N_X"],
                    mapping_status="usable",
                ),
            ]
        )

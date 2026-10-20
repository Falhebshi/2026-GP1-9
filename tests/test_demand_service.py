from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.demand.service import (
    DemandTransformationResult,
    build_demand_id,
    split_count,
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


def make_west_config() -> NetworkMappingConfig:
    """
    Return a mapping for the west approach: detector 1 counts the left
    turn MOV_W_N alone, detector 3 the through movement MOV_W_E alone,
    and detector 2 the shared lane serving both.
    """

    return make_valid_config(
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
            make_detector_mapping(
                detector_id="3",
                approach_id="APP_W",
                movement_ids=["MOV_W_E"],
                mapping_status="usable",
            ),
        ]
    )


def make_west_observations(
    left: int,
    shared: int,
    through: int,
) -> list[TrafficObservation]:
    """Return observations from west detectors 1, 2 and 3."""

    return [
        make_observation(
            detector_id="1",
            vehicle_count=left,
        ),
        make_observation(
            detector_id="2",
            vehicle_count=shared,
        ),
        make_observation(
            detector_id="3",
            vehicle_count=through,
        ),
    ]


def demand_counts(
    result: DemandTransformationResult,
) -> dict[str, int]:
    """Return the vehicle count of each movement's demand."""

    return {
        demand.movement_id: demand.vehicle_count
        for demand in result.demands
    }


def test_shared_lane_count_is_split_by_exclusive_lanes() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=20,
            through=30,
        ),
        config=make_west_config(),
    )

    assert result.errors == []
    assert demand_counts(result) == {
        "MOV_W_N": 10 + 5,
        "MOV_W_E": 30 + 15,
    }


def test_split_demand_is_marked_as_allocated() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=20,
            through=30,
        ),
        config=make_west_config(),
    )

    for demand in result.demands:
        assert demand.is_allocated
        assert demand.allocated_observation_ids == [
            "OBS_SYN_9_2_20261014T0815",
        ]
        assert "OBS_SYN_9_2_20261014T0815" in (
            demand.source_observation_ids
        )


def test_split_keeps_the_lane_total_in_whole_vehicles() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=45,
            through=10,
        ),
        config=make_west_config(),
    )

    assert demand_counts(result) == {
        "MOV_W_N": 10 + 22,
        "MOV_W_E": 10 + 23,
    }


def test_quiet_left_lane_gives_few_lefts_in_shared_lane() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=1,
            shared=20,
            through=30,
        ),
        config=make_west_config(),
    )

    assert demand_counts(result) == {
        "MOV_W_N": 1 + 1,
        "MOV_W_E": 30 + 19,
    }


def test_shared_lane_is_split_equally_when_exclusive_lanes_are_empty() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=0,
            shared=20,
            through=0,
        ),
        config=make_west_config(),
    )

    assert demand_counts(result) == {
        "MOV_W_N": 10,
        "MOV_W_E": 10,
    }


def test_split_conserves_vehicle_counts() -> None:
    observations = make_west_observations(
        left=17,
        shared=33,
        through=41,
    )

    result = transform_observations(
        observations=observations,
        config=make_west_config(),
    )

    assert sum(demand_counts(result).values()) == sum(
        observation.vehicle_count
        for observation in observations
    )


def test_missing_exclusive_lane_detector_blocks_both_movements() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=20,
            through=30,
        )[:2],
        config=make_west_config(),
    )

    assert result.demands == []
    assert {
        error.movement_id: error.message
        for error in result.errors
    } == {
        "MOV_W_N": "split of shared detector 2 needs detector(s) 3",
        "MOV_W_E": "split of shared detector 2 needs detector(s) 3",
    }


def test_missing_shared_detector_is_reported() -> None:
    observations = make_west_observations(
        left=10,
        shared=20,
        through=30,
    )

    result = transform_observations(
        observations=[observations[0], observations[2]],
        config=make_west_config(),
    )

    assert result.demands == []
    assert {
        error.message
        for error in result.errors
    } == {"no observation from detector(s) 2"}


def test_conflicting_shared_detector_blocks_both_movements() -> None:
    observations = make_west_observations(
        left=10,
        shared=20,
        through=30,
    )
    observations.append(
        make_observation(
            detector_id="2",
            vehicle_count=24,
        )
    )

    result = transform_observations(
        observations=observations,
        config=make_west_config(),
    )

    assert result.demands == []
    assert [
        error.message
        for error in result.errors
        if error.movement_id is not None
    ] == [
        "shared detector 2 sent different counts",
        "shared detector 2 sent different counts",
    ]


def test_shared_lane_without_exclusive_lanes_is_reported() -> None:
    result = transform_observations(
        observations=[
            make_observation(
                detector_id="2",
                vehicle_count=40,
            ),
        ],
        config=make_valid_config(),
    )

    assert result.demands == []
    assert {
        error.message
        for error in result.errors
    } == {
        "shared detector 2 has no exclusive lane for every movement "
        "to split by"
    }


def test_share_adjustment_changes_the_split() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=20,
            through=30,
        ),
        config=make_west_config(),
        share_adjustments={"MOV_W_N": 0.2},
    )

    assert demand_counts(result) == {
        "MOV_W_N": 10 + 9,
        "MOV_W_E": 30 + 11,
    }


def test_share_adjustment_is_kept_between_zero_and_one() -> None:
    result = transform_observations(
        observations=make_west_observations(
            left=10,
            shared=20,
            through=30,
        ),
        config=make_west_config(),
        share_adjustments={"MOV_W_N": -0.5},
    )

    assert demand_counts(result) == {
        "MOV_W_N": 10,
        "MOV_W_E": 30 + 20,
    }


def test_share_adjustment_for_unshared_movement_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="which no shared-lane detector serves",
    ):
        transform_observations(
            observations=make_north_left_observations(),
            config=make_west_config(),
            share_adjustments={"MOV_N_E": 0.2},
        )


def test_split_count_gives_ties_to_the_first_movement() -> None:
    assert split_count(
        vehicle_count=5,
        shares={
            "MOV_W_N": 0.5,
            "MOV_W_E": 0.5,
        },
    ) == {
        "MOV_W_E": 3,
        "MOV_W_N": 2,
    }


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
    assert result.error_count == 4


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

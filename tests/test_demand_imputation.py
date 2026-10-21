from datetime import datetime, timedelta

from backend.demand.imputation import (
    MAX_GAP_INTERVALS,
    day_type,
    fit_neighbour_line,
    missing_run_length,
)
from backend.demand.service import transform_observations
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import (
    ImputationMethod,
    TrafficObservation,
    TrafficObservationSource,
)


# A Sunday, so the interval is a workday
NOW = datetime.fromisoformat("2026-10-18T08:00:00+03:00")
INTERVAL = timedelta(minutes=15)


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


def make_config() -> NetworkMappingConfig:
    """
    Return a mapping with the north left turn MOV_N_E on detectors 4, 5
    and 6 (neighbours of each other), the west slip MOV_W_S_SLIP on
    detector 13 alone, and the west shared lane on detectors 1, 2 and 3.
    """

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
                make_movement_mapping("MOV_W_S_SLIP", "APP_W"),
            ],
            "detector_mappings": [
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
                    detector_id="13",
                    approach_id="APP_W",
                    movement_ids=["MOV_W_S_SLIP"],
                    mapping_status="usable",
                ),
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
            ],
        }
    )


def make_observation(
    detector_id: str,
    vehicle_count: int,
    interval_start: datetime = NOW,
) -> TrafficObservation:
    """Return one synthetic 15-minute observation at site 9."""

    interval_end = interval_start + INTERVAL

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


def north_counts(step: int) -> dict[str, int]:
    """
    Return the counts of detectors 4, 5 and 6 for one past interval.
    Detector 4 always counts one more than detector 5, and detector 6
    twice detector 5 minus 3.
    """

    detector_5 = 10 + step % 9

    return {
        "1": 10,
        "3": 30,
        "4": detector_5 + 1,
        "5": detector_5,
        "6": 2 * detector_5 - 3,
    }


def make_history(
    days: int,
    detector_ids: tuple[str, ...] = ("4", "5", "6"),
) -> list[TrafficObservation]:
    """
    Return the past observations of the given detectors for every
    interval of the days before NOW. Detector 13 counts 7 at 08:00 on
    workdays, 40 at 08:00 on Fridays and Saturdays, and 20 otherwise.
    """

    history = []
    first = NOW - timedelta(days=days)
    steps = days * 96

    for step in range(steps):
        interval_start = first + step * INTERVAL
        counts = north_counts(step)
        counts["13"] = 20

        if interval_start.time() == NOW.time():
            counts["13"] = (
                7
                if day_type(interval_start) == "workday"
                else 40
            )

        for detector_id in detector_ids:
            history.append(
                make_observation(
                    detector_id=detector_id,
                    vehicle_count=counts[detector_id],
                    interval_start=interval_start,
                )
            )

    return history


def test_day_types_follow_the_rcrc_analysis() -> None:
    assert day_type(NOW) == "workday"
    assert day_type(NOW + timedelta(days=5)) == "friday"
    assert day_type(NOW + timedelta(days=6)) == "saturday"


def test_neighbour_line_is_fitted_on_common_intervals() -> None:
    target = {
        NOW - step * INTERVAL: 2 * (10 + step % 9) - 3
        for step in range(1, 500)
    }
    neighbour = {
        NOW - step * INTERVAL: 10 + step % 9
        for step in range(1, 500)
    }

    intercept, slope = fit_neighbour_line(
        target_counts=target,
        neighbour_counts=neighbour,
    )

    assert round(intercept, 6) == -3
    assert round(slope, 6) == 2


def test_neighbour_line_needs_five_days_of_common_intervals() -> None:
    target = {
        NOW - step * INTERVAL: step % 9
        for step in range(1, 100)
    }

    assert fit_neighbour_line(
        target_counts=target,
        neighbour_counts=target,
    ) is None


def test_missing_run_counts_both_directions() -> None:
    present = {NOW - 3 * INTERVAL, NOW + 2 * INTERVAL}

    assert missing_run_length(
        present=present,
        interval_start=NOW,
        first_known=NOW - 10 * INTERVAL,
        last_known=NOW + 10 * INTERVAL,
    ) == 4


def test_missing_detector_is_estimated_from_its_neighbours() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=16),
            make_observation(detector_id="5", vehicle_count=15),
        ],
        config=make_config(),
        history=make_history(days=6),
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_N_E"
    )

    assert demand.vehicle_count == 16 + 15 + (2 * 15 - 3)
    assert demand.is_imputed
    assert [
        (detector.detector_id, detector.method)
        for detector in demand.imputed_detectors
    ] == [("6", ImputationMethod.NEIGHBOUR_REGRESSION)]


def test_estimate_is_the_median_of_the_neighbour_estimates() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=20),
            make_observation(detector_id="5", vehicle_count=15),
        ],
        config=make_config(),
        history=make_history(days=6),
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_N_E"
    )

    from_detector_5 = 2 * 15 - 3
    from_detector_4 = 2 * (20 - 1) - 3

    assert demand.vehicle_count == 20 + 15 + (
        from_detector_5 + from_detector_4
    ) // 2


def test_detector_without_neighbours_uses_its_historical_average() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=14),
        ],
        config=make_config(),
        history=make_history(
            days=22,
            detector_ids=("4", "13"),
        ),
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_W_S_SLIP"
    )

    assert demand.vehicle_count == 7
    assert demand.source_observation_ids == []
    assert [
        (detector.detector_id, detector.method)
        for detector in demand.imputed_detectors
    ] == [("13", ImputationMethod.HISTORICAL_AVERAGE)]


def test_historical_average_uses_the_same_day_type() -> None:
    friday = NOW - timedelta(days=2)
    history = [
        observation
        for observation in make_history(
            days=29,
            detector_ids=("4", "13"),
        )
        if not (
            observation.detector_id == "13"
            and observation.interval_start == friday
        )
    ]

    result = transform_observations(
        observations=[
            make_observation(
                detector_id="4",
                vehicle_count=14,
                interval_start=friday,
            ),
        ],
        config=make_config(),
        history=history,
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_W_S_SLIP"
    )

    assert demand.vehicle_count == 40


def test_too_little_history_leaves_the_detector_missing() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=14),
            make_observation(detector_id="5", vehicle_count=15),
        ],
        config=make_config(),
        history=make_history(days=2),
    )

    assert [
        demand.movement_id
        for demand in result.demands
    ] == []
    assert [
        error.message
        for error in result.errors
    ] == ["no observation from detector(s) 6"]


def test_gap_longer_than_one_hour_is_not_filled() -> None:
    history = [
        observation
        for observation in make_history(days=6)
        if not (
            observation.detector_id == "6"
            and observation.interval_start
            >= NOW - MAX_GAP_INTERVALS * INTERVAL
        )
    ]

    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=14),
            make_observation(detector_id="5", vehicle_count=15),
        ],
        config=make_config(),
        history=history,
    )

    assert result.demands == []
    assert [
        error.message
        for error in result.errors
    ] == ["no observation from detector(s) 6"]


def test_shared_lane_detector_is_never_estimated() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="1", vehicle_count=10),
            make_observation(detector_id="3", vehicle_count=30),
        ],
        config=make_config(),
        history=make_history(
            days=22,
            detector_ids=("4", "13"),
        ),
    )

    assert {
        error.movement_id: error.message
        for error in result.errors
        if error.movement_id in ("MOV_W_N", "MOV_W_E")
    } == {
        "MOV_W_N": "no observation from detector(s) 2",
        "MOV_W_E": "no observation from detector(s) 2",
    }


def test_reported_demand_is_not_marked_as_imputed() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=14),
            make_observation(detector_id="5", vehicle_count=15),
            make_observation(detector_id="6", vehicle_count=27),
        ],
        config=make_config(),
        history=make_history(days=6),
    )

    demand = next(
        demand
        for demand in result.demands
        if demand.movement_id == "MOV_N_E"
    )

    assert demand.vehicle_count == 14 + 15 + 27
    assert not demand.is_imputed


def test_without_history_nothing_is_estimated() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=14),
            make_observation(detector_id="5", vehicle_count=15),
        ],
        config=make_config(),
    )

    assert result.demands == []
    assert [
        error.message
        for error in result.errors
    ] == ["no observation from detector(s) 6"]


def test_estimated_exclusive_lane_is_used_for_the_split() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="1", vehicle_count=10),
            make_observation(detector_id="2", vehicle_count=20),
        ],
        config=make_config(),
        history=make_history(
            days=22,
            detector_ids=("1", "3"),
        ),
    )

    demands = {
        demand.movement_id: demand
        for demand in result.demands
    }

    assert demands["MOV_W_N"].vehicle_count == 10 + 5
    assert demands["MOV_W_E"].vehicle_count == 30 + 15

    for movement_id in ("MOV_W_N", "MOV_W_E"):
        assert demands[movement_id].is_allocated
        assert [
            detector.detector_id
            for detector in demands[movement_id].imputed_detectors
        ] == ["3"]


def north_left_demand(result) -> int:
    """Return the MOV_N_E demand at NOW in a transformation result."""

    return next(
        demand.vehicle_count
        for demand in result.demands
        if demand.movement_id == "MOV_N_E"
        and demand.interval_start == NOW
    )


def make_rejected_observation() -> TrafficObservation:
    """Return a 30-minute detector 6 observation, which is rejected."""

    return TrafficObservation(
        observation_id="OBS_REJECTED",
        source=TrafficObservationSource.SYNTHETIC,
        site_id="9",
        detector_id="6",
        interval_start=NOW - INTERVAL,
        interval_end=NOW + INTERVAL,
        vehicle_count=9999,
    )


def test_rejected_observation_is_not_used_for_estimates() -> None:
    result = transform_observations(
        observations=[
            make_observation(detector_id="4", vehicle_count=16),
            make_observation(detector_id="5", vehicle_count=15),
            make_rejected_observation(),
        ],
        config=make_config(),
        history=make_history(days=6),
    )

    assert north_left_demand(result) == 16 + 15 + (2 * 15 - 3)
    assert [
        error.message
        for error in result.errors
    ] == ["observation interval must be 15 minutes"]


def test_conflicting_batch_counts_are_not_used_in_any_order() -> None:
    earlier = NOW - INTERVAL
    current = [
        make_observation(
            detector_id="4",
            vehicle_count=16,
        ),
        make_observation(
            detector_id="5",
            vehicle_count=15,
        ),
        make_observation(
            detector_id="4",
            vehicle_count=12,
            interval_start=earlier,
        ),
        make_observation(
            detector_id="5",
            vehicle_count=11,
            interval_start=earlier,
        ),
    ]
    conflicting = [
        make_observation(
            detector_id="6",
            vehicle_count=19,
            interval_start=earlier,
        ),
        make_observation(
            detector_id="6",
            vehicle_count=9999,
            interval_start=earlier,
        ),
    ]

    for ordered in (conflicting, conflicting[::-1]):
        result = transform_observations(
            observations=current + ordered,
            config=make_config(),
            history=make_history(days=6),
        )

        assert north_left_demand(result) == 16 + 15 + (2 * 15 - 3)


def test_conflicting_history_counts_are_not_used_in_any_order() -> None:
    history = make_history(days=6)
    conflicting = make_observation(
        detector_id="6",
        vehicle_count=9999,
        interval_start=NOW - INTERVAL,
    )

    for ordered in (history + [conflicting], [conflicting] + history):
        result = transform_observations(
            observations=[
                make_observation(detector_id="4", vehicle_count=16),
                make_observation(detector_id="5", vehicle_count=15),
            ],
            config=make_config(),
            history=ordered,
        )

        assert north_left_demand(result) == 16 + 15 + (2 * 15 - 3)


def test_history_without_valid_observations_gives_window_errors() -> None:
    result = transform_observations(
        observations=[],
        config=make_config(),
        history=[make_rejected_observation()],
        window_start=NOW,
        window_end=NOW + INTERVAL,
    )

    assert result.demands == []
    assert [
        (error.movement_id, error.message)
        for error in result.errors
    ] == [
        ("MOV_N_E", "no observation from detector(s) 4, 5, 6"),
        ("MOV_W_E", "no observation from detector(s) 2, 3"),
        ("MOV_W_N", "no observation from detector(s) 1, 2"),
        ("MOV_W_S_SLIP", "no observation from detector(s) 13"),
    ]

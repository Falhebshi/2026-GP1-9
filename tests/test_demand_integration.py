"""Transform one synthetic batch using the real network mappings."""

from datetime import datetime, timedelta

from backend.demand.service import (
    DEFAULT_MAPPING_PATH,
    build_simulation_demand,
)
from jaadah.models.traffic import (
    TrafficObservation,
    TrafficObservationSource,
)


INTERVAL_START = datetime.fromisoformat("2026-10-14T08:00:00+03:00")
INTERVAL_END = INTERVAL_START + timedelta(minutes=15)


def make_observation(
    detector_id: int,
    vehicle_count: int,
) -> TrafficObservation:
    """Return one synthetic 15-minute observation at site 9."""

    return TrafficObservation(
        observation_id=f"OBS_SYN_9_{detector_id}_20261014T0815",
        source=TrafficObservationSource.SYNTHETIC,
        site_id="9",
        detector_id=str(detector_id),
        interval_start=INTERVAL_START,
        interval_end=INTERVAL_END,
        vehicle_count=vehicle_count,
    )


def make_all_detector_observations() -> list[TrafficObservation]:
    """
    Return one observation from each of the 16 synthetic detectors.
    Detector n counts 10 * n vehicles, so every total can be checked.
    """

    return [
        make_observation(
            detector_id=detector_id,
            vehicle_count=10 * detector_id,
        )
        for detector_id in range(1, 17)
    ]


def test_real_mappings_give_demand_for_every_detected_movement() -> None:
    result = build_simulation_demand(
        observations=make_all_detector_observations(),
    )

    assert result.errors == []

    assert {
        demand.movement_id: demand.vehicle_count
        for demand in result.demands
    } == {
        "MOV_W_N": 10 + 5,
        "MOV_W_E": 30 + 15,
        "MOV_E_S": 90 + 44,
        "MOV_E_W": 110 + 120 + 56,
        "MOV_N_E": 40 + 50 + 60,
        "MOV_S_W": 70 + 80,
        "MOV_W_S_SLIP": 130,
        "MOV_N_W_SLIP": 140,
        "MOV_S_E_BYPASS": 150 + 160,
    }

    assert all(
        demand.interval_start == INTERVAL_START
        and demand.interval_end == INTERVAL_END
        for demand in result.demands
    )


def test_real_mappings_mark_only_shared_lane_movements_as_allocated() -> None:
    result = build_simulation_demand(
        observations=make_all_detector_observations(),
    )

    assert {
        demand.movement_id: demand.allocated_observation_ids
        for demand in result.demands
        if demand.is_allocated
    } == {
        "MOV_W_N": ["OBS_SYN_9_2_20261014T0815"],
        "MOV_W_E": ["OBS_SYN_9_2_20261014T0815"],
        "MOV_E_S": ["OBS_SYN_9_10_20261014T0815"],
        "MOV_E_W": ["OBS_SYN_9_10_20261014T0815"],
    }


def test_sensitivity_run_keeps_approach_totals() -> None:
    observations = make_all_detector_observations()

    baseline = build_simulation_demand(
        observations=observations,
    )

    for adjustment in (-0.2, 0.2):
        adjusted = build_simulation_demand(
            observations=observations,
            share_adjustments={
                "MOV_W_N": adjustment,
                "MOV_E_S": adjustment,
            },
        )

        for pair in (
            ("MOV_W_N", "MOV_W_E"),
            ("MOV_E_S", "MOV_E_W"),
        ):
            assert sum(
                demand.vehicle_count
                for demand in adjusted.demands
                if demand.movement_id in pair
            ) == sum(
                demand.vehicle_count
                for demand in baseline.demands
                if demand.movement_id in pair
            )


def test_every_counted_vehicle_is_in_demand_or_reported() -> None:
    observations = make_all_detector_observations()

    result = build_simulation_demand(
        observations=observations,
    )

    used_ids = {
        observation_id
        for demand in result.demands
        for observation_id in demand.source_observation_ids
    }
    reported_ids = {
        observation_id
        for error in result.errors
        for observation_id in error.observation_ids
    }

    assert used_ids | reported_ids == {
        observation.observation_id
        for observation in observations
    }
    assert used_ids.isdisjoint(reported_ids)


def test_mapping_path_can_be_given_explicitly() -> None:
    observations = make_all_detector_observations()

    default_result = build_simulation_demand(
        observations=observations,
    )
    explicit_result = build_simulation_demand(
        observations=observations,
        mapping_path=str(DEFAULT_MAPPING_PATH),
    )

    assert explicit_result.demands == default_result.demands
    assert explicit_result.errors == default_result.errors

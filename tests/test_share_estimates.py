from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.demand.service import (
    DEFAULT_MAPPING_PATH,
    build_demand_id,
    build_simulation_demand,
    transform_observations,
)
from backend.demand.share_estimates import (
    DEFAULT_SHARE_CONFIG_PATH,
    ShareConfig,
    estimate_undetected_movements,
    load_share_config,
    validate_share_config,
)
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import (
    ShareOrigin,
    ShareScenario,
    TrafficObservation,
    TrafficObservationSource,
)


NOW = datetime.fromisoformat("2026-10-18T08:00:00+03:00")
INTERVAL = timedelta(minutes=15)


def movement(movement_id: str, approach_id: str) -> dict:
    return {
        "movement_id": movement_id,
        "intersection_id": "INT_001",
        "approach_id": approach_id,
        "sumo_route_edge_ids": [f"{movement_id}_in", f"{movement_id}_out"],
        "signal_controlled": False,
    }


def detector(detector_id: str, approach_id: str, movement_ids: list[str],
             status: str = "usable") -> dict:
    return {
        "source": "rcrc",
        "site_id": "1444",
        "detector_id": detector_id,
        "intersection_id": "INT_001",
        "approach_id": approach_id,
        "movement_ids": movement_ids,
        "mapping_status": status,
    }


def make_config(extra_movements: tuple[dict, ...] = ()) -> NetworkMappingConfig:
    """
    West approach: left MOV_W_N (detector 1), shared lane (2), through
    MOV_W_E (3) and the slip MOV_W_S_SLIP with no detector. North:
    MOV_N_E (4), no detector on MOV_N_W_SLIP.
    """

    return NetworkMappingConfig.model_validate({
        "schema_version": "2.1",
        "mapping_version": "test",
        "network": {"version": "test", "path": "test.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "approach_mappings": [
            {"approach_id": "APP_W", "intersection_id": "INT_001", "approach_side": "west"},
            {"approach_id": "APP_N", "intersection_id": "INT_001", "approach_side": "north"},
        ],
        "movement_mappings": [
            movement("MOV_W_N", "APP_W"),
            movement("MOV_W_E", "APP_W"),
            movement("MOV_W_S_SLIP", "APP_W"),
            movement("MOV_N_E", "APP_N"),
            movement("MOV_N_W_SLIP", "APP_N"),
            *extra_movements,
        ],
        "detector_mappings": [
            detector("1", "APP_W", ["MOV_W_N"]),
            detector("2", "APP_W", ["MOV_W_N", "MOV_W_E"], "requires_allocation"),
            detector("3", "APP_W", ["MOV_W_E"]),
            detector("4", "APP_N", ["MOV_N_E"]),
        ],
    })


def share(movement_id="MOV_W_S_SLIP", basis=("MOV_W_N", "MOV_W_E"),
          low=0.1, central=0.2, high=0.4, origin="assumed") -> dict:
    return {
        "movement_id": movement_id,
        "source": "rcrc",
        "basis_movement_ids": list(basis),
        "ratio": {"low": low, "central": central, "high": high},
        "share_origin": origin,
        "note": "test",
    }


def make_shares(*items) -> ShareConfig:
    return ShareConfig.model_validate({
        "config_version": "test",
        "description": "test",
        "shares": list(items) or [share()],
    })


def observation(detector_id: str, count: int, start: datetime = NOW) -> TrafficObservation:
    end = start + INTERVAL
    return TrafficObservation(
        observation_id=f"OBS_RCRC_1444_{detector_id}_{end:%Y%m%dT%H%M}",
        source=TrafficObservationSource.RCRC,
        site_id="1444",
        detector_id=detector_id,
        interval_start=start,
        interval_end=end,
        vehicle_count=count,
    )


def west(start: datetime = NOW) -> list[TrafficObservation]:
    """West approach: 10 left, 20 shared (split 10:30), 30 through."""

    return [observation("1", 10, start), observation("2", 20, start),
            observation("3", 30, start)]


def demands_by_movement(result):
    return {demand.movement_id: demand for demand in result.demands}


# ============================================================
# ESTIMATES
# ============================================================

def test_slip_is_the_ratio_of_its_basis_movements():
    result = transform_observations(west(), make_config(), share_config=make_shares())

    slip = demands_by_movement(result)["MOV_W_S_SLIP"]

    # Basis: MOV_W_N 10 + 5, MOV_W_E 30 + 15 = 60 vehicles.
    assert slip.vehicle_count == 12
    assert slip.is_share_estimated
    assert slip.source_observation_ids == []
    assert slip.share_estimate.ratio == 0.2
    assert slip.share_estimate.scenario == ShareScenario.CENTRAL
    assert slip.share_estimate.share_origin == ShareOrigin.ASSUMED
    assert slip.share_estimate.basis_demand_ids == [
        "DEM_RCRC_MOV_W_N_20261018T0815",
        "DEM_RCRC_MOV_W_E_20261018T0815",
    ]


def test_estimated_demand_id_matches_the_service_format():
    result = transform_observations(west(), make_config(), share_config=make_shares())

    slip = demands_by_movement(result)["MOV_W_S_SLIP"]

    assert slip.demand_id == build_demand_id(
        TrafficObservationSource.RCRC, "MOV_W_S_SLIP", NOW + INTERVAL,
    )


@pytest.mark.parametrize(
    "scenario,expected",
    [(ShareScenario.LOW, 6), (ShareScenario.CENTRAL, 12), (ShareScenario.HIGH, 24)],
)
def test_scenario_picks_the_ratio(scenario, expected):
    result = transform_observations(
        west(), make_config(), share_config=make_shares(), share_scenario=scenario,
    )

    slip = demands_by_movement(result)["MOV_W_S_SLIP"]

    assert slip.vehicle_count == expected
    assert slip.share_estimate.scenario == scenario


def test_estimate_is_rounded_to_whole_vehicles():
    result = transform_observations(
        west(), make_config(), share_config=make_shares(share(central=0.125)),
    )

    # 0.125 x 60 = 7.5, rounded half up.
    assert demands_by_movement(result)["MOV_W_S_SLIP"].vehicle_count == 8


def test_missing_basis_movement_gives_an_error_not_an_estimate():
    north = share(movement_id="MOV_N_W_SLIP", basis=("MOV_N_E",))

    result = transform_observations(
        west(), make_config(), share_config=make_shares(share(), north),
        window_start=NOW, window_end=NOW + INTERVAL,
    )

    assert "MOV_N_W_SLIP" not in demands_by_movement(result)
    assert "MOV_W_S_SLIP" in demands_by_movement(result)
    assert [
        error.message for error in result.errors if error.movement_id == "MOV_N_W_SLIP"
    ] == ["no estimate: basis movement(s) MOV_N_E have no demand"]


def test_window_interval_without_data_is_reported_for_the_slip():
    result = transform_observations(
        west(), make_config(), share_config=make_shares(),
        window_start=NOW, window_end=NOW + 2 * INTERVAL,
    )

    slip_errors = [e for e in result.errors if e.movement_id == "MOV_W_S_SLIP"]

    assert [e.interval_end for e in slip_errors] == [NOW + 2 * INTERVAL]


def test_imputed_basis_detectors_are_carried_to_the_estimate():
    history = []
    first = NOW - timedelta(days=22)
    for step in range(22 * 96):
        history += west(first + step * INTERVAL)

    observations = [observation("1", 10), observation("2", 20)]

    result = transform_observations(
        observations, make_config(), history=history, share_config=make_shares(),
    )

    slip = demands_by_movement(result)["MOV_W_S_SLIP"]

    assert [d.detector_id for d in slip.imputed_detectors] == ["3"]
    assert slip.is_imputed and slip.is_share_estimated


def test_nothing_is_estimated_without_a_share_config():
    result = transform_observations(west(), make_config())

    assert "MOV_W_S_SLIP" not in demands_by_movement(result)


def test_source_without_a_share_is_not_estimated():
    estimates, problems = estimate_undetected_movements(
        demands=transform_observations(west(), make_config()).demands,
        share_config=make_shares(),
        config=make_config(),
        sources={TrafficObservationSource.SYNTHETIC},
    )

    assert estimates == []
    assert problems == []


def test_demands_stay_ordered_by_interval_and_movement():
    observations = west() + west(NOW + INTERVAL)

    result = transform_observations(observations, make_config(), share_config=make_shares())

    keys = [(d.interval_start, d.movement_id) for d in result.demands]
    assert keys == sorted(keys)


# ============================================================
# CONFIGURATION
# ============================================================

@pytest.mark.parametrize(
    "item,message",
    [
        (share(movement_id="MOV_X"), "unknown movement"),
        (share(movement_id="MOV_W_N", basis=("MOV_W_E",)), "has a detector"),
        (share(basis=("MOV_N_E",)), "on another approach"),
        (share(movement_id="MOV_N_W_SLIP", basis=("MOV_W_S_SLIP",)), "another approach"),
        (share(basis=("MOV_W_N", "MOV_X")), "unknown basis movement"),
    ],
)
def test_share_config_must_fit_the_mapping(item, message):
    with pytest.raises(ValueError, match=message):
        validate_share_config(make_shares(item), make_config())


def test_basis_movement_needs_a_detector():
    config = make_config(extra_movements=(movement("MOV_W_W_UTURN", "APP_W"),))

    with pytest.raises(ValueError, match="has no detector"):
        validate_share_config(
            make_shares(share(basis=("MOV_W_N", "MOV_W_W_UTURN"))), config,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"ratio": {"low": 0.3, "central": 0.2, "high": 0.4}},
        {"ratio": {"low": -0.1, "central": 0.2, "high": 0.4}},
        {"basis_movement_ids": []},
        {"basis_movement_ids": ["MOV_W_S_SLIP"]},
        {"share_origin": "guess"},
        {"note": " "},
    ],
)
def test_invalid_share_entry_is_rejected(change):
    with pytest.raises(ValidationError):
        make_shares(share() | change)


def test_one_share_per_movement_and_source():
    with pytest.raises(ValidationError, match="one share per source"):
        make_shares(share(), share())


# ============================================================
# REPOSITORY CONFIGURATION
# ============================================================

def test_repository_shares_fit_the_study_area_mapping():
    shares = load_share_config(DEFAULT_SHARE_CONFIG_PATH)

    validate_share_config(shares, load_network_mappings(DEFAULT_MAPPING_PATH))

    assert {item.movement_id for item in shares.shares} == {
        "MOV_W_S_SLIP", "MOV_N_W_SLIP", "MOV_S_E_BYPASS",
    }
    assert {item.source for item in shares.shares} == {TrafficObservationSource.RCRC}


def test_repository_shares_are_labelled_as_assumptions_until_counts_arrive():
    """Change this test when RCRC turning counts replace the placeholders."""

    shares = load_share_config(DEFAULT_SHARE_CONFIG_PATH)

    assert {item.share_origin for item in shares.shares} == {ShareOrigin.ASSUMED}


def test_synthetic_demand_is_unchanged_by_the_repository_shares():
    """Synthetic slips have their own detectors and are never estimated."""

    observations = [
        TrafficObservation(
            observation_id=f"OBS_SYN_9_{i}_20261018T0815",
            source=TrafficObservationSource.SYNTHETIC,
            site_id="9",
            detector_id=str(i),
            interval_start=NOW,
            interval_end=NOW + INTERVAL,
            vehicle_count=10,
        )
        for i in range(1, 17)
    ]

    with_shares = build_simulation_demand(observations)
    without = build_simulation_demand(observations, share_config_path=None)

    assert with_shares.demands == without.demands
    assert not any(demand.is_share_estimated for demand in with_shares.demands)


def test_repository_ratios_follow_the_lane_rule():
    """
    Central = slip lanes / counted lanes on the approach; low = half,
    high = double (docs/traffic_demand_transformation.md).
    """

    config = load_network_mappings(DEFAULT_MAPPING_PATH)
    lanes = config.approach_lanes
    counted = {
        (d.approach_id, d.lane_id)
        for d in config.detector_mappings
        if d.source == TrafficObservationSource.RCRC
    }

    for item in load_share_config(DEFAULT_SHARE_CONFIG_PATH).shares:
        approach_id = config.canonical_movements[item.movement_id].approach_id
        slip_lanes = [
            lane for lane in lanes
            if lane.served_movement_ids == [item.movement_id]
        ]
        counted_lanes = [lane for (approach, lane) in counted if approach == approach_id]
        central = len(slip_lanes) / len(counted_lanes)

        assert item.ratio.central == pytest.approx(central), item.movement_id
        assert item.ratio.low == pytest.approx(central / 2), item.movement_id
        assert item.ratio.high == pytest.approx(central * 2), item.movement_id


def test_unsignalised_u_turns_are_not_estimated():
    """
    They leave the approach on their own connector before the stop-bar
    lanes, so there are no parallel counted lanes to compare with.
    """

    movements = {item.movement_id for item in load_share_config(DEFAULT_SHARE_CONFIG_PATH).shares}

    assert not movements & {"MOV_W_W_UTURN", "MOV_S_S_UTURN", "MOV_N_N_UTURN"}

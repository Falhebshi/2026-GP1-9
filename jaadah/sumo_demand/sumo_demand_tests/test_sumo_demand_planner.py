from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.scenario import Scenario, SimulationConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import (
    DemandPlanningError,
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    plan_departures,
    record_random_generator,
    stop_line_edges,
    vehicle_id,
)

RIYADH = timezone(timedelta(hours=3))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
NETWORK_PATH = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"


def at(hour, minute):
    return datetime(2026, 10, 20, hour, minute, tzinfo=RIYADH)


# ============================================================
# HELPERS
# ============================================================

ROUTES = {
    "MOV_A": ["edge_a1", "edge_a2"],
    "MOV_B": ["edge_b1", "edge_b2"],
    "MOV_NO_DETECTOR": ["edge_c1", "edge_c2"],
}
EXPECTED = frozenset({"MOV_A", "MOV_B"})
FREE_FLOW = {"MOV_A": 0.0, "MOV_B": 57.0}

# Analysis 08:00-08:15 with 15 min warm-up and clearance:
# run 07:45-08:30, SUMO seconds 0-2700, intervals 07:45, 08:00, 08:15.
COUNTS = {
    ("MOV_A", at(7, 45)): 5, ("MOV_A", at(8, 0)): 30, ("MOV_A", at(8, 15)): 0,
    ("MOV_B", at(7, 45)): 20, ("MOV_B", at(8, 0)): 1, ("MOV_B", at(8, 15)): 12,
}


def make_window(start=at(8, 0), end=at(8, 15), warmup=900, clearance=900, total=None):
    scenario = Scenario(
        scenario_id="SCN_TEST",
        intersection_id="INT_001",
        time_context="historical",
        control_mode="baseline",
        start_time=start,
        end_time=end,
    )
    config = SimulationConfig(
        simulation_duration_s=total,
        warmup_duration_s=warmup,
        clearance_duration_s=clearance,
    )
    return build_run_window(scenario, config)


def demand_id_of(movement_id, start):
    return f"DEM_{movement_id}_{start:%H%M}"


def demand(movement_id, start, count, minutes=15, demand_id=None):
    return SimulationDemand(
        demand_id=demand_id or demand_id_of(movement_id, start),
        interval_start=start,
        interval_end=start + timedelta(minutes=minutes),
        movement_id=movement_id,
        vehicle_count=count,
        source="synthetic",
        source_observation_ids=[f"OBS_{movement_id}_{start:%H%M}"],
    )


def all_demands(counts=COUNTS):
    return [demand(movement_id, start, count) for (movement_id, start), count in counts.items()]


def plan(demands=None, seed=42):
    return plan_departures(
        all_demands() if demands is None else demands,
        window=make_window(),
        routes=ROUTES,
        expected_movements=EXPECTED,
        free_flow_s=FREE_FLOW,
        seed=seed,
    )


def departures_of(result, movement_id, start):
    """The cars of one record, found through demand_id."""

    wanted = demand_id_of(movement_id, start)
    return [item for item in result.departures if item.demand_id == wanted]


def problems_of(exc_info):
    return "\n".join(exc_info.value.problems)


# ============================================================
# RUN WINDOW
# ============================================================

def test_window_epoch_is_analysis_start_minus_warmup():
    window = make_window(start=at(8, 0), end=at(9, 0))

    assert window.epoch == at(7, 45)
    assert window.run_end == at(9, 15)
    assert window.duration_s == 5400
    assert window.to_simulation_seconds(at(8, 0)) == 900
    assert window.to_simulation_seconds(at(9, 0)) == 4500


def test_window_lists_warmup_analysis_and_clearance_intervals():
    window = make_window(start=at(8, 0), end=at(9, 0))

    # 07:45-09:15 is 5400 s = 6 intervals: 1 warm-up, 4 analysis, 1 clearance.
    assert window.interval_starts() == [
        at(7, 45), at(8, 0), at(8, 15), at(8, 30), at(8, 45), at(9, 0),
    ]


def test_window_accepts_matching_total_duration():
    assert make_window(end=at(9, 0), total=5400).duration_s == 5400


@pytest.mark.parametrize("kwargs, message", [
    ({"warmup": 600}, "warm-up duration must be a whole number"),
    ({"clearance": 1000}, "clearance duration must be a whole number"),
    ({"end": at(8, 50)}, "analysis period must be a whole number"),
    ({"start": at(8, 5), "end": at(8, 20)}, "analysis start must fall on a quarter hour"),
    ({"end": at(9, 0), "total": 3600}, "simulation_duration_s must equal"),
])
def test_window_rejects_invalid_timing(kwargs, message):
    with pytest.raises(DemandPlanningError) as exc:
        make_window(**kwargs)

    assert message in problems_of(exc)


def test_window_requires_end_time():
    scenario = Scenario(
        scenario_id="SCN_NOW",
        intersection_id="INT_001",
        time_context="current",
        control_mode="baseline",
        start_time=at(8, 0),
    )
    config = SimulationConfig(warmup_duration_s=900, clearance_duration_s=900)

    with pytest.raises(DemandPlanningError) as exc:
        build_run_window(scenario, config)

    assert "end_time" in problems_of(exc)


# ============================================================
# COUNTS
# ============================================================

def test_every_record_produces_exactly_its_vehicle_count():
    result = plan()
    counted = Counter(item.demand_id for item in result.departures)

    for (movement_id, start), count in COUNTS.items():
        assert counted[demand_id_of(movement_id, start)] == count
    assert len(result.departures) == sum(COUNTS.values()) == 68


def test_zero_count_produces_no_vehicles_and_one_count_one_vehicle():
    result = plan()

    assert departures_of(result, "MOV_A", at(8, 15)) == []
    assert len(departures_of(result, "MOV_B", at(8, 0))) == 1


# ============================================================
# TIMING
# ============================================================

def test_departures_without_shift_stay_inside_their_interval():
    # MOV_A, 08:00-08:15 is SUMO seconds 900-1800; free-flow time 0 s.
    times = [item.depart_s for item in departures_of(plan(), "MOV_A", at(8, 0))]

    assert all(900 <= value < 1800 for value in times)


def test_departures_are_shifted_by_free_flow_time():
    # MOV_B, 08:15-08:30 is SUMO 1800-2700; with 57 s free-flow the cars
    # depart in [1743, 2643) and reach the stop line in [1800, 2700).
    items = departures_of(plan(), "MOV_B", at(8, 15))

    assert len(items) == 12
    assert all(1743 <= item.depart_s < 2643 for item in items)
    assert all(1800 <= item.depart_s + FREE_FLOW["MOV_B"] < 2700 for item in items)


def test_first_warmup_interval_is_not_shifted_before_second_zero():
    # MOV_B, 07:45-08:00 is SUMO 0-900; shifted window would start at -57 s,
    # so departures are drawn on [0, 843).
    times = [item.depart_s for item in departures_of(plan(), "MOV_B", at(7, 45))]

    assert len(times) == 20
    assert all(0 <= value < 843 for value in times)


def test_departure_times_are_whole_hundredths_of_a_second():
    for item in plan().departures:
        assert round(item.depart_s * 100) == pytest.approx(item.depart_s * 100, abs=1e-6)


def test_departures_are_sorted_by_time():
    result = plan()
    keys = [(item.depart_s, item.vehicle_id) for item in result.departures]

    assert keys == sorted(keys)


# ============================================================
# REPRODUCIBILITY
# ============================================================

def test_same_seed_gives_identical_plan():
    assert plan(seed=42) == plan(seed=42)


def test_different_seed_changes_departure_times():
    first = [item.depart_s for item in plan(seed=42).departures]
    second = [item.depart_s for item in plan(seed=43).departures]

    assert first != second


def test_changing_one_record_does_not_change_other_records():
    changed = dict(COUNTS)
    changed[("MOV_B", at(8, 0))] = 25

    before = departures_of(plan(), "MOV_A", at(8, 0))
    after = departures_of(plan(all_demands(changed)), "MOV_A", at(8, 0))

    assert before == after


def test_record_generator_is_stable_across_calls():
    first = record_random_generator(42, "MOV_A", at(8, 0)).random()
    second = record_random_generator(42, "MOV_A", at(8, 0)).random()

    assert first == second


# ============================================================
# IDENTIFIERS AND PROVENANCE
# ============================================================

def test_vehicle_id_format():
    assert vehicle_id("MOV_E_W", at(8, 15), 7) == "MOV_E_W__20261020T0815__007"


def test_vehicle_ids_are_unique_and_keep_their_demand_record():
    result = plan()
    ids = [item.vehicle_id for item in result.departures]

    assert len(ids) == len(set(ids))
    first = departures_of(result, "MOV_A", at(8, 0))
    assert [item.vehicle_id for item in first][:2] == [
        "MOV_A__20261020T0815__001",
        "MOV_A__20261020T0815__002",
    ]
    assert {item.demand_id for item in first} == {"DEM_MOV_A_0800"}


def test_planned_car_stores_only_its_own_facts():
    car = plan().departures[0]

    assert set(car.model_dump()) == {"vehicle_id", "demand_id", "depart_s"}
    assert set(plan().model_dump()) == {"departures"}


# ============================================================
# INVALID INPUT
# ============================================================

def test_missing_record_is_an_error_listing_the_gap():
    counts = dict(COUNTS)
    del counts[("MOV_B", at(8, 15))]

    with pytest.raises(DemandPlanningError) as exc:
        plan(all_demands(counts))

    assert problems_of(exc) == (
        "missing demand: MOV_B 2026-10-20T08:15:00+03:00 - 2026-10-20T08:30:00+03:00"
    )


@pytest.mark.parametrize("extra, message", [
    (demand("MOV_X", at(8, 0), 3), "unknown movement"),
    (demand("MOV_NO_DETECTOR", at(8, 0), 3), "movement receives no detector demand"),
    (demand("MOV_A", at(8, 0), 3, demand_id="DEM_COPY"), "duplicate record"),
    (demand("MOV_A", at(8, 30), 3), "outside the run window"),
    (demand("MOV_A", at(8, 5), 3), "not on the 15-minute grid"),
])
def test_invalid_record_is_rejected(extra, message):
    with pytest.raises(DemandPlanningError) as exc:
        plan(all_demands() + [extra])

    assert message in problems_of(exc)


def test_interval_that_is_not_15_minutes_is_rejected():
    demands = [item for item in all_demands() if item.demand_id != "DEM_MOV_A_0800"]
    demands.append(demand("MOV_A", at(8, 0), 30, minutes=30))

    with pytest.raises(DemandPlanningError) as exc:
        plan(demands)

    assert "interval is not 15 minutes" in problems_of(exc)


def test_all_problems_are_reported_together():
    counts = dict(COUNTS)
    del counts[("MOV_A", at(7, 45))]

    with pytest.raises(DemandPlanningError) as exc:
        plan(all_demands(counts) + [demand("MOV_X", at(8, 0), 1)])

    assert len(exc.value.problems) == 2


@pytest.mark.parametrize("seed", [-1, True])
def test_invalid_seed_is_rejected(seed):
    with pytest.raises(DemandPlanningError):
        plan(seed=seed)


# ============================================================
# FREE-FLOW TIMES
# ============================================================

SMALL_NETWORK = """<net>
    <edge id="e_in" from="n0" to="n1">
        <lane id="e_in_0" index="0" speed="10.00" length="100.00"/>
    </edge>
    <edge id="e_stop" from="n1" to="n2">
        <lane id="e_stop_0" index="0" speed="25.00" length="50.00"/>
        <lane id="e_stop_1" index="1" speed="20.00" length="50.00"/>
    </edge>
    <edge id="e_out" from="n2" to="n3">
        <lane id="e_out_0" index="0" speed="25.00" length="400.00"/>
    </edge>
</net>"""


def small_config():
    return NetworkMappingConfig.model_validate({
        "schema_version": "2.0",
        "mapping_version": "test",
        "network": {"version": "small", "path": "small.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "approach_mappings": [{
            "approach_id": "APP_E", "intersection_id": "INT_001", "approach_side": "east",
        }],
        "approach_lanes": [{
            "lane_id": "LANE_E_1", "approach_id": "APP_E", "lane_index": 1,
            "served_movement_ids": ["MOV_E_W"], "lane_width_m": 3.2,
        }],
        "lane_mappings": [{"lane_id": "LANE_E_1", "sumo_lane_ids": ["e_stop_1"]}],
        "movement_mappings": [
            {
                "movement_id": "MOV_E_W", "intersection_id": "INT_001",
                "approach_id": "APP_E", "sumo_route_edge_ids": ["e_in", "e_stop", "e_out"],
                "signal_controlled": False,
            },
            {
                "movement_id": "MOV_E_E_UTURN", "intersection_id": "INT_001",
                "approach_id": "APP_E", "sumo_route_edge_ids": ["e_in", "e_out"],
                "signal_controlled": False,
            },
        ],
    })


def test_free_flow_time_sums_edges_up_to_the_stop_line(tmp_path):
    # 100 m at 10 m/s + 50 m at 25 m/s (highest lane speed) = 10 + 2 = 12 s.
    # The edge after the stop line is not included.
    network = tmp_path / "small.net.xml"
    network.write_text(SMALL_NETWORK, encoding="utf-8")

    times = compute_free_flow_times(small_config(), network)

    assert times == {"MOV_E_W": 12.0}


def test_stop_line_edge_is_the_edge_of_the_last_lane_segment(tmp_path):
    # LANE_E_1 ends on lane e_stop_1, so MOV_E_W's stop line is the end of
    # e_stop; the U-turn is served by no lane and has no stop line.
    network = tmp_path / "small.net.xml"
    network.write_text(SMALL_NETWORK, encoding="utf-8")

    assert stop_line_edges(small_config(), network) == {"MOV_E_W": "e_stop"}


def test_free_flow_rejects_stop_line_edge_not_on_route(tmp_path):
    network = tmp_path / "small.net.xml"
    network.write_text(SMALL_NETWORK, encoding="utf-8")
    config = small_config()
    config.movement_mappings[0].sumo_route_edge_ids = ["e_in", "e_out"]

    with pytest.raises(DemandPlanningError) as exc:
        compute_free_flow_times(config, network)

    assert "is not on its route" in problems_of(exc)


# ============================================================
# STUDY-AREA MAPPING AND NETWORK
# ============================================================

needs_study_area = pytest.mark.skipif(
    not (MAPPING_PATH.is_file() and NETWORK_PATH.is_file()),
    reason="study-area mapping or network not available",
)


@needs_study_area
def test_study_area_has_nine_demand_movements():
    config = load_network_mappings(MAPPING_PATH)

    assert demand_movement_ids(config) == {
        "MOV_E_W", "MOV_E_S", "MOV_W_E", "MOV_W_N", "MOV_N_E", "MOV_S_W",
        "MOV_W_S_SLIP", "MOV_N_W_SLIP", "MOV_S_E_BYPASS",
    }


@needs_study_area
def test_study_area_free_flow_times():
    config = load_network_mappings(MAPPING_PATH)

    times = compute_free_flow_times(config, NETWORK_PATH)

    assert set(times) == demand_movement_ids(config)
    expected = {
        "MOV_W_E": 27.6, "MOV_W_N": 27.6, "MOV_W_S_SLIP": 29.2,
        "MOV_E_W": 33, "MOV_E_S": 33, "MOV_N_E": 45,
        "MOV_N_W_SLIP": 47, "MOV_S_W": 50, "MOV_S_E_BYPASS": 57,
    }
    for movement_id, seconds in expected.items():
        assert times[movement_id] == pytest.approx(seconds, abs=0.5)

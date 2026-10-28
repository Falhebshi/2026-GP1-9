import statistics
from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics.kpi import comparison
from backend.analytics.kpi.comparison import (
    NO_PAIR_VALUE_REASON,
    ComparisonSpec,
    KpiSpec,
    RunValue,
    check_replication_set,
    combine_runs,
    combined_origins,
    compare_hcm_level_of_service,
    compare_level_of_service,
    compare_runs,
    compare_single,
    input_origins,
    measured_level_of_service,
    queue_from_lanes,
    single_result,
)
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.kpi_tests.test_capacity import LANES, MOVEMENT_MODELS, program
from jaadah.models.kpis import (
    InputOrigin,
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    LevelOfServiceGrade,
    UncontrolledMovements,
)
from jaadah.models.network import ApproachLane, Movement
from jaadah.models.scenario import ReplicationSet, Scenario, SimulationRun, TimeContext
from jaadah.models.signals import SignalProgram
from jaadah.models.traffic import SimulationDemand


RIYADH = timezone(timedelta(hours=3))
INTERVAL = AnalysisInterval(
    datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
    datetime(2026, 10, 14, 8, 15, tzinfo=RIYADH),
)

OK = KpiStatus.OK
NA = KpiStatus.NOT_APPLICABLE
UNAVAILABLE = KpiStatus.UNAVAILABLE

SIM_ORIGINS = [InputOrigin.MODELLED_ASSUMPTION, InputOrigin.SIMULATED]


def ok(value):
    return RunValue(OK, value)


def delay_spec(**overrides):
    values = dict(
        kpi=KpiName.CONTROL_DELAY,
        level=KpiLevel.MOVEMENT,
        element_id="MOV_E_T",
        unit=KpiUnit.SECONDS_PER_VEHICLE,
        method=KpiMethod.SIMULATION,
        interval=INTERVAL,
        scenario_id="SCN_BASE",
        input_origins=SIM_ORIGINS,
    )
    values.update(overrides)
    return KpiSpec(**values)


# ============================================================
# COMBINING RUNS (questions 1-3)
# ============================================================

def test_mean_and_sample_standard_deviation():
    """30, 34, 38 s: mean 34, SD sqrt(32 / 2) = 4.0 (n - 1)."""

    result = combine_runs(delay_spec(), {"R1": ok(30), "R2": ok(34), "R3": ok(38)})

    assert result.value == pytest.approx(34)
    assert result.standard_deviation == pytest.approx(4.0)
    assert result.run_ids == ["R1", "R2", "R3"]


def test_one_run_has_no_standard_deviation():
    result = combine_runs(delay_spec(), {"R1": ok(30)})

    assert result.value == 30
    assert result.standard_deviation is None


def test_one_unavailable_run_makes_the_result_unavailable():
    values = {f"R{i}": ok(30) for i in range(1, 10)}
    values["R10"] = RunValue(UNAVAILABLE, None, "incomplete passages")

    result = combine_runs(delay_spec(), values)

    assert result.status == UNAVAILABLE
    assert result.reason == "incomplete passages; unavailable in 1 of 10 runs"
    assert result.value is None
    assert len(result.run_ids) == 10  # every run that was looked at


def test_unavailable_runs_with_different_reasons_give_the_count_only():
    values = {
        "R1": ok(30),
        "R2": RunValue(UNAVAILABLE, None, "incomplete passages"),
        "R3": RunValue(UNAVAILABLE, None, "queue reached the zone end"),
    }

    result = combine_runs(delay_spec(), values)

    assert result.reason == "unavailable in 2 of 3 runs"


def test_runs_without_cars_are_left_out():
    """Not 0: an average over no cars does not exist."""

    values = {"R1": ok(3), "R2": ok(5), "R3": RunValue(NA, None, "no arrivals")}

    result = combine_runs(delay_spec(), values)

    assert result.value == pytest.approx(4)
    assert result.run_ids == ["R1", "R2"]


def test_no_run_with_cars_is_not_applicable():
    values = {"R1": RunValue(NA, None, "no arrivals"), "R2": RunValue(NA, None, "no arrivals")}

    result = combine_runs(delay_spec(), values)

    assert result.status == NA
    assert result.reason == "no arrivals"


def test_no_runs_rejected():
    with pytest.raises(ValueError, match="at least one run"):
        combine_runs(delay_spec(), {})


def test_tag_kept_on_combined_approach_result():
    spec = delay_spec(
        level=KpiLevel.APPROACH,
        element_id="APP_S",
        uncontrolled_movements=UncontrolledMovements.INCLUDED,
    )

    result = combine_runs(spec, {"R1": ok(20), "R2": ok(22)})

    assert result.uncontrolled_movements == UncontrolledMovements.INCLUDED


def test_measured_level_of_service_from_mean_delay():
    """Seeds 30 and 40 s: mean 35 s, LOS C (35 is on the C/D limit)."""

    delay = combine_runs(delay_spec(), {"R1": ok(30), "R2": ok(40)})
    spec = delay_spec(kpi=KpiName.LEVEL_OF_SERVICE, unit=KpiUnit.GRADE)

    los = measured_level_of_service(spec, delay)

    assert los.los_grade == LevelOfServiceGrade.C
    assert los.run_ids == ["R1", "R2"]
    assert los.standard_deviation is None


def test_measured_level_of_service_follows_missing_delay():
    delay = combine_runs(delay_spec(), {"R1": RunValue(UNAVAILABLE, None)})
    spec = delay_spec(kpi=KpiName.LEVEL_OF_SERVICE, unit=KpiUnit.GRADE)

    assert measured_level_of_service(spec, delay).status == UNAVAILABLE


def test_hcm_result_has_no_runs():
    spec = delay_spec(
        method=KpiMethod.HCM,
        level=KpiLevel.LANE_GROUP,
        element_id="APP_E_T",
        input_origins=[InputOrigin.MODELLED_ASSUMPTION],
    )

    result = single_result(spec, OK, 41.2)

    assert result.run_ids == []
    assert result.value == 41.2


# ============================================================
# QUEUES: LANES FIRST (question 9)
# ============================================================

QUEUE_LANES = [lane for lane in LANES if lane.approach_id in {"APP_E", "APP_S"}]


def lane_result(lane_id, runs):
    spec = KpiSpec(
        kpi=KpiName.QUEUE_LENGTH,
        level=KpiLevel.LANE,
        element_id=lane_id,
        unit=KpiUnit.METRES,
        method=KpiMethod.SIMULATION,
        interval=INTERVAL,
        scenario_id="SCN_BASE",
        input_origins=SIM_ORIGINS,
    )
    return combine_runs(spec, {f"R{i}": ok(v) for i, v in enumerate(runs, start=1)})


def lane_results(**overrides):
    runs = {lane.lane_id: [20, 20, 20] for lane in QUEUE_LANES}
    runs.update(overrides)
    return {lane_id: lane_result(lane_id, values) for lane_id, values in runs.items()}


def test_lanes_are_averaged_first_then_the_longest_is_taken():
    """
    The worked example: lane 3 runs 80, 50, 70 (mean 66.7); lane 4 runs
    60, 90, 60 (mean 70). East through = 70 m on lane 4, not 80 m.
    """

    results = lane_results(LANE_E_3=[80, 50, 70], LANE_E_4=[60, 90, 60])

    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)
    east_through = out[("movement", "MOV_E_T")]

    assert east_through.result.value == pytest.approx(70)
    assert east_through.lane_id == "LANE_E_4"
    assert east_through.result.standard_deviation == pytest.approx(
        statistics.stdev([60, 90, 60])
    )


def test_movement_value_equals_its_lane_result():
    """Requirement 36: the same value in every view."""

    results = lane_results(LANE_E_4=[60, 90, 60])
    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)

    assert out[("movement", "MOV_E_T")].result.value == results["LANE_E_4"].value


def test_shared_lane_is_named_on_the_movement():
    results = lane_results(LANE_E_2=[90, 90, 90])
    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)

    left = out[("movement", "MOV_E_L")].result

    assert left.measured_on_lane_id == "LANE_E_2"
    assert left.is_shared_value


def test_single_movement_lane_is_not_marked_shared():
    results = lane_results(LANE_E_4=[90, 90, 90])
    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)

    assert out[("movement", "MOV_E_T")].result.measured_on_lane_id is None


def test_approach_and_intersection_take_the_longest_lane():
    results = lane_results(LANE_S_2=[100, 100, 100])
    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)

    assert out[("approach", "APP_S")].lane_id == "LANE_S_2"
    assert out[("intersection", "INT_01")].result.value == pytest.approx(100)
    assert out[("approach", "APP_S")].result.measured_on_lane_id is None


def test_unavailable_lane_makes_its_elements_unavailable():
    results = lane_results()
    spec = KpiSpec(
        kpi=KpiName.QUEUE_LENGTH, level=KpiLevel.LANE, element_id="LANE_S_1",
        unit=KpiUnit.METRES, method=KpiMethod.SIMULATION, interval=INTERVAL,
        scenario_id="SCN_BASE", input_origins=SIM_ORIGINS,
    )
    results["LANE_S_1"] = combine_runs(spec, {"R1": RunValue(UNAVAILABLE, None)})

    out = queue_from_lanes(results, QUEUE_LANES, MOVEMENT_MODELS)

    assert out[("approach", "APP_S")].result.status == UNAVAILABLE
    assert out[("approach", "APP_E")].result.status == OK
    assert out[("intersection", "INT_01")].result.status == UNAVAILABLE


def approach_result(approach_id, runs, status=None, reason=None):
    spec = KpiSpec(
        kpi=KpiName.QUEUE_LENGTH, level=KpiLevel.APPROACH, element_id=approach_id,
        unit=KpiUnit.METRES, method=KpiMethod.SIMULATION, interval=INTERVAL,
        scenario_id="SCN_BASE", input_origins=SIM_ORIGINS,
    )
    if status == UNAVAILABLE:
        return combine_runs(spec, {"R1": RunValue(UNAVAILABLE, None, reason)})
    return combine_runs(spec, {f"R{i}": ok(v) for i, v in enumerate(runs, start=1)})


def approach_results(**overrides):
    runs = {"APP_E": [150, 150, 150], "APP_S": [90, 90, 90], **overrides}
    return {a: v if not isinstance(v, list) else approach_result(a, v) for a, v in runs.items()}


def test_approach_queue_is_its_full_zone_queue_combined_over_the_runs():
    out = queue_from_lanes(
        lane_results(LANE_E_4=[100, 100, 100]), QUEUE_LANES, MOVEMENT_MODELS,
        approach_results=approach_results(APP_E=[140, 160, 150]),
    )

    east = out[("approach", "APP_E")]
    assert east.result.value == pytest.approx(150)
    assert east.lane_id is None
    assert east.result.standard_deviation == pytest.approx(10)
    assert out[("movement", "MOV_E_T")].result.value == pytest.approx(100)


def test_approach_takes_a_longer_slip_lane_and_intersection_the_longest_approach():
    """LANE_S_2 stands in for a slip lane here."""

    out = queue_from_lanes(
        lane_results(LANE_S_2=[200, 200, 200]), QUEUE_LANES, MOVEMENT_MODELS,
        approach_results=approach_results(), slip_lane_ids={"LANE_S_2"},
    )

    assert out[("approach", "APP_S")].lane_id == "LANE_S_2"
    assert out[("approach", "APP_S")].result.value == pytest.approx(200)
    assert out[("intersection", "INT_01")].result.value == pytest.approx(200)
    assert out[("intersection", "INT_01")].lane_id == "LANE_S_2"


def test_unavailable_approach_queue_keeps_its_reason():
    reason = "the queue reached the end of the measurement zone"
    results = approach_results(APP_E=approach_result("APP_E", [], UNAVAILABLE, reason))

    out = queue_from_lanes(
        lane_results(), QUEUE_LANES, MOVEMENT_MODELS, approach_results=results
    )

    assert out[("approach", "APP_E")].result.status == UNAVAILABLE
    assert out[("approach", "APP_E")].result.reason == f"{reason}; unavailable in 1 of 1 runs"
    assert out[("intersection", "INT_01")].result.reason == out[("approach", "APP_E")].result.reason
    assert out[("approach", "APP_S")].result.status == OK


def test_slip_approaches_are_tagged():
    out = queue_from_lanes(
        lane_results(), QUEUE_LANES, MOVEMENT_MODELS, uncontrolled_by_approach={"APP_S"}
    )

    assert out[("approach", "APP_S")].result.uncontrolled_movements == UncontrolledMovements.INCLUDED
    assert out[("approach", "APP_E")].result.uncontrolled_movements is None
    assert out[("intersection", "INT_01")].result.uncontrolled_movements == UncontrolledMovements.INCLUDED


# ============================================================
# INPUT ORIGINS (question 8; demand markers)
# ============================================================

NEXT_INTERVAL = AnalysisInterval(INTERVAL.end, INTERVAL.end + timedelta(minutes=15))


def demand(movement_id, source="rcrc", interval=INTERVAL, allocated=False, imputed=False):
    """One demand record; optionally split from a shared lane or estimated."""

    values = dict(
        demand_id=f"DEM_{movement_id}_{interval.start:%H%M}",
        interval_start=interval.start,
        interval_end=interval.end,
        movement_id=movement_id,
        vehicle_count=100,
        source=source,
        source_observation_ids=["OBS_1", "OBS_2"],
    )
    if allocated:
        values["allocated_observation_ids"] = ["OBS_2"]
    if imputed:
        values["imputed_detectors"] = [
            {"site_id": "9", "detector_id": "6", "method": "neighbour_regression"}
        ]
    return SimulationDemand(**values)


def origins(demands, approach_id=None, method=KpiMethod.SIMULATION, interval=INTERVAL, **program_args):
    return input_origins(
        method, demands, program(**program_args), MOVEMENT_MODELS, interval, approach_id
    )


@pytest.fixture
def surveyed_geometry(monkeypatch):
    """
    Lane geometry is a modelled assumption today, which already puts
    modelled_assumption on every result. Treating it as observed shows
    what the demand markers add on their own.
    """

    monkeypatch.setattr(comparison, "GEOMETRY_INPUT_ORIGIN", InputOrigin.OBSERVED)


def test_synthetic_demand_simulation_origins():
    result = origins([demand("MOV_E_T", source="synthetic")], "APP_E")

    assert result == [InputOrigin.MODELLED_ASSUMPTION, InputOrigin.SIMULATED]


def test_rcrc_demand_with_observed_signal():
    result = origins([demand("MOV_E_T")], "APP_E", source="observed")

    # geometry stays a modelled assumption
    assert result == [
        InputOrigin.OBSERVED,
        InputOrigin.MODELLED_ASSUMPTION,
        InputOrigin.SIMULATED,
    ]


def test_measured_rcrc_demand_is_observed(surveyed_geometry):
    result = origins([demand("MOV_E_T")], "APP_E", source="observed")

    assert result == [InputOrigin.OBSERVED, InputOrigin.SIMULATED]


@pytest.mark.parametrize("marker", ["allocated", "imputed"])
def test_allocated_or_imputed_demand_is_a_modelled_assumption(surveyed_geometry, marker):
    """Whatever the source: part of the count is not measured."""

    result = origins([demand("MOV_E_L", **{marker: True})], "APP_E", source="observed")

    assert InputOrigin.MODELLED_ASSUMPTION in result
    assert InputOrigin.OBSERVED in result


def test_marker_stays_on_its_own_approach(surveyed_geometry):
    """East was split; North was measured in full."""

    demands = [demand("MOV_E_L", allocated=True), demand("MOV_E_T"), demand("MOV_N_L")]

    east = origins(demands, "APP_E", source="observed")
    north = origins(demands, "APP_N", source="observed")

    assert InputOrigin.MODELLED_ASSUMPTION in east
    assert north == [InputOrigin.OBSERVED, InputOrigin.SIMULATED]


def test_intersection_uses_every_approach(surveyed_geometry):
    demands = [demand("MOV_E_L", allocated=True), demand("MOV_N_L")]

    result = origins(demands, None, source="observed")

    assert InputOrigin.MODELLED_ASSUMPTION in result


def test_marker_stays_in_its_own_interval(surveyed_geometry):
    """A split at 08:15 does not change the 08:00 result."""

    demands = [demand("MOV_E_T"), demand("MOV_E_L", interval=NEXT_INTERVAL, allocated=True)]

    result = origins(demands, "APP_E", source="observed")

    assert result == [InputOrigin.OBSERVED, InputOrigin.SIMULATED]


def test_longer_result_uses_every_overlapping_interval(surveyed_geometry):
    """A whole-period result (08:00-08:30) sees the 08:15 split."""

    demands = [demand("MOV_E_T"), demand("MOV_E_L", interval=NEXT_INTERVAL, allocated=True)]
    period = AnalysisInterval(INTERVAL.start, NEXT_INTERVAL.end)

    result = origins(demands, "APP_E", interval=period, source="observed")

    assert InputOrigin.MODELLED_ASSUMPTION in result


def test_approach_without_demand_records_adds_no_demand_origin(surveyed_geometry):
    result = origins([demand("MOV_N_L")], "APP_E", source="observed")

    assert result == [InputOrigin.OBSERVED, InputOrigin.SIMULATED]


def test_unknown_movement_rejected():
    with pytest.raises(ValueError, match="unknown movement MOV_X"):
        origins([demand("MOV_X")], "APP_E")


def test_hcm_origins_never_include_simulated():
    result = origins([demand("MOV_E_T")], "APP_E", method=KpiMethod.HCM)

    assert InputOrigin.SIMULATED not in result
    assert InputOrigin.MODELLED_ASSUMPTION in result


def test_comparison_origins_combine_both_sides():
    assert combined_origins(
        [InputOrigin.OBSERVED, InputOrigin.SIMULATED],
        [InputOrigin.MODELLED_ASSUMPTION, InputOrigin.SIMULATED],
    ) == [InputOrigin.OBSERVED, InputOrigin.MODELLED_ASSUMPTION, InputOrigin.SIMULATED]


# ============================================================
# CHECKING THE RUNS (question 7)
# ============================================================

def run(run_id, scenario_id, seed, **overrides):
    values = dict(
        run_id=run_id,
        scenario_id=scenario_id,
        random_seed=seed,
        network_version="net-1",
        sumo_version="1.27",
        step_length_s=0.2,
        mapping_version="2.2-movement-attributes",
        demand_sha256="d" * 64,
        route_file_sha256=f"{seed:064x}",
        started_at=datetime(2026, 10, 14, 7, 0, tzinfo=RIYADH),
        status="completed",
    )
    values.update(overrides)
    return SimulationRun(**values)


SCENARIOS = {
    "SCN_BASE": Scenario(
        scenario_id="SCN_BASE", intersection_id="INT_01", time_context="current",
        control_mode="baseline", start_time=datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
    ),
    "SCN_INT": Scenario(
        scenario_id="SCN_INT", intersection_id="INT_01", time_context="current",
        control_mode="intervention", start_time=datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
        reference_scenario_id="SCN_BASE",
    ),
}

SET = ReplicationSet(
    replication_set_id="RS_1",
    baseline_scenario_id="SCN_BASE",
    intervention_scenario_id="SCN_INT",
    pairs=[
        {"baseline_run_id": f"B{i}", "intervention_run_id": f"I{i}"} for i in (1, 2, 3)
    ],
)


def runs(**overrides):
    values = {}
    for i, seed in zip((1, 2, 3), (42, 73, 105)):
        values[f"B{i}"] = run(f"B{i}", "SCN_BASE", seed)
        values[f"I{i}"] = run(f"I{i}", "SCN_INT", seed)
    values.update(overrides)
    return values


def test_matching_runs_pass():
    check_replication_set(SET, runs(), SCENARIOS)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"I2": run("I2", "SCN_INT", 74)}, "pair 2 used seeds 73 and 74"),
        ({"B3": run("B3", "SCN_BASE", 42), "I3": run("I3", "SCN_INT", 42)}, "different seed"),
        ({"I1": run("I1", "SCN_INT", 42, status="failed")}, "not completed"),
        ({"I1": run("I1", "SCN_BASE", 42)}, "belongs to scenario SCN_BASE"),
        ({"I1": run("I1", "SCN_INT", 42, network_version="net-2")}, "network_version"),
        ({"I1": run("I1", "SCN_INT", 42, sumo_version="1.26")}, "sumo_version"),
        ({"I1": run("I1", "SCN_INT", 42, step_length_s=0.1)}, "step_length_s"),
    ],
)
def test_mismatched_runs_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        check_replication_set(SET, runs(**overrides), SCENARIOS)


def test_missing_run_rejected():
    values = runs()
    del values["I3"]

    with pytest.raises(ValueError, match="run I3 is missing"):
        check_replication_set(SET, values, SCENARIOS)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"I2": run("I2", "SCN_INT", 73, mapping_version="2.1-lanes")}, "mapping_version"),
        ({"I2": run("I2", "SCN_INT", 73, demand_sha256="e" * 64)}, "demand_sha256"),
        ({"I2": run("I2", "SCN_INT", 73, route_file_sha256="f" * 64)}, "pair 2 used different route files"),
    ],
)
def test_runs_must_use_the_same_inputs(overrides, message):
    with pytest.raises(ValueError, match=message):
        check_replication_set(SET, runs(**overrides), SCENARIOS)


def test_route_files_differ_between_pairs():
    """Different seeds plan different departures: only pairs must match."""

    values = runs()

    assert values["B1"].route_file_sha256 != values["B2"].route_file_sha256
    check_replication_set(SET, values, SCENARIOS)


@pytest.mark.parametrize(
    "update, field",
    [
        ({"start_time": datetime(2026, 10, 14, 17, 0, tzinfo=RIYADH)}, "start_time"),
        ({"end_time": datetime(2026, 10, 14, 9, 0, tzinfo=RIYADH)}, "end_time"),
        ({"time_context": TimeContext.FORECAST}, "time_context"),
    ],
)
def test_scenarios_must_cover_the_same_time_window(update, field):
    """A 08:00 baseline cannot be compared with a 17:00 intervention."""

    scenarios = {**SCENARIOS, "SCN_INT": SCENARIOS["SCN_INT"].model_copy(update=update)}

    with pytest.raises(ValueError, match=f"the scenarios differ in {field}"):
        check_replication_set(SET, runs(), scenarios)


def test_intervention_must_reference_the_baseline():
    scenarios = {
        **SCENARIOS,
        "SCN_INT": SCENARIOS["SCN_INT"].model_copy(update={"reference_scenario_id": "SCN_X"}),
    }

    with pytest.raises(ValueError, match="does not reference"):
        check_replication_set(SET, runs(), scenarios)


# ============================================================
# COMPARING (question 4)
# ============================================================

def comparison_spec(**overrides):
    values = dict(
        kpi=KpiName.CONTROL_DELAY,
        level=KpiLevel.MOVEMENT,
        element_id="MOV_E_T",
        unit=KpiUnit.SECONDS_PER_VEHICLE,
        method=KpiMethod.SIMULATION,
        interval=INTERVAL,
        baseline_scenario_id="SCN_BASE",
        intervention_scenario_id="SCN_INT",
        input_origins=SIM_ORIGINS,
        replication_set_id="RS_1",
    )
    values.update(overrides)
    return ComparisonSpec(**values)


BASELINE = {"B1": ok(40), "B2": ok(50), "B3": ok(60)}
INTERVENTION = {"I1": ok(35), "I2": ok(44), "I3": ok(56)}


def test_paired_comparison_by_hand():
    """The worked example: differences -5, -6, -4 -> -5 +/- 1 s, -10 %."""

    result = compare_runs(comparison_spec(), SET, BASELINE, INTERVENTION)

    assert result.mean_change == pytest.approx(-5)
    assert result.standard_deviation == pytest.approx(1)
    assert result.baseline_mean == pytest.approx(50)
    assert result.percent_change == pytest.approx(-10)
    assert len(result.used_pairs) == 3


def test_unavailable_pair_makes_the_comparison_unavailable():
    intervention = {**INTERVENTION, "I2": RunValue(UNAVAILABLE, None)}

    result = compare_runs(comparison_spec(), SET, BASELINE, intervention)

    assert result.status == UNAVAILABLE
    assert result.reason == "unavailable in 1 of 3 pairs"


def test_pair_without_cars_is_skipped():
    baseline = {**BASELINE, "B3": RunValue(NA, None, "no arrivals")}

    result = compare_runs(comparison_spec(), SET, baseline, INTERVENTION)

    assert [p.baseline_run_id for p in result.used_pairs] == ["B1", "B2"]
    assert result.mean_change == pytest.approx(-5.5)
    assert result.baseline_mean == pytest.approx(45)


def test_no_usable_pair_is_not_applicable():
    baseline = {r: RunValue(NA, None) for r in BASELINE}

    result = compare_runs(comparison_spec(), SET, baseline, INTERVENTION)

    assert result.status == NA
    assert result.reason == NO_PAIR_VALUE_REASON


def test_missing_side_rejected():
    with pytest.raises(ValueError, match="both sides"):
        compare_runs(comparison_spec(), SET, {"B1": ok(40)}, INTERVENTION)


def test_queue_change_equals_difference_of_reported_values():
    """Each side uses its own chosen lane's runs."""

    baseline_lane = {"B1": ok(60), "B2": ok(90), "B3": ok(60)}       # mean 70
    intervention_lane = {"I1": ok(50), "I2": ok(40), "I3": ok(60)}   # mean 50

    spec = comparison_spec(kpi=KpiName.QUEUE_LENGTH, unit=KpiUnit.METRES)
    result = compare_runs(spec, SET, baseline_lane, intervention_lane)

    assert result.mean_change == pytest.approx(50 - 70)


def test_hcm_comparison_is_a_plain_difference():
    spec = comparison_spec(
        kpi=KpiName.VOLUME_TO_CAPACITY_RATIO,
        level=KpiLevel.LANE_GROUP,
        element_id="APP_S_T",
        unit=KpiUnit.RATIO,
        method=KpiMethod.HCM,
        replication_set_id=None,
        input_origins=[InputOrigin.MODELLED_ASSUMPTION],
    )

    result = compare_single(spec, ok(1.33), ok(0.95))

    assert result.mean_change == pytest.approx(-0.38)
    assert result.used_pairs == []
    assert result.standard_deviation is None


def test_hcm_comparison_with_missing_side_is_unavailable():
    spec = comparison_spec(method=KpiMethod.HCM, replication_set_id=None)

    assert compare_single(spec, ok(30), RunValue(UNAVAILABLE, None)).status == UNAVAILABLE


def test_wrong_method_rejected():
    with pytest.raises(ValueError, match="simulation"):
        compare_runs(comparison_spec(method=KpiMethod.HCM), SET, BASELINE, INTERVENTION)

    with pytest.raises(ValueError, match="HCM"):
        compare_single(comparison_spec(), ok(1), ok(2))


def test_full_sample_has_no_partial_tag():
    result = compare_runs(comparison_spec(), SET, BASELINE, INTERVENTION)

    assert result.pair_count == 3
    assert result.is_partial_sample is False


def test_skipped_pair_sets_the_partial_tag():
    """Based on 2 of 3 matched runs: may differ from the scenario's own values."""

    baseline = {**BASELINE, "B3": RunValue(NA, None, "no arrivals")}

    result = compare_runs(comparison_spec(), SET, baseline, INTERVENTION)

    assert result.pair_count == 3
    assert len(result.used_pairs) == 2
    assert result.is_partial_sample is True


def test_unavailable_comparison_keeps_the_pair_count_but_no_tag():
    intervention = {**INTERVENTION, "I2": RunValue(UNAVAILABLE, None)}

    result = compare_runs(comparison_spec(), SET, BASELINE, intervention)

    assert result.pair_count == 3
    assert result.is_partial_sample is False


def los_spec_for_comparison():
    return comparison_spec(kpi=KpiName.LEVEL_OF_SERVICE, unit=KpiUnit.GRADE)


def test_level_of_service_comparison_shows_both_grades():
    """40/50/60 -> 35/44/56 s: mean 50 -> 45 s, LOS D -> D."""

    delay = compare_runs(comparison_spec(), SET, BASELINE, INTERVENTION)

    result = compare_level_of_service(los_spec_for_comparison(), delay)

    assert result.baseline_los_grade == LevelOfServiceGrade.D
    assert result.intervention_los_grade == LevelOfServiceGrade.D
    assert len(result.used_pairs) == 3
    assert result.is_partial_sample is False


def test_level_of_service_follows_the_matched_pairs():
    """
    The reviewer's example: baseline 10, 100, NA; intervention 20, NA,
    NA. Only pair 1 is matched, so the delay goes 10 -> 20 s (worse) and
    the LOS A -> B (worse too). Grading the baseline from all its runs
    (mean 55 s, LOS D) would have shown D -> B, an apparent improvement.
    """

    baseline = {"B1": ok(10), "B2": ok(100), "B3": RunValue(NA, None)}
    intervention = {"I1": ok(20), "I2": RunValue(NA, None), "I3": RunValue(NA, None)}

    delay = compare_runs(comparison_spec(), SET, baseline, intervention)
    result = compare_level_of_service(los_spec_for_comparison(), delay)

    assert delay.mean_change == pytest.approx(10)
    assert result.baseline_los_grade == LevelOfServiceGrade.A
    assert result.intervention_los_grade == LevelOfServiceGrade.B
    assert [p.baseline_run_id for p in result.used_pairs] == ["B1"]
    assert result.is_partial_sample is True


def test_level_of_service_without_delay_change_follows_its_status():
    intervention = {**INTERVENTION, "I2": RunValue(UNAVAILABLE, None)}
    delay = compare_runs(comparison_spec(), SET, BASELINE, intervention)

    result = compare_level_of_service(los_spec_for_comparison(), delay)

    assert result.status == UNAVAILABLE
    assert result.reason == "unavailable in 1 of 3 pairs"


def test_level_of_service_needs_the_matching_delay_comparison():
    other_element = compare_runs(
        comparison_spec(element_id="MOV_E_L"), SET, BASELINE, INTERVENTION
    )

    with pytest.raises(ValueError, match="same element and interval"):
        compare_level_of_service(los_spec_for_comparison(), other_element)


def hcm_los(scenario, grade, **overrides):
    """An HCM level-of-service result for East through (no runs)."""

    values = dict(
        kpi="level_of_service",
        level="movement",
        movement_id="MOV_E_T",
        interval_start=INTERVAL.start,
        interval_end=INTERVAL.end,
        los_grade=grade,
        unit="grade",
        status="ok",
        method="hcm",
        input_origins=["modelled_assumption"],
        scenario_id=scenario,
    )
    values.update(overrides)
    if values["status"] != OK:
        values["input_origins"] = []
    return KpiResult(**values)


def test_hcm_level_of_service_keeps_both_grades():
    """HCM has no runs, so nothing is left out: the grades are kept."""

    spec = comparison_spec(
        kpi=KpiName.LEVEL_OF_SERVICE,
        unit=KpiUnit.GRADE,
        method=KpiMethod.HCM,
        replication_set_id=None,
        input_origins=[InputOrigin.MODELLED_ASSUMPTION],
    )

    result = compare_hcm_level_of_service(spec, hcm_los("SCN_BASE", "E"), hcm_los("SCN_INT", "C"))

    assert result.baseline_los_grade == LevelOfServiceGrade.E
    assert result.intervention_los_grade == LevelOfServiceGrade.C
    assert result.used_pairs == []
    assert result.pair_count is None
    assert result.is_partial_sample is False


def hcm_los_comparison_spec():
    return comparison_spec(
        kpi=KpiName.LEVEL_OF_SERVICE,
        unit=KpiUnit.GRADE,
        method=KpiMethod.HCM,
        replication_set_id=None,
        input_origins=[InputOrigin.MODELLED_ASSUMPTION],
    )


@pytest.mark.parametrize(
    "side, overrides, field",
    [
        ("baseline", {"scenario_id": "SCN_OTHER"}, "scenario_id"),
        ("intervention", {"scenario_id": "SCN_OTHER"}, "scenario_id"),
        ("baseline", {"movement_id": "MOV_W_T"}, "element_id"),
        ("intervention", {"kpi": "control_delay", "unit": "s/veh", "los_grade": None, "value": 30}, "kpi"),
        ("baseline", {"method": "simulation", "run_ids": ["RUN_BASE"], "input_origins": SIM_ORIGINS}, "method"),
        ("intervention", {"level": "approach", "movement_id": None, "approach_id": "APP_E"}, "level"),
        ("baseline", {"interval_start": INTERVAL.start - timedelta(minutes=15)}, "interval_start"),
        ("intervention", {"interval_end": INTERVAL.end + timedelta(minutes=15)}, "interval_end"),
    ],
)
def test_hcm_los_rejects_mismatched_results(side, overrides, field):
    baseline = hcm_los("SCN_BASE", "E", **(overrides if side == "baseline" else {}))
    intervention = hcm_los("SCN_INT", "C", **(overrides if side == "intervention" else {}))

    with pytest.raises(ValueError, match=f"{side} HCM.*{field}"):
        compare_hcm_level_of_service(hcm_los_comparison_spec(), baseline, intervention)


@pytest.mark.parametrize("unavailable_side", ["baseline", "intervention", "both"])
def test_hcm_los_rejects_mismatched_unavailable_results(unavailable_side):
    baseline_unavailable = unavailable_side in {"baseline", "both"}
    intervention_unavailable = unavailable_side in {"intervention", "both"}
    baseline = hcm_los(
        "SCN_OTHER" if baseline_unavailable else "SCN_BASE",
        None if baseline_unavailable else "E",
        **({"status": UNAVAILABLE, "reason": "missing delay"} if baseline_unavailable else {}),
    )
    intervention = hcm_los(
        "SCN_INT",
        None if intervention_unavailable else "C",
        **(
            {"status": UNAVAILABLE, "reason": "missing delay", "movement_id": "MOV_W_T"}
            if intervention_unavailable else {}
        ),
    )

    with pytest.raises(ValueError, match="HCM level-of-service result does not match"):
        compare_hcm_level_of_service(hcm_los_comparison_spec(), baseline, intervention)


def test_hcm_los_with_matching_unavailable_result_remains_unavailable():
    result = compare_hcm_level_of_service(
        hcm_los_comparison_spec(),
        hcm_los("SCN_BASE", None, status=UNAVAILABLE, reason="missing delay"),
        hcm_los("SCN_INT", "C"),
    )

    assert result.status == UNAVAILABLE
    assert result.reason == comparison.PART_UNAVAILABLE_REASON


# ============================================================
# LABELS MATCH THE DATA (PR #33 review)
# ============================================================

@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"baseline_scenario_id": "SCN_OTHER"}, "baseline_scenario_id: spec says SCN_OTHER, set is SCN_BASE"),
        ({"intervention_scenario_id": "SCN_OTHER"}, "intervention_scenario_id: spec says SCN_OTHER, set is SCN_INT"),
        ({"replication_set_id": "RS_9"}, "replication_set_id: spec says RS_9, set is RS_1"),
    ],
)
def test_spec_labels_must_match_the_set(overrides, message):
    """Otherwise RS_1's runs could be saved under another experiment's names."""

    with pytest.raises(ValueError, match=message):
        compare_runs(comparison_spec(**overrides), SET, BASELINE, INTERVENTION)


def test_level_of_service_labels_must_match_the_delay_comparison():
    delay = compare_runs(comparison_spec(), SET, BASELINE, INTERVENTION)
    spec = comparison_spec(
        kpi=KpiName.LEVEL_OF_SERVICE, unit=KpiUnit.GRADE, replication_set_id="RS_9"
    )

    with pytest.raises(ValueError, match="delay comparison is RS_1"):
        compare_level_of_service(spec, delay)


# ============================================================
# SHARED LANE GROUP ON HCM MOVEMENT VALUES (PR #33 review)
# ============================================================

def hcm_capacity_spec(**overrides):
    """HCM capacity of East left, which partly uses the shared group APP_E_LT."""

    values = dict(
        kpi=KpiName.CAPACITY,
        level=KpiLevel.MOVEMENT,
        element_id="MOV_E_L",
        unit=KpiUnit.VEHICLES_PER_HOUR,
        method=KpiMethod.HCM,
        interval=INTERVAL,
        scenario_id="SCN_BASE",
        input_origins=[InputOrigin.MODELLED_ASSUMPTION],
        measured_on_lane_group_id="APP_E_LT",
    )
    values.update(overrides)
    return KpiSpec(**values)


def test_shared_lane_group_reaches_the_result():
    result = single_result(hcm_capacity_spec(), OK, 410.0)

    assert result.measured_on_lane_group_id == "APP_E_LT"
    assert result.is_shared_value is True


def test_movement_without_shared_group_has_no_tag():
    result = single_result(hcm_capacity_spec(measured_on_lane_group_id=None), OK, 410.0)

    assert result.is_shared_value is False


def test_shared_lane_group_dropped_without_a_value():
    result = single_result(hcm_capacity_spec(), UNAVAILABLE, None, reason="no capacity")

    assert result.measured_on_lane_group_id is None


def test_lane_and_lane_group_together_rejected():
    """A value is measured on a lane or on a lane group, not both."""

    spec = hcm_capacity_spec(measured_on_lane_id="LANE_E_2")

    with pytest.raises(ValueError, match="not both"):
        single_result(spec, OK, 410.0)

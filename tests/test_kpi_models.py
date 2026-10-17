from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.kpis import (
    ALLOWED_KPI_LEVELS,
    VALUE_COMPUTATIONS,
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    LevelOfServiceGrade,
    InputOrigin,
    ValueComputation,
)


RIYADH = timezone(timedelta(hours=3))


def valid_kpi_data(**overrides):
    """A valid movement-level control delay result from one run."""

    data = {
        "kpi": "control_delay",
        "level": "movement",
        "movement_id": "MOV_E_W",
        "interval_start": datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
        "interval_end": datetime(2026, 10, 14, 8, 15, tzinfo=RIYADH),
        "value": 32.5,
        "unit": "s/veh",
        "status": "ok",
        "method": "simulation",
        "input_origins": ["simulated", "observed"],
        "scenario_id": "SCN_BASE",
        "run_ids": ["RUN_1"],
    }

    # A result without a value carries no origins, unless a test
    # sets them on purpose.
    if overrides.get("status", "ok") != "ok":
        data["input_origins"] = []

    data.update(overrides)
    return data


# ============================================================
# VALID RESULTS
# ============================================================

def test_valid_movement_result():
    result = KpiResult(**valid_kpi_data())

    assert result.kpi == KpiName.CONTROL_DELAY
    assert result.level == KpiLevel.MOVEMENT
    assert result.unit == KpiUnit.SECONDS_PER_VEHICLE
    assert result.status == KpiStatus.OK
    assert result.method == KpiMethod.SIMULATION
    assert result.value_computation == ValueComputation.DIRECT_SUMMARY
    assert result.input_origins == [
        InputOrigin.SIMULATED,
        InputOrigin.OBSERVED,
    ]
    assert result.replication_count == 1


def test_valid_approach_result():
    result = KpiResult(
        **valid_kpi_data(
            level="approach",
            movement_id=None,
            approach_id="APP_E",
        )
    )

    assert result.approach_id == "APP_E"
    assert result.movement_id is None


def test_valid_intersection_result():
    result = KpiResult(
        **valid_kpi_data(
            level="intersection",
            movement_id=None,
            intersection_id="INT_01",
        )
    )

    assert result.intersection_id == "INT_01"
    assert result.approach_id is None


def test_valid_level_of_service_result():
    result = KpiResult(
        **valid_kpi_data(
            kpi="level_of_service",
            value=None,
            los_grade="C",
            unit="grade",
        )
    )

    assert result.los_grade == LevelOfServiceGrade.C


def test_valid_replicated_result():
    result = KpiResult(
        **valid_kpi_data(
            run_ids=["RUN_1", "RUN_2", "RUN_3"],
            standard_deviation=2.4,
        )
    )

    assert result.replication_count == 3


def test_value_zero_is_allowed_when_measured():
    result = KpiResult(
        **valid_kpi_data(kpi="queue_length", unit="m", value=0)
    )

    assert result.value == 0


def test_ok_result_may_carry_a_reason():
    result = KpiResult(
        **valid_kpi_data(reason="possibly capacity-constrained")
    )

    assert result.reason == "possibly capacity-constrained"


@pytest.mark.parametrize(
    "status",
    ["unavailable", "not_applicable"],
)
def test_result_without_value(status):
    result = KpiResult(
        **valid_kpi_data(
            status=status,
            value=None,
            reason="no data for this interval",
        )
    )

    assert result.value is None


def test_ids_and_reason_are_stripped():
    result = KpiResult(
        **valid_kpi_data(
            movement_id="  MOV_E_W  ",
            run_ids=[" RUN_1 "],
            reason="  note  ",
        )
    )

    assert result.movement_id == "MOV_E_W"
    assert result.run_ids == ["RUN_1"]
    assert result.reason == "note"


# ============================================================
# IDENTIFIERS
# ============================================================

LEVEL_IDS = {
    "movement": ("movement_id", "MOV_E_W"),
    "approach": ("approach_id", "APP_E"),
    "intersection": ("intersection_id", "INT_01"),
}


def level_data(level, **overrides):
    """Valid result data at a given level, carrying only that level's ID."""

    field, element_id = LEVEL_IDS[level]
    data = valid_kpi_data(level=level, movement_id=None)
    data[field] = element_id
    data.update(overrides)
    return data


@pytest.mark.parametrize("level", ["movement", "approach", "intersection"])
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_element_id_rejected(level, bad_value):
    field, _ = LEVEL_IDS[level]

    with pytest.raises(ValidationError):
        KpiResult(**level_data(level, **{field: bad_value}))


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_scenario_id_rejected(bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(scenario_id=bad_value))


def test_empty_reason_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(reason="   "))


@pytest.mark.parametrize(
    "run_ids",
    [[""], ["  "], ["RUN_1", "RUN_1"], ["RUN_1", " RUN_1 "]],
)
def test_invalid_run_ids_rejected(run_ids):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(run_ids=run_ids))


# ============================================================
# ENUMS
# ============================================================

@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("kpi", "average_speed"),
        ("level", "segment"),
        ("unit", "km/h"),
        ("status", "missing"),
        ("method", "observed"),
        ("input_origins", ["derived"]),
        ("input_origins", ["rcrc"]),
        ("los_grade", "G"),
    ],
)
def test_invalid_enum_values_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(**{field: bad_value}))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(colour="red"))


# ============================================================
# TIME
# ============================================================

def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                interval_start=datetime(2026, 10, 14, 8, 0)
            )
        )


def test_non_riyadh_timestamp_rejected():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                interval_start=datetime(
                    2026, 10, 14, 5, 0, tzinfo=timezone.utc
                ),
                interval_end=datetime(
                    2026, 10, 14, 5, 15, tzinfo=timezone.utc
                ),
            )
        )


@pytest.mark.parametrize("minutes", [0, -15])
def test_empty_or_reversed_interval_rejected(minutes):
    start = datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH)

    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                interval_start=start,
                interval_end=start + timedelta(minutes=minutes),
            )
        )


# ============================================================
# NUMBERS
# ============================================================

@pytest.mark.parametrize(
    "bad_value",
    [-1, float("nan"), float("inf")],
)
def test_invalid_value_rejected(bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(value=bad_value))


def test_negative_standard_deviation_rejected():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                run_ids=["RUN_1", "RUN_2"],
                standard_deviation=-0.5,
            )
        )


# ============================================================
# LEVEL AND IDS
# ============================================================

@pytest.mark.parametrize("level", ["movement", "approach", "intersection"])
def test_own_level_id_is_required(level):
    field, _ = LEVEL_IDS[level]

    with pytest.raises(ValidationError):
        KpiResult(**level_data(level, **{field: None}))


@pytest.mark.parametrize(
    "level, other_level",
    [
        ("movement", "approach"),
        ("movement", "intersection"),
        ("approach", "movement"),
        ("approach", "intersection"),
        ("intersection", "movement"),
        ("intersection", "approach"),
    ],
)
def test_other_level_ids_are_rejected(level, other_level):
    """Rule (a): only the element's own ID; parents are looked up."""

    other_field, other_id = LEVEL_IDS[other_level]

    with pytest.raises(ValidationError):
        KpiResult(**level_data(level, **{other_field: other_id}))


# ============================================================
# UNITS
# ============================================================

@pytest.mark.parametrize(
    "kpi, unit, method",
    [
        ("queue_length", "m", "simulation"),
        ("queue_length", "veh", "simulation"),
        ("saturation_flow_rate", "veh/h", "hcm"),
        ("saturation_flow_rate", "veh/h/lane", "hcm"),
        ("volume_to_capacity_ratio", "ratio", "hcm"),
        ("throughput", "veh/h", "simulation"),
    ],
)
def test_allowed_units_accepted(kpi, unit, method):
    result = KpiResult(
        **valid_kpi_data(kpi=kpi, unit=unit, method=method)
    )

    assert result.unit.value == unit


@pytest.mark.parametrize(
    "kpi, unit, method",
    [
        ("control_delay", "s", "simulation"),
        ("throughput", "veh", "simulation"),
        ("queue_length", "s", "simulation"),
        ("volume_to_capacity_ratio", "veh/h", "hcm"),
        ("capacity", "veh/h/lane", "hcm"),
    ],
)
def test_wrong_unit_rejected(kpi, unit, method):
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(kpi=kpi, unit=unit, method=method)
        )


# ============================================================
# STATUS AND VALUE
# ============================================================

def test_ok_without_value_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(value=None))


@pytest.mark.parametrize(
    "status",
    ["unavailable", "not_applicable"],
)
def test_missing_value_cannot_be_zero(status):
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                status=status,
                value=0,
                reason="no data",
            )
        )


@pytest.mark.parametrize(
    "status",
    ["unavailable", "not_applicable"],
)
def test_result_without_value_requires_reason(status):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(status=status, value=None))


def test_unavailable_result_cannot_have_standard_deviation():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                status="unavailable",
                value=None,
                reason="no data",
                run_ids=["RUN_1", "RUN_2"],
                standard_deviation=1.0,
            )
        )


# ============================================================
# LEVEL OF SERVICE
# ============================================================

def los_data(**overrides):
    data = {
        "kpi": "level_of_service",
        "value": None,
        "los_grade": "D",
        "unit": "grade",
    }
    data.update(overrides)
    return valid_kpi_data(**data)


def test_los_with_numeric_value_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**los_data(value=42.0))


def test_los_ok_without_grade_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**los_data(los_grade=None))


def test_grade_on_other_kpi_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(los_grade="B"))


def test_not_applicable_los_without_grade():
    result = KpiResult(
        **los_data(
            los_grade=None,
            status="not_applicable",
            reason="uncontrolled right turn",
            input_origins=[],
        )
    )

    assert result.los_grade is None


def test_replicated_los_needs_no_standard_deviation():
    result = KpiResult(**los_data(run_ids=["RUN_1", "RUN_2"]))

    assert result.standard_deviation is None


def test_los_with_standard_deviation_rejected():
    with pytest.raises(ValidationError):
        KpiResult(
            **los_data(
                run_ids=["RUN_1", "RUN_2"],
                standard_deviation=1.0,
            )
        )


# ============================================================
# REPLICATION
# ============================================================

def test_single_run_with_standard_deviation_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(standard_deviation=1.0))


def test_replicated_ok_result_requires_standard_deviation():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(run_ids=["RUN_1", "RUN_2"]))


def test_replicated_unavailable_result_without_standard_deviation():
    result = KpiResult(
        **valid_kpi_data(
            status="unavailable",
            value=None,
            reason="no data",
            run_ids=["RUN_1", "RUN_2"],
        )
    )

    assert result.replication_count == 2


# ============================================================
# METHOD AND ORIGINS
# ============================================================

@pytest.mark.parametrize(
    "kpi, unit, method, expected",
    [
        ("control_delay", "s/veh", "simulation", ValueComputation.DIRECT_SUMMARY),
        ("control_delay", "s/veh", "hcm", ValueComputation.DERIVED),
        ("queue_length", "m", "simulation", ValueComputation.DIRECT_SUMMARY),
        ("queue_storage_ratio", "ratio", "simulation", ValueComputation.DERIVED),
        ("throughput", "veh/h", "simulation", ValueComputation.DIRECT_SUMMARY),
        ("capacity", "veh/h", "hcm", ValueComputation.DERIVED),
        ("volume_to_capacity_ratio", "ratio", "hcm", ValueComputation.DERIVED),
    ],
)
def test_value_computation_follows_kpi_and_method(kpi, unit, method, expected):
    result = KpiResult(
        **valid_kpi_data(kpi=kpi, unit=unit, method=method)
    )

    assert result.value_computation == expected


def test_simulation_based_los_is_derived():
    result = KpiResult(**los_data())

    assert result.value_computation == ValueComputation.DERIVED


def test_value_computation_cannot_be_set():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(value_computation="derived"))


def test_result_without_value_has_no_value_computation():
    result = KpiResult(
        **valid_kpi_data(
            status="unavailable",
            value=None,
            reason="no data",
        )
    )

    assert result.value_computation is None


@pytest.mark.parametrize(
    "kpi, unit, method",
    [
        ("queue_length", "m", "hcm"),
        ("throughput", "veh/h", "hcm"),
        ("capacity", "veh/h", "simulation"),
        ("volume_to_capacity_ratio", "ratio", "simulation"),
    ],
)
def test_unsupported_kpi_and_method_rejected(kpi, unit, method):
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                kpi=kpi,
                unit=unit,
                method=method,
                input_origins=["observed", "modelled_assumption"],
            )
        )


def test_hcm_result_from_observed_and_assumed_inputs():
    result = KpiResult(
        **valid_kpi_data(
            kpi="volume_to_capacity_ratio",
            unit="ratio",
            value=0.87,
            method="hcm",
            input_origins=["observed", "modelled_assumption"],
        )
    )

    assert InputOrigin.MODELLED_ASSUMPTION in result.input_origins


def test_ok_result_requires_input_origins():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(input_origins=[]))


def test_duplicate_input_origins_rejected():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(input_origins=["simulated", "simulated"])
        )


def test_simulation_result_requires_simulated_input():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(input_origins=["observed"]))


def test_result_without_value_has_no_input_origins():
    with pytest.raises(ValidationError):
        KpiResult(
            **valid_kpi_data(
                status="unavailable",
                value=None,
                reason="no data",
                input_origins=["observed"],
            )
        )


# ============================================================
# RUNS BY METHOD (review comment 9)
# ============================================================

def hcm_data(**overrides):
    """A valid HCM capacity result calculated without running SUMO."""

    data = {
        "kpi": "capacity",
        "unit": "veh/h",
        "value": 1520.0,
        "method": "hcm",
        "input_origins": ["observed", "modelled_assumption"],
        "run_ids": [],
    }
    data.update(overrides)
    return valid_kpi_data(**data)


def test_simulation_result_without_runs_rejected():
    with pytest.raises(ValidationError, match="at least one run ID"):
        KpiResult(**valid_kpi_data(run_ids=[]))


def test_hcm_result_without_runs_is_allowed():
    result = KpiResult(**hcm_data())

    assert result.run_ids == []
    assert result.replication_count == 0


def test_run_ids_default_to_empty_for_hcm():
    data = hcm_data()
    del data["run_ids"]

    result = KpiResult(**data)

    assert result.run_ids == []


def test_hcm_result_without_runs_cannot_have_standard_deviation():
    with pytest.raises(ValidationError):
        KpiResult(**hcm_data(standard_deviation=10.0))


# ============================================================
# SERIALIZATION (review comment 8)
# ============================================================

COMPUTED_FIELDS = {"value_computation", "replication_count", "is_shared_value"}


def test_computed_fields_appear_in_dump():
    dumped = KpiResult(**valid_kpi_data()).model_dump()

    assert dumped["value_computation"] == ValueComputation.DIRECT_SUMMARY
    assert dumped["replication_count"] == 1


def test_computed_fields_appear_in_json():
    as_json = KpiResult(**valid_kpi_data()).model_dump_json()

    assert '"value_computation":"direct_summary"' in as_json
    assert '"replication_count":1' in as_json


def test_storage_round_trip_without_computed_fields():
    """The safe way to save and reload: leave out what is recalculated."""

    original = KpiResult(**valid_kpi_data())
    stored = original.model_dump(exclude=COMPUTED_FIELDS)

    reloaded = KpiResult(**stored)

    assert reloaded == original
    assert reloaded.value_computation == original.value_computation


def test_reloading_a_full_dump_fails():
    """Documents the catch: computed fields cannot be passed back in."""

    full_dump = KpiResult(**valid_kpi_data()).model_dump()

    with pytest.raises(ValidationError):
        KpiResult(**full_dump)


# ============================================================
# LANE AND LANE-GROUP LEVELS (shared-lane decision, 17 Oct)
# ============================================================

def lane_queue_data(**overrides):
    """A valid lane-level queue result: lane LANE_E_2, 48 m."""

    data = {
        "kpi": "queue_length",
        "unit": "m",
        "value": 48.0,
        "level": "lane",
        "movement_id": None,
        "lane_id": "LANE_E_2",
    }
    data.update(overrides)
    return valid_kpi_data(**data)


def lane_group_capacity_data(**overrides):
    """A valid HCM capacity result for lane group east_LT."""

    data = {
        "kpi": "capacity",
        "unit": "veh/h",
        "value": 620.0,
        "method": "hcm",
        "input_origins": ["observed", "modelled_assumption"],
        "run_ids": [],
        "level": "lane_group",
        "movement_id": None,
        "lane_group_id": "east_LT",
    }
    data.update(overrides)
    return valid_kpi_data(**data)


def test_both_tables_cover_the_same_pairs():
    assert set(ALLOWED_KPI_LEVELS) == set(VALUE_COMPUTATIONS)


def test_valid_lane_result():
    result = KpiResult(**lane_queue_data())

    assert result.level == KpiLevel.LANE
    assert result.lane_id == "LANE_E_2"


def test_valid_lane_group_result():
    result = KpiResult(**lane_group_capacity_data())

    assert result.level == KpiLevel.LANE_GROUP
    assert result.lane_group_id == "east_LT"


@pytest.mark.parametrize(
    "overrides",
    [
        # simulation delay is per car, never on a lane
        {"kpi": "control_delay", "unit": "s/veh"},
        # queue duration is now measured per car
        {"kpi": "queue_duration", "unit": "s"},
    ],
)
def test_per_car_kpis_not_reported_on_a_lane(overrides):
    with pytest.raises(ValidationError, match="not reported at lane level"):
        KpiResult(**lane_queue_data(**overrides))


def test_queue_length_not_reported_on_a_lane_group():
    with pytest.raises(ValidationError, match="not reported at lane_group"):
        KpiResult(
            **lane_queue_data(
                level="lane_group",
                lane_id=None,
                lane_group_id="east_LT",
            )
        )


def test_capacity_not_reported_at_intersection_level():
    with pytest.raises(ValidationError, match="not reported at intersection"):
        KpiResult(
            **lane_group_capacity_data(
                level="intersection",
                lane_group_id=None,
                intersection_id="INT_01",
            )
        )


def test_measured_saturation_flow_only_on_lanes():
    with pytest.raises(ValidationError, match="not reported at movement"):
        KpiResult(
            **valid_kpi_data(kpi="saturation_flow_rate", unit="veh/h/lane")
        )


@pytest.mark.parametrize(
    "data_builder, own_field",
    [
        (lane_queue_data, "lane_id"),
        (lane_group_capacity_data, "lane_group_id"),
    ],
)
def test_lane_levels_require_their_own_id(data_builder, own_field):
    with pytest.raises(ValidationError):
        KpiResult(**data_builder(**{own_field: None}))


@pytest.mark.parametrize(
    "field, value",
    [
        ("lane_group_id", "east_LT"),
        ("movement_id", "MOV_E_T"),
        ("approach_id", "APP_E"),
        ("intersection_id", "INT_01"),
    ],
)
def test_lane_result_rejects_other_ids(field, value):
    with pytest.raises(ValidationError):
        KpiResult(**lane_queue_data(**{field: value}))


@pytest.mark.parametrize("bad_value", ["", "   "])
@pytest.mark.parametrize(
    "data_builder, own_field",
    [
        (lane_queue_data, "lane_id"),
        (lane_group_capacity_data, "lane_group_id"),
    ],
)
def test_empty_lane_ids_rejected(data_builder, own_field, bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**data_builder(**{own_field: bad_value}))


# ============================================================
# SHARED-LANE MARKER
# ============================================================

def shared_queue_data(**overrides):
    """East-through's queue, taken from the shared lane LANE_E_2."""

    data = {
        "kpi": "queue_length",
        "unit": "m",
        "value": 48.0,
        "movement_id": "MOV_E_T",
        "measured_on_lane_id": "LANE_E_2",
    }
    data.update(overrides)
    return valid_kpi_data(**data)


def test_shared_lane_value_is_marked():
    result = KpiResult(**shared_queue_data())

    assert result.is_shared_value is True
    assert result.measured_on_lane_id == "LANE_E_2"


def test_ordinary_value_is_not_marked():
    result = KpiResult(**valid_kpi_data())

    assert result.is_shared_value is False


def test_shared_lane_group_value_is_marked():
    result = KpiResult(
        **lane_group_capacity_data(
            level="movement",
            lane_group_id=None,
            movement_id="MOV_E_T",
            measured_on_lane_group_id="east_LT",
        )
    )

    assert result.is_shared_value is True


def test_is_shared_value_appears_in_dump():
    dumped = KpiResult(**shared_queue_data()).model_dump()

    assert dumped["is_shared_value"] is True


def test_marker_only_on_movement_level():
    with pytest.raises(ValidationError, match="only used on movement-level"):
        KpiResult(
            **shared_queue_data(
                level="approach",
                movement_id=None,
                approach_id="APP_E",
            )
        )


def test_marker_cannot_name_lane_and_lane_group():
    with pytest.raises(ValidationError, match="not both"):
        KpiResult(**shared_queue_data(measured_on_lane_group_id="east_LT"))


@pytest.mark.parametrize(
    "overrides",
    [
        # simulation delay is per car: never measured on a lane
        {"kpi": "control_delay", "unit": "s/veh", "value": 32.5},
        # queue length is a lane measure, not a lane-group one
        {"measured_on_lane_id": None, "measured_on_lane_group_id": "east_LT"},
    ],
)
def test_marker_must_match_the_kpi(overrides):
    with pytest.raises(ValidationError, match="is not measured on a"):
        KpiResult(**shared_queue_data(**overrides))


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_marker_rejected(bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**shared_queue_data(measured_on_lane_id=bad_value))


def test_shared_value_storage_round_trip():
    original = KpiResult(**shared_queue_data())
    reloaded = KpiResult(**original.model_dump(exclude=COMPUTED_FIELDS))

    assert reloaded == original
    assert reloaded.is_shared_value is True
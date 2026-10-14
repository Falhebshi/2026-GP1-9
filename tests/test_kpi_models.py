from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.kpis import (
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    LevelOfServiceGrade,
    InputOrigin,
    ValueOrigin,
)


RIYADH = timezone(timedelta(hours=3))


def valid_kpi_data(**overrides):
    """A valid movement-level control delay result from one run."""

    data = {
        "kpi": "control_delay",
        "level": "movement",
        "intersection_id": "INT_01",
        "approach_id": "APP_E",
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
    assert result.value_origin == ValueOrigin.SIMULATED
    assert result.input_origins == [
        InputOrigin.SIMULATED,
        InputOrigin.OBSERVED,
    ]
    assert result.replication_count == 1


def test_valid_approach_result():
    result = KpiResult(
        **valid_kpi_data(level="approach", movement_id=None)
    )

    assert result.movement_id is None


def test_valid_intersection_result():
    result = KpiResult(
        **valid_kpi_data(
            level="intersection",
            approach_id=None,
            movement_id=None,
        )
    )

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
            intersection_id="  INT_01  ",
            run_ids=[" RUN_1 "],
            reason="  note  ",
        )
    )

    assert result.intersection_id == "INT_01"
    assert result.run_ids == ["RUN_1"]
    assert result.reason == "note"


# ============================================================
# IDENTIFIERS
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["intersection_id", "scenario_id", "approach_id", "movement_id"],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(**{field: bad_value}))


def test_empty_reason_rejected():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(reason="   "))


@pytest.mark.parametrize(
    "run_ids",
    [[], [""], ["  "], ["RUN_1", "RUN_1"], ["RUN_1", " RUN_1 "]],
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

@pytest.mark.parametrize(
    "overrides",
    [
        {"level": "movement", "movement_id": None},
        {"level": "movement", "approach_id": None},
        {"level": "approach", "approach_id": None, "movement_id": None},
        {"level": "approach"},
        {"level": "intersection", "movement_id": None},
        {"level": "intersection", "approach_id": None},
    ],
)
def test_ids_must_match_level(overrides):
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(**overrides))


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
        ("control_delay", "s/veh", "simulation", ValueOrigin.SIMULATED),
        ("control_delay", "s/veh", "hcm", ValueOrigin.DERIVED),
        ("queue_length", "m", "simulation", ValueOrigin.SIMULATED),
        ("queue_storage_ratio", "ratio", "simulation", ValueOrigin.DERIVED),
        ("throughput", "veh/h", "simulation", ValueOrigin.SIMULATED),
        ("capacity", "veh/h", "hcm", ValueOrigin.DERIVED),
        ("volume_to_capacity_ratio", "ratio", "hcm", ValueOrigin.DERIVED),
    ],
)
def test_value_origin_follows_kpi_and_method(kpi, unit, method, expected):
    result = KpiResult(
        **valid_kpi_data(kpi=kpi, unit=unit, method=method)
    )

    assert result.value_origin == expected


def test_simulation_based_los_is_derived():
    result = KpiResult(**los_data())

    assert result.value_origin == ValueOrigin.DERIVED


def test_value_origin_cannot_be_set():
    with pytest.raises(ValidationError):
        KpiResult(**valid_kpi_data(value_origin="derived"))


def test_result_without_value_has_no_value_origin():
    result = KpiResult(
        **valid_kpi_data(
            status="unavailable",
            value=None,
            reason="no data",
        )
    )

    assert result.value_origin is None


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
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.kpis import KpiComparison, LevelOfServiceGrade


RIYADH = timezone(timedelta(hours=3))

PAIRS = [
    {"baseline_run_id": "RUN_B1", "intervention_run_id": "RUN_I1"},
    {"baseline_run_id": "RUN_B2", "intervention_run_id": "RUN_I2"},
    {"baseline_run_id": "RUN_B3", "intervention_run_id": "RUN_I3"},
]


def comparison_data(**overrides):
    """
    A valid movement delay comparison over 3 pairs: baseline 40, 50,
    60 s; intervention 35, 44, 56 s; change -5 +/- 1 s.
    """

    data = {
        "kpi": "control_delay",
        "level": "movement",
        "movement_id": "MOV_E_W",
        "interval_start": datetime(2026, 10, 14, 8, 0, tzinfo=RIYADH),
        "interval_end": datetime(2026, 10, 14, 8, 15, tzinfo=RIYADH),
        "unit": "s/veh",
        "method": "simulation",
        "baseline_scenario_id": "SCN_BASE",
        "intervention_scenario_id": "SCN_INT",
        "replication_set_id": "RS_1",
        "used_pairs": PAIRS,
        "pair_count": 3,
        "status": "ok",
        "mean_change": -5.0,
        "standard_deviation": 1.0,
        "baseline_mean": 50.0,
        "input_origins": ["simulated", "modelled_assumption"],
    }

    if overrides.get("status", "ok") != "ok":
        for field in ("mean_change", "standard_deviation", "baseline_mean"):
            data[field] = None
        data["used_pairs"] = []
        data["input_origins"] = []

    data.update(overrides)
    return data


def hcm_data(**overrides):
    """A valid HCM v/c comparison: no runs, a plain difference."""

    data = comparison_data(
        kpi="volume_to_capacity_ratio",
        level="lane_group",
        movement_id=None,
        lane_group_id="APP_E_T",
        unit="ratio",
        method="hcm",
        replication_set_id=None,
        used_pairs=[],
        pair_count=None,
        mean_change=-0.12,
        standard_deviation=None,
        baseline_mean=0.95,
        input_origins=["observed", "modelled_assumption"],
    )
    data.update(overrides)
    return data


def los_data(**overrides):
    data = comparison_data(
        kpi="level_of_service",
        unit="grade",
        mean_change=None,
        standard_deviation=None,
        baseline_mean=None,
        baseline_los_grade="D",
        intervention_los_grade="C",
    )
    data.update(overrides)
    return data


# ============================================================
# VALID COMPARISONS
# ============================================================

def test_valid_simulation_comparison():
    result = KpiComparison(**comparison_data())

    assert result.mean_change == -5.0
    assert len(result.used_pairs) == 3


def test_percent_change_by_hand():
    """-5 / 50 = -10 %."""

    assert KpiComparison(**comparison_data()).percent_change == pytest.approx(-10.0)


def test_percent_change_without_baseline_is_none():
    """No percentage of zero: a baseline of 0 m queue that grows to 20 m."""

    result = KpiComparison(
        **comparison_data(mean_change=20.0, baseline_mean=0.0)
    )

    assert result.percent_change is None


def test_valid_hcm_comparison_has_no_runs():
    result = KpiComparison(**hcm_data())

    assert result.used_pairs == []
    assert result.percent_change == pytest.approx(-12.0 / 0.95)


def test_valid_los_comparison():
    result = KpiComparison(**los_data())

    assert result.baseline_los_grade == LevelOfServiceGrade.D
    assert result.intervention_los_grade == LevelOfServiceGrade.C
    assert result.percent_change is None


def test_single_pair_has_no_standard_deviation():
    result = KpiComparison(
        **comparison_data(used_pairs=PAIRS[:1], standard_deviation=None)
    )

    assert result.standard_deviation is None


@pytest.mark.parametrize("status", ["unavailable", "not_applicable"])
def test_comparison_without_value(status):
    result = KpiComparison(
        **comparison_data(status=status, reason="unavailable in 1 of 10 runs")
    )

    assert result.mean_change is None
    assert result.percent_change is None


def test_approach_comparison_with_slip_tag():
    result = KpiComparison(
        **comparison_data(
            level="approach",
            movement_id=None,
            approach_id="APP_S",
            uncontrolled_movements="included",
        )
    )

    assert result.uncontrolled_movements.value == "included"


# ============================================================
# REJECTED COMPARISONS
# ============================================================

def test_same_scenarios_rejected():
    with pytest.raises(ValidationError, match="must be different"):
        KpiComparison(**comparison_data(intervention_scenario_id="SCN_BASE"))


def test_simulation_comparison_needs_replication_set():
    with pytest.raises(ValidationError, match="replication_set_id"):
        KpiComparison(**comparison_data(replication_set_id=None))


def test_simulation_comparison_needs_pairs():
    with pytest.raises(ValidationError, match="at least one used pair"):
        KpiComparison(**comparison_data(used_pairs=[], standard_deviation=None))


@pytest.mark.parametrize(
    "overrides",
    [{"replication_set_id": "RS_1"}, {"used_pairs": PAIRS[:1]}],
)
def test_hcm_comparison_has_no_runs(overrides):
    with pytest.raises(ValidationError, match="no replication set"):
        KpiComparison(**hcm_data(**overrides))


def test_run_used_twice_rejected():
    pairs = [
        PAIRS[0],
        {"baseline_run_id": "RUN_B1", "intervention_run_id": "RUN_I9"},
    ]

    with pytest.raises(ValidationError, match="only once"):
        KpiComparison(**comparison_data(used_pairs=pairs))


def test_several_pairs_require_standard_deviation():
    with pytest.raises(ValidationError, match="require standard_deviation"):
        KpiComparison(**comparison_data(standard_deviation=None))


def test_one_pair_cannot_have_standard_deviation():
    with pytest.raises(ValidationError, match="more than one pair"):
        KpiComparison(**comparison_data(used_pairs=PAIRS[:1]))


def test_ok_without_change_rejected():
    with pytest.raises(ValidationError, match="requires mean_change"):
        KpiComparison(**comparison_data(mean_change=None))


def test_negative_intervention_mean_rejected():
    """Baseline 4 s cannot fall by 5 s: a delay is never negative."""

    with pytest.raises(ValidationError, match="must not be negative"):
        KpiComparison(**comparison_data(baseline_mean=4.0))


def test_value_on_unavailable_comparison_rejected():
    with pytest.raises(ValidationError, match="must not have a value"):
        KpiComparison(
            **comparison_data(status="unavailable", reason="x", mean_change=-5.0)
        )


def test_unavailable_comparison_requires_reason():
    with pytest.raises(ValidationError, match="requires a reason"):
        KpiComparison(**comparison_data(status="unavailable"))


def test_unavailable_comparison_cannot_list_pairs():
    with pytest.raises(ValidationError, match="must not list used pairs"):
        KpiComparison(
            **comparison_data(status="unavailable", reason="x", used_pairs=PAIRS)
        )


def test_los_with_numeric_change_rejected():
    with pytest.raises(ValidationError, match="not a numeric change"):
        KpiComparison(**los_data(mean_change=-1.0))


def test_los_needs_both_grades():
    with pytest.raises(ValidationError, match="requires both grades"):
        KpiComparison(**los_data(intervention_los_grade=None))


def test_grades_on_other_kpi_rejected():
    with pytest.raises(ValidationError, match="only allowed for level_of_service"):
        KpiComparison(**comparison_data(baseline_los_grade="D"))


def test_simulation_comparison_must_include_simulated():
    with pytest.raises(ValidationError, match="'simulated'"):
        KpiComparison(**comparison_data(input_origins=["observed"]))


def test_ok_comparison_needs_origins():
    with pytest.raises(ValidationError, match="at least one input origin"):
        KpiComparison(**comparison_data(input_origins=[]))


def test_wrong_unit_rejected():
    with pytest.raises(ValidationError, match="is not allowed"):
        KpiComparison(**comparison_data(unit="m"))


def test_level_not_reported_rejected():
    """HCM capacity is not reported at intersection level."""

    with pytest.raises(ValidationError, match="is not reported"):
        KpiComparison(
            **hcm_data(
                kpi="capacity",
                unit="veh/h",
                level="intersection",
                lane_group_id=None,
                intersection_id="INT_01",
                mean_change=100.0,
                baseline_mean=1200.0,
            )
        )


def test_element_id_must_match_level():
    with pytest.raises(ValidationError, match="require approach_id"):
        KpiComparison(**comparison_data(level="approach"))


def test_wrong_slip_tag_rejected():
    with pytest.raises(ValidationError, match="cannot be"):
        KpiComparison(
            **comparison_data(
                level="approach",
                movement_id=None,
                approach_id="APP_S",
                uncontrolled_movements="excluded",
            )
        )


def test_non_riyadh_time_rejected():
    with pytest.raises(ValidationError, match="Riyadh"):
        KpiComparison(
            **comparison_data(
                interval_start=datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)
            )
        )


@pytest.mark.parametrize("field", ["percent_change", "is_partial_sample"])
def test_computed_fields_cannot_be_passed_in(field):
    with pytest.raises(ValidationError):
        KpiComparison(**comparison_data(**{field: True}))


# ============================================================
# STORAGE
# ============================================================

COMPUTED_FIELDS = {"percent_change", "is_partial_sample"}


def test_storage_round_trip_without_percent_change():
    original = KpiComparison(**comparison_data())
    reloaded = KpiComparison(**original.model_dump(exclude=COMPUTED_FIELDS))

    assert reloaded == original


def test_percent_change_appears_in_dump():
    assert KpiComparison(**comparison_data()).model_dump()["percent_change"] == pytest.approx(-10.0)


# ============================================================
# PAIR COUNT AND THE PARTIAL-SAMPLE TAG (PR #33 review)
# ============================================================

def test_all_pairs_used_is_not_partial():
    assert KpiComparison(**comparison_data()).is_partial_sample is False


def test_fewer_pairs_used_is_partial():
    """Based on 2 of 3 matched runs."""

    result = KpiComparison(**comparison_data(used_pairs=PAIRS[:2]))

    assert result.is_partial_sample is True


def test_comparison_without_value_is_never_partial():
    result = KpiComparison(**comparison_data(status="unavailable", reason="x"))

    assert result.is_partial_sample is False


def test_simulation_comparison_requires_pair_count():
    with pytest.raises(ValidationError, match="require a pair_count"):
        KpiComparison(**comparison_data(pair_count=None))


def test_more_used_pairs_than_pair_count_rejected():
    with pytest.raises(ValidationError, match="more pairs than pair_count"):
        KpiComparison(**comparison_data(pair_count=2))


def test_hcm_comparison_cannot_have_pair_count():
    with pytest.raises(ValidationError, match="no replication set or pairs"):
        KpiComparison(**hcm_data(pair_count=3))


@pytest.mark.parametrize("bad_value", [True, 0])
def test_invalid_pair_count_rejected(bad_value):
    with pytest.raises(ValidationError):
        KpiComparison(**comparison_data(pair_count=bad_value))


def test_partial_tag_appears_in_dump():
    dumped = KpiComparison(**comparison_data(used_pairs=PAIRS[:2])).model_dump()

    assert dumped["is_partial_sample"] is True

import pytest
from pydantic import ValidationError

from jaadah.models.scenario import ReplicationPair, ReplicationSet


def pair_data(label, **overrides):
    """A valid pair whose run IDs are built from a label."""

    data = {
        "baseline_run_id": f"RUN_B_{label}",
        "intervention_run_id": f"RUN_I_{label}",
    }
    data.update(overrides)
    return data


def valid_set_data(**overrides):
    """A valid experiment with three matched pairs."""

    data = {
        "replication_set_id": "RS_TIMING_A",
        "baseline_scenario_id": "SCN_BASE",
        "intervention_scenario_id": "SCN_TIMING_A",
        "pairs": [pair_data(1), pair_data(2), pair_data(3)],
    }
    data.update(overrides)
    return data


# ============================================================
# REPLICATION PAIR
# ============================================================

def test_valid_pair():
    pair = ReplicationPair(**pair_data(1))

    assert pair.baseline_run_id == "RUN_B_1"
    assert pair.intervention_run_id == "RUN_I_1"


def test_seed_is_not_a_field():
    """SimulationRun owns the seed; a pair must not repeat it."""

    with pytest.raises(ValidationError):
        ReplicationPair(**pair_data(1, random_seed=42))


@pytest.mark.parametrize(
    "field",
    ["baseline_run_id", "intervention_run_id"],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_run_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        ReplicationPair(**pair_data(1, **{field: bad_value}))


def test_pair_with_same_run_twice_rejected():
    with pytest.raises(ValidationError):
        ReplicationPair(**pair_data(1, intervention_run_id="RUN_B_1"))


def test_pair_same_run_after_stripping_rejected():
    with pytest.raises(ValidationError):
        ReplicationPair(
            **pair_data(1, intervention_run_id="  RUN_B_1  ")
        )


def test_pair_extra_fields_rejected():
    with pytest.raises(ValidationError):
        ReplicationPair(**pair_data(1, scenario_id="SCN_BASE"))


# ============================================================
# REPLICATION SET
# ============================================================

def test_valid_set():
    replication_set = ReplicationSet(**valid_set_data())

    assert replication_set.replication_count == 3


def test_run_id_lists_follow_pair_order():
    replication_set = ReplicationSet(**valid_set_data())

    assert replication_set.baseline_run_ids == [
        "RUN_B_1",
        "RUN_B_2",
        "RUN_B_3",
    ]
    assert replication_set.intervention_run_ids == [
        "RUN_I_1",
        "RUN_I_2",
        "RUN_I_3",
    ]


def test_two_pairs_is_enough():
    replication_set = ReplicationSet(
        **valid_set_data(pairs=[pair_data(1), pair_data(2)])
    )

    assert replication_set.replication_count == 2


def test_ids_are_stripped():
    replication_set = ReplicationSet(
        **valid_set_data(baseline_scenario_id="  SCN_BASE  ")
    )

    assert replication_set.baseline_scenario_id == "SCN_BASE"


@pytest.mark.parametrize(
    "field",
    [
        "replication_set_id",
        "baseline_scenario_id",
        "intervention_scenario_id",
    ],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_set_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(**{field: bad_value}))


def test_same_scenario_twice_rejected():
    with pytest.raises(ValidationError):
        ReplicationSet(
            **valid_set_data(intervention_scenario_id="SCN_BASE")
        )


@pytest.mark.parametrize(
    "pairs",
    [[], [pair_data(1)]],
)
def test_fewer_than_two_pairs_rejected(pairs):
    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(pairs=pairs))


def test_run_reused_in_another_pair_rejected():
    pairs = [
        pair_data(1),
        pair_data(2, baseline_run_id="RUN_B_1"),
    ]

    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(pairs=pairs))


def test_run_used_as_baseline_and_intervention_rejected():
    pairs = [
        pair_data(1),
        pair_data(2, intervention_run_id="RUN_B_1"),
    ]

    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(pairs=pairs))


def test_invalid_pair_inside_set_rejected():
    pairs = [pair_data(1), pair_data(2, intervention_run_id="RUN_B_2")]

    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(pairs=pairs))


def test_set_extra_fields_rejected():
    with pytest.raises(ValidationError):
        ReplicationSet(**valid_set_data(seeds=[42, 73, 105]))
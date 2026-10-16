import pytest
from pydantic import ValidationError

from jaadah.models.network import (
    ApproachLane,
    MovementAttributes,
    MovementControl,
    MovementType,
)


# ============================================================
# MOVEMENT ATTRIBUTES
# ============================================================

def valid_movement_data(**overrides):
    """A valid signalized through movement on the East approach."""

    data = {
        "movement_id": "MOV_E_T",
        "movement_type": "through",
        "control": "signalized",
    }
    data.update(overrides)
    return data


def test_valid_movement_attributes():
    movement = MovementAttributes(**valid_movement_data())

    assert movement.movement_type == MovementType.THROUGH
    assert movement.control == MovementControl.SIGNALIZED


def test_uncontrolled_right_turn():
    movement = MovementAttributes(
        **valid_movement_data(
            movement_id="MOV_E_R",
            movement_type="right",
            control="uncontrolled",
        )
    )

    assert movement.control == MovementControl.UNCONTROLLED


def test_movement_ids_are_stripped():
    movement = MovementAttributes(
        **valid_movement_data(movement_id="  MOV_E_T  ")
    )

    assert movement.movement_id == "MOV_E_T"


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_movement_id_rejected(bad_value):
    with pytest.raises(ValidationError):
        MovementAttributes(**valid_movement_data(movement_id=bad_value))


@pytest.mark.parametrize(
    "field, value",
    [("intersection_id", "INT_01"), ("approach_id", "APP_E")],
)
def test_movement_parent_ids_are_not_fields(field, value):
    """Rule (a): Movement owns the movement's intersection and approach."""

    with pytest.raises(ValidationError):
        MovementAttributes(**valid_movement_data(**{field: value}))


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("movement_type", "u_turn"),
        ("movement_type", "Through"),
        ("control", "signal"),
        ("control", "green"),
    ],
)
def test_invalid_movement_enums_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        MovementAttributes(**valid_movement_data(**{field: bad_value}))


def test_movement_extra_fields_rejected():
    with pytest.raises(ValidationError):
        MovementAttributes(**valid_movement_data(sumo_edge_id="E12"))


# ============================================================
# APPROACH LANE
# ============================================================

def valid_lane_data(**overrides):
    """A valid lane shared by the East through and left movements."""

    data = {
        "approach_id": "APP_E",
        "lane_index": 1,
        "served_movement_ids": ["MOV_E_L", "MOV_E_T"],
        "lane_width_m": 3.5,
        "storage_length_m": 120.0,
    }
    data.update(overrides)
    return data


def test_valid_shared_lane():
    lane = ApproachLane(**valid_lane_data())

    assert lane.served_movement_ids == ["MOV_E_L", "MOV_E_T"]


def test_valid_single_movement_lane():
    lane = ApproachLane(
        **valid_lane_data(served_movement_ids=["MOV_S_T"])
    )

    assert len(lane.served_movement_ids) == 1


def test_storage_length_is_optional():
    lane = ApproachLane(**valid_lane_data(storage_length_m=None))

    assert lane.storage_length_m is None


def test_lane_ids_are_stripped():
    lane = ApproachLane(
        **valid_lane_data(
            approach_id=" APP_E ",
            served_movement_ids=[" MOV_E_L ", "MOV_E_T"],
        )
    )

    assert lane.approach_id == "APP_E"
    assert lane.served_movement_ids == ["MOV_E_L", "MOV_E_T"]


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_approach_id_rejected(bad_value):
    with pytest.raises(ValidationError):
        ApproachLane(**valid_lane_data(approach_id=bad_value))


def test_lane_intersection_id_is_not_a_field():
    """Rule (a): Approach owns the lane's intersection."""

    with pytest.raises(ValidationError):
        ApproachLane(**valid_lane_data(intersection_id="INT_01"))


@pytest.mark.parametrize(
    "bad_value",
    [0, -1, True, False, 1.5],
)
def test_invalid_lane_index_rejected(bad_value):
    with pytest.raises(ValidationError):
        ApproachLane(**valid_lane_data(lane_index=bad_value))


@pytest.mark.parametrize(
    "served_movement_ids",
    [
        [],
        [""],
        ["   "],
        ["MOV_E_T", "MOV_E_T"],
        ["MOV_E_T", " MOV_E_T "],
    ],
)
def test_invalid_served_movements_rejected(served_movement_ids):
    with pytest.raises(ValidationError):
        ApproachLane(
            **valid_lane_data(served_movement_ids=served_movement_ids)
        )


@pytest.mark.parametrize(
    "field",
    ["lane_width_m", "storage_length_m"],
)
@pytest.mark.parametrize(
    "bad_value",
    [0, -3.5, float("nan"), float("inf")],
)
def test_invalid_lengths_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        ApproachLane(**valid_lane_data(**{field: bad_value}))


def test_lane_width_is_required():
    data = valid_lane_data()
    del data["lane_width_m"]

    with pytest.raises(ValidationError):
        ApproachLane(**data)


def test_lane_extra_fields_rejected():
    with pytest.raises(ValidationError):
        ApproachLane(**valid_lane_data(sumo_lane_id="E12_0"))
import pytest

from backend.analytics.kpi.lane_groups import LaneGroup, derive_lane_groups
from jaadah.models.network import (
    ApproachLane,
    MovementAttributes,
    MovementControl,
    MovementType,
)


def attributes(movement_id, movement_type, control="signalized"):
    return MovementAttributes(
        movement_id=movement_id,
        movement_type=movement_type,
        control=control,
    )


ATTRIBUTES = [
    attributes("MOV_E_L", MovementType.LEFT),
    attributes("MOV_E_T", MovementType.THROUGH),
    attributes("MOV_E_R", MovementType.RIGHT),
    attributes("MOV_S_T", MovementType.THROUGH),
    attributes("MOV_S_R", MovementType.RIGHT, MovementControl.UNCONTROLLED),
]


def lane(lane_id, lane_index, served, approach_id="APP_E"):
    return ApproachLane(
        lane_id=lane_id,
        approach_id=approach_id,
        lane_index=lane_index,
        served_movement_ids=served,
        lane_width_m=3.5,
    )


def east_layout():
    """Left, shared left-through, three through lanes."""

    return [
        lane("LANE_E_1", 1, ["MOV_E_L"]),
        lane("LANE_E_2", 2, ["MOV_E_L", "MOV_E_T"]),
        lane("LANE_E_3", 3, ["MOV_E_T"]),
        lane("LANE_E_4", 4, ["MOV_E_T"]),
        lane("LANE_E_5", 5, ["MOV_E_T"]),
    ]


def groups_by_id(lanes, movement_attributes=ATTRIBUTES):
    return {
        group.lane_group_id: group
        for group in derive_lane_groups(lanes, movement_attributes)
    }


# ============================================================
# FORMING LANE GROUPS
# ============================================================

def test_east_layout_gives_three_groups():
    groups = derive_lane_groups(east_layout(), ATTRIBUTES)

    assert groups == [
        LaneGroup("APP_E_L", "APP_E", ("LANE_E_1",), frozenset({"MOV_E_L"})),
        LaneGroup(
            "APP_E_LT",
            "APP_E",
            ("LANE_E_2",),
            frozenset({"MOV_E_L", "MOV_E_T"}),
        ),
        LaneGroup(
            "APP_E_T",
            "APP_E",
            ("LANE_E_3", "LANE_E_4", "LANE_E_5"),
            frozenset({"MOV_E_T"}),
        ),
    ]


def test_adjacent_lanes_of_same_movement_form_one_group():
    groups = groups_by_id(east_layout())

    assert groups["APP_E_T"].lane_count == 3


def test_shared_lane_is_its_own_group():
    groups = groups_by_id(east_layout())

    assert groups["APP_E_LT"].lane_ids == ("LANE_E_2",)
    assert groups["APP_E_LT"].is_shared


def test_single_movement_group_is_not_shared():
    groups = groups_by_id(east_layout())

    assert not groups["APP_E_T"].is_shared


def test_lane_input_order_does_not_matter():
    groups = derive_lane_groups(list(reversed(east_layout())), ATTRIBUTES)

    assert [g.lane_group_id for g in groups] == [
        "APP_E_L",
        "APP_E_LT",
        "APP_E_T",
    ]
    assert groups[2].lane_ids == ("LANE_E_3", "LANE_E_4", "LANE_E_5")


def test_lanes_with_a_gap_are_separate_groups():
    """Through lanes 1 and 3 with no lane 2 are not adjacent."""

    lanes = [
        lane("LANE_E_1", 1, ["MOV_E_T"]),
        lane("LANE_E_3", 3, ["MOV_E_T"]),
    ]

    with pytest.raises(ValueError, match="two lane groups named APP_E_T"):
        derive_lane_groups(lanes, ATTRIBUTES)


def test_approaches_are_separate_and_ordered():
    lanes = [
        lane("LANE_S_1", 1, ["MOV_S_T"], approach_id="APP_S"),
        *east_layout(),
    ]

    groups = derive_lane_groups(lanes, ATTRIBUTES)

    assert [g.approach_id for g in groups] == [
        "APP_E", "APP_E", "APP_E", "APP_S",
    ]


def test_no_lanes_gives_no_groups():
    assert derive_lane_groups([], ATTRIBUTES) == []


# ============================================================
# LANE GROUP IDS
# ============================================================

@pytest.mark.parametrize(
    "served, expected_id",
    [
        (["MOV_E_L"], "APP_E_L"),
        (["MOV_E_T"], "APP_E_T"),
        (["MOV_E_R"], "APP_E_R"),
        (["MOV_E_T", "MOV_E_L"], "APP_E_LT"),
        (["MOV_E_R", "MOV_E_T"], "APP_E_TR"),
        (["MOV_E_R", "MOV_E_L", "MOV_E_T"], "APP_E_LTR"),
    ],
)
def test_letters_always_in_order_l_t_r(served, expected_id):
    groups = derive_lane_groups([lane("LANE_E_1", 1, served)], ATTRIBUTES)

    assert groups[0].lane_group_id == expected_id


def test_id_does_not_change_when_a_lane_is_added():
    four_lanes = east_layout()[:4]
    five_lanes = east_layout()

    assert set(groups_by_id(four_lanes)) == set(groups_by_id(five_lanes))


# ============================================================
# UNCONTROLLED (SLIP) LANES
# ============================================================

def test_slip_lane_belongs_to_no_group():
    lanes = [
        lane("LANE_S_1", 1, ["MOV_S_T"], approach_id="APP_S"),
        lane("LANE_S_2", 2, ["MOV_S_T"], approach_id="APP_S"),
        lane("LANE_S_3", 3, ["MOV_S_R"], approach_id="APP_S"),
    ]

    groups = derive_lane_groups(lanes, ATTRIBUTES)

    assert [g.lane_group_id for g in groups] == ["APP_S_T"]
    assert "LANE_S_3" not in groups[0].lane_ids


def test_approach_with_only_slip_lanes_has_no_groups():
    lanes = [lane("LANE_S_3", 3, ["MOV_S_R"], approach_id="APP_S")]

    assert derive_lane_groups(lanes, ATTRIBUTES) == []


# ============================================================
# INPUT CHECKS
# ============================================================

def test_movement_without_attributes_rejected():
    with pytest.raises(ValueError, match="MOV_X, which has no"):
        derive_lane_groups([lane("LANE_E_1", 1, ["MOV_X"])], ATTRIBUTES)


def test_lane_mixing_signalized_and_uncontrolled_rejected():
    lanes = [
        lane("LANE_S_2", 2, ["MOV_S_T", "MOV_S_R"], approach_id="APP_S"),
    ]

    with pytest.raises(ValueError, match="LANE_S_2 mixes signalized"):
        derive_lane_groups(lanes, ATTRIBUTES)


def test_duplicate_lane_index_rejected():
    lanes = [
        lane("LANE_E_1", 1, ["MOV_E_L"]),
        lane("LANE_E_1B", 1, ["MOV_E_T"]),
    ]

    with pytest.raises(ValueError, match="two lanes with the same lane_index"):
        derive_lane_groups(lanes, ATTRIBUTES)


def test_same_lane_index_on_different_approaches_allowed():
    lanes = [
        lane("LANE_E_1", 1, ["MOV_E_T"]),
        lane("LANE_S_1", 1, ["MOV_S_T"], approach_id="APP_S"),
    ]

    assert len(derive_lane_groups(lanes, ATTRIBUTES)) == 2


def test_duplicate_group_id_rejected():
    """Through, left, through: two separate APP_E_T groups."""

    lanes = [
        lane("LANE_E_1", 1, ["MOV_E_T"]),
        lane("LANE_E_2", 2, ["MOV_E_L"]),
        lane("LANE_E_3", 3, ["MOV_E_T"]),
    ]

    with pytest.raises(ValueError, match="two lane groups named APP_E_T"):
        derive_lane_groups(lanes, ATTRIBUTES)


def test_two_adjacent_shared_lanes_rejected():
    """Each shared lane is its own group, so both would be APP_E_LT."""

    lanes = [
        lane("LANE_E_1", 1, ["MOV_E_L", "MOV_E_T"]),
        lane("LANE_E_2", 2, ["MOV_E_L", "MOV_E_T"]),
    ]

    with pytest.raises(ValueError, match="two lane groups named APP_E_LT"):
        derive_lane_groups(lanes, ATTRIBUTES)
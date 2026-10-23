"""
HCM lane groups, derived from the approach lanes.

A lane group is a set of adjacent lanes on one approach that serve
the same movements. A lane shared by several movements is always its
own lane group. Lanes of uncontrolled movements (right-turn slip
lanes) belong to no lane group, because capacity and v/c do not apply
to them.

Lane groups are derived each time from the ApproachLane records, not
stored. Their IDs are the approach ID plus the letters of the
movements served, always in the order L, T, R (e.g. APP_E_LT).
"""

from typing import NamedTuple

from jaadah.models.network import (
    ApproachLane,
    MovementAttributes,
    MovementControl,
    MovementType,
)


MOVEMENT_LETTERS = {
    MovementType.LEFT: "L",
    MovementType.THROUGH: "T",
    MovementType.RIGHT: "R",
}


class LaneGroup(NamedTuple):
    """One HCM lane group."""

    lane_group_id: str
    approach_id: str
    lane_ids: tuple[str, ...]
    movement_ids: frozenset[str]

    @property
    def lane_count(self) -> int:
        return len(self.lane_ids)

    @property
    def is_shared(self) -> bool:
        return len(self.movement_ids) > 1


def derive_lane_groups(
    lanes: list[ApproachLane],
    movement_attributes: list[MovementAttributes],
) -> list[LaneGroup]:
    """
    Build the lane groups of every approach, ordered by approach and
    then from the median outwards.

    Raises ValueError when a lane serves a movement without
    MovementAttributes, mixes signalized and uncontrolled movements,
    two lanes of an approach have the same lane_index, or two lane
    groups of an approach would get the same ID.
    """

    attributes = {a.movement_id: a for a in movement_attributes}

    lanes_by_approach: dict[str, list[ApproachLane]] = {}

    for lane in lanes:
        lanes_by_approach.setdefault(lane.approach_id, []).append(lane)

    groups = []

    for approach_id in sorted(lanes_by_approach):
        groups.extend(
            _approach_lane_groups(
                approach_id, lanes_by_approach[approach_id], attributes
            )
        )

    return groups


def _approach_lane_groups(
    approach_id: str,
    lanes: list[ApproachLane],
    attributes: dict[str, MovementAttributes],
) -> list[LaneGroup]:
    """Build the lane groups of one approach."""

    ordered = sorted(lanes, key=lambda lane: lane.lane_index)

    indexes = [lane.lane_index for lane in ordered]

    if len(indexes) != len(set(indexes)):
        raise ValueError(
            f"approach {approach_id} has two lanes with the same lane_index"
        )

    signalized = [
        lane for lane in ordered if _is_signalized(lane, attributes)
    ]

    # Each run is a list of adjacent lanes serving the same movements.
    runs: list[list[ApproachLane]] = []

    for lane in signalized:
        if runs and _continues_run(runs[-1], lane):
            runs[-1].append(lane)
        else:
            runs.append([lane])

    groups = []
    seen_ids = set()

    for run in runs:
        movement_ids = frozenset(run[0].served_movement_ids)
        lane_group_id = _lane_group_id(approach_id, movement_ids, attributes)

        if lane_group_id in seen_ids:
            raise ValueError(
                f"approach {approach_id} would have two lane groups "
                f"named {lane_group_id}"
            )

        seen_ids.add(lane_group_id)

        groups.append(
            LaneGroup(
                lane_group_id=lane_group_id,
                approach_id=approach_id,
                lane_ids=tuple(lane.lane_id for lane in run),
                movement_ids=movement_ids,
            )
        )

    return groups


def _is_signalized(
    lane: ApproachLane,
    attributes: dict[str, MovementAttributes],
) -> bool:
    """
    True when every movement of the lane is signalized, False when
    every movement is uncontrolled. A mix is an error.
    """

    controls = set()

    for movement_id in lane.served_movement_ids:
        if movement_id not in attributes:
            raise ValueError(
                f"lane {lane.lane_id} serves movement {movement_id}, "
                "which has no MovementAttributes"
            )

        controls.add(attributes[movement_id].control)

    if len(controls) > 1:
        raise ValueError(
            f"lane {lane.lane_id} mixes signalized and uncontrolled "
            "movements"
        )

    return controls == {MovementControl.SIGNALIZED}


def _continues_run(run: list[ApproachLane], lane: ApproachLane) -> bool:
    """
    True when the lane joins the previous lanes' group: it is the next
    lane outwards, serves the same movements, and neither is shared.
    """

    previous = run[-1]

    return (
        lane.lane_index == previous.lane_index + 1
        and set(lane.served_movement_ids) == set(previous.served_movement_ids)
        and len(lane.served_movement_ids) == 1
    )


def _lane_group_id(
    approach_id: str,
    movement_ids: frozenset[str],
    attributes: dict[str, MovementAttributes],
) -> str:
    """Approach ID plus the movement letters in the order L, T, R."""

    types = {attributes[m].movement_type for m in movement_ids}

    letters = "".join(
        letter
        for movement_type, letter in MOVEMENT_LETTERS.items()
        if movement_type in types
    )

    return f"{approach_id}_{letters}"
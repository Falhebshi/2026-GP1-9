"""
The network inputs of the KPI engine, taken from the network mapping.

The engine works on canonical models and reads no files. This module
turns a loaded NetworkMappingConfig into the three network inputs the
engine functions take: the approach lanes, the analysed movements and
their movement attributes.

Rules applied, and why:

- Analysed movements only: the movements with MovementAttributes. Ramp,
  U-turn and tunnel movements have none and no KPIs, so they are left
  out.
- Completeness: the mapping accepts drafts, in which some attributes are
  missing; the engine cannot. Every movement served by an approach lane
  must have attributes, and every analysed movement must be served by
  at least one approach lane, otherwise it has no lane group, capacity
  or queue. A draft is rejected with every gap listed, instead of the
  engine failing later on the first one.
"""

from typing import NamedTuple

from ..models.mappings import NetworkMappingConfig
from ..models.network import ApproachLane, Movement, MovementAttributes


class NetworkInputsError(ValueError):
    """Raised when the mapping cannot supply the engine; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot prepare the KPI network inputs:\n" + "\n".join(problems))


class NetworkInputs(NamedTuple):
    """The network inputs of the KPI engine."""

    lanes: list[ApproachLane]
    movements: dict[str, Movement]
    movement_attributes: dict[str, MovementAttributes]


def build_network_inputs(config: NetworkMappingConfig) -> NetworkInputs:
    """The engine's lanes, analysed movements and movement attributes."""

    attributes = {item.movement_id: item for item in config.movement_attributes}
    served = {m for lane in config.approach_lanes for m in lane.served_movement_ids}

    problems = [
        f"{movement_id}: served by an approach lane but has no movement attributes"
        for movement_id in sorted(served - set(attributes))
    ]
    problems += [
        f"{movement_id}: has movement attributes but no approach lane serves it"
        for movement_id in sorted(set(attributes) - served)
    ]
    if problems:
        raise NetworkInputsError(problems)

    canonical = config.canonical_movements
    return NetworkInputs(
        lanes=list(config.approach_lanes),
        movements={movement_id: canonical[movement_id] for movement_id in attributes},
        movement_attributes=attributes,
    )

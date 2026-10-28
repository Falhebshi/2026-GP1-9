"""
Build the approaches of the study intersection and their movements, for
the approach chips and details of the frontend.

Usage (from the repository root):
    python simulation/scene_3d/build_approaches.py <out approaches.json>

Every approach lists the movements that have KPIs (the ones with
movement attributes in the network mappings), with their type and
control, so the page can name them ("Left turn", "Right turn (slip
lane)"). U-turns, ramps and the tunnel have no KPIs and are left out.
The file holds no SUMO IDs.
"""

import argparse
import json
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(REPO_ROOT))

from jaadah.mapping.loader import (  # noqa: E402
    load_network_mappings,
)
from jaadah.models.mappings import (  # noqa: E402
    NetworkMappingConfig,
)


MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)

# The road each approach comes from. The network mappings have no road
# names, and the street names in the SUMO network can't be used: the
# first edge of the west approach carries the name of another street,
# and the south approach has none. These are the names the page showed
# before this file.
ROAD_OF_SIDE = {
    "east": "Imam Saud Rd",
    "west": "Imam Saud Rd",
    "north": "Prince Turki Rd, service road",
    "south": "Prince Turki Rd, service road",
}

# Left, through, right: the order of the turn arrows on the page
TYPE_ORDER = {
    "left": 0,
    "through": 1,
    "right": 2,
}


def build_approaches(
    config: NetworkMappingConfig,
) -> dict:
    """Return the approaches of the study intersection with their movements."""

    approach_of_movement = {
        movement.movement_id: movement.approach_id
        for movement in config.movement_mappings
    }
    movements_of_approach: dict[str, list[dict]] = {}

    for attributes in config.movement_attributes:
        approach_id = approach_of_movement[attributes.movement_id]
        movements = movements_of_approach.setdefault(
            approach_id,
            [],
        )
        movements.append(
            {
                "movement_id": attributes.movement_id,
                "movement_type": attributes.movement_type.value,
                "control": attributes.control.value,
            }
        )

    approaches = []

    for approach in sorted(
        config.approach_mappings,
        key=lambda item: item.approach_id,
    ):
        side = approach.approach_side.value
        movements = movements_of_approach.get(approach.approach_id, [])

        approaches.append(
            {
                "approach_id": approach.approach_id,
                "side": side,
                "road": ROAD_OF_SIDE[side],
                "movements": sorted(
                    movements,
                    key=lambda item: TYPE_ORDER[item["movement_type"]],
                ),
            }
        )

    return {
        "intersection_id": config.intersection_mapping.intersection_id,
        "approaches": approaches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[0],
    )
    parser.add_argument(
        "output",
        type=Path,
    )
    args = parser.parse_args()

    approaches = build_approaches(
        config=load_network_mappings(
            file_path=MAPPING_PATH,
        ),
    )

    with args.output.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            approaches,
            file,
            indent=2,
        )
        file.write("\n")

    for approach in approaches["approaches"]:
        movement_ids = [
            movement["movement_id"]
            for movement in approach["movements"]
        ]

        print(
            f"{approach['approach_id']} ({approach['road']}): "
            + ", ".join(movement_ids)
        )


if __name__ == "__main__":
    main()

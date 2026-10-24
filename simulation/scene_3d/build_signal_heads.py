"""
Build the positions of the signal heads of the 3D view, grouped by
approach, from the SUMO network and the network mappings.

Usage (from the repository root):
    python simulation/scene_3d/build_signal_heads.py <out signal_heads.json>

Every approach lists its movements and, for each of its lanes at the
stop line (rightmost lane first), the drawn lane it belongs to, where
the head stands, the direction of travel and the lane width. The 3D view colours all heads of an
approach with the indication of its movements, so it needs no SUMO
link numbers.
"""

import argparse
import json
import sys
from pathlib import Path

import sumolib


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(REPO_ROOT))

from backend.outputs.signals import find_signal_links  # noqa: E402
from jaadah.mapping.loader import load_network_mappings  # noqa: E402
from jaadah.models.mappings import NetworkMappingConfig  # noqa: E402


# Project data paths
NETWORK_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "jaadah_study_area.net.xml"
)

MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)


def to_lon_lat(
    net,
    x: float,
    y: float,
) -> list[float]:
    """Return SUMO x, y metres as [longitude, latitude]."""

    longitude, latitude = net.convertXY2LonLat(x, y)

    return [round(longitude, 7), round(latitude, 7)]


def build_signal_heads(
    net,
    config: NetworkMappingConfig,
) -> dict:
    """Return the signal heads of the study intersection by approach."""

    movement_of_link = {
        link: movement_id
        for movement_id, links in find_signal_links(config).items()
        for link in links
    }
    approach_of_movement = {
        movement.movement_id: movement.approach_id
        for movement in config.movement_mappings
    }
    side_of_approach = {
        approach.approach_id: approach.approach_side.value
        for approach in config.approach_mappings
    }

    tls = net.getTLS(config.intersection_mapping.sumo_tls_id)
    approaches: dict[str, dict] = {}

    for in_lane, _, link in tls.getConnections():
        movement_id = movement_of_link[link]
        approach_id = approach_of_movement[movement_id]
        approach = approaches.setdefault(
            approach_id,
            {
                "approach_id": approach_id,
                "side": side_of_approach[approach_id],
                "movement_ids": set(),
                "lanes": {},
            },
        )
        approach["movement_ids"].add(movement_id)

        (x1, y1), (x2, y2) = in_lane.getShape()[-2:]
        approach["lanes"][in_lane.getIndex()] = {
            "lane_id": in_lane.getID(),
            "position": to_lon_lat(net, x2, y2),
            "toward": to_lon_lat(
                net,
                x2 + (x2 - x1) * 0.01,
                y2 + (y2 - y1) * 0.01,
            ),
            "width_m": round(in_lane.getWidth(), 2),
        }

    return {
        "intersection_id": config.intersection_mapping.intersection_id,
        "approaches": [
            {
                **approach,
                "movement_ids": sorted(approach["movement_ids"]),
                "lanes": [
                    approach["lanes"][index]
                    for index in sorted(approach["lanes"])
                ],
            }
            for _, approach in sorted(approaches.items())
        ],
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

    heads = build_signal_heads(
        net=sumolib.net.readNet(str(NETWORK_PATH)),
        config=load_network_mappings(MAPPING_PATH),
    )

    with args.output.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            heads,
            file,
            separators=(",", ":"),
        )

    for approach in heads["approaches"]:
        print(
            f"{approach['approach_id']}: {len(approach['lanes'])} heads, "
            + ", ".join(approach["movement_ids"])
        )


if __name__ == "__main__":
    main()

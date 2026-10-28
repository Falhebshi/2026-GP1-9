import sys

import sumolib

from backend.outputs.intersections import REPO_ROOT
from jaadah.mapping.loader import load_network_mappings


SCRIPTS_DIR = REPO_ROOT / "simulation" / "scene_3d"

sys.path.insert(0, str(SCRIPTS_DIR))

from build_signal_heads import (  # noqa: E402
    MAPPING_PATH,
    NETWORK_PATH,
    build_signal_heads,
)


def study_signal_heads() -> dict:
    """Build the signal heads of the study intersection."""

    return build_signal_heads(
        net=sumolib.net.readNet(str(NETWORK_PATH)),
        config=load_network_mappings(MAPPING_PATH),
    )


def test_every_approach_has_its_movements_and_lanes() -> None:
    heads = study_signal_heads()

    assert heads["intersection_id"] == "INT_001"
    assert {
        approach["approach_id"]: (
            approach["side"],
            approach["movement_ids"],
            len(approach["lanes"]),
        )
        for approach in heads["approaches"]
    } == {
        "APP_E": ("east", ["MOV_E_S", "MOV_E_W"], 4),
        "APP_N": ("north", ["MOV_N_E"], 3),
        "APP_S": ("south", ["MOV_S_W"], 2),
        "APP_W": ("west", ["MOV_W_E", "MOV_W_N"], 3),
    }


def test_heads_stand_at_the_stop_line_near_the_junction() -> None:
    heads = study_signal_heads()
    center_longitude, center_latitude = 46.633641, 24.735316

    for approach in heads["approaches"]:
        for lane in approach["lanes"]:
            longitude, latitude = lane["position"]

            assert abs(longitude - center_longitude) < 0.0005
            assert abs(latitude - center_latitude) < 0.0005
            assert lane["width_m"] > 0

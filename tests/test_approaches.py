import json
import sys

from backend.outputs.intersections import (
    REPO_ROOT,
)
from jaadah.mapping.loader import (
    load_network_mappings,
)


SCRIPTS_DIR = REPO_ROOT / "simulation" / "scene_3d"

sys.path.insert(0, str(SCRIPTS_DIR))

from build_approaches import (  # noqa: E402
    MAPPING_PATH,
    build_approaches,
)


FRONTEND_COPY_PATH = (
    REPO_ROOT
    / "frontend"
    / "public"
    / "data"
    / "INT_001"
    / "network"
    / "approaches.json"
)


def study_approaches() -> dict:
    """Build the approaches of the study intersection."""

    return build_approaches(
        config=load_network_mappings(
            file_path=MAPPING_PATH,
        ),
    )


def test_every_approach_has_its_movements_left_to_right() -> None:
    approaches = study_approaches()

    assert approaches["intersection_id"] == "INT_001"
    assert {
        approach["approach_id"]: (
            approach["side"],
            [
                (
                    movement["movement_id"],
                    movement["movement_type"],
                    movement["control"],
                )
                for movement in approach["movements"]
            ],
        )
        for approach in approaches["approaches"]
    } == {
        "APP_E": (
            "east",
            [
                ("MOV_E_S", "left", "signalized"),
                ("MOV_E_W", "through", "signalized"),
            ],
        ),
        "APP_N": (
            "north",
            [
                ("MOV_N_E", "left", "signalized"),
                ("MOV_N_W_SLIP", "right", "uncontrolled"),
            ],
        ),
        "APP_S": (
            "south",
            [
                ("MOV_S_W", "left", "signalized"),
                ("MOV_S_E_BYPASS", "right", "uncontrolled"),
            ],
        ),
        "APP_W": (
            "west",
            [
                ("MOV_W_N", "left", "signalized"),
                ("MOV_W_E", "through", "signalized"),
                ("MOV_W_S_SLIP", "right", "uncontrolled"),
            ],
        ),
    }


def test_only_movements_with_kpis_are_listed() -> None:
    config = load_network_mappings(
        file_path=MAPPING_PATH,
    )
    listed = {
        movement["movement_id"]
        for approach in study_approaches()["approaches"]
        for movement in approach["movements"]
    }

    assert listed == {
        attributes.movement_id
        for attributes in config.movement_attributes
    }


def test_every_approach_has_a_road_name() -> None:
    for approach in study_approaches()["approaches"]:
        assert approach["road"]


def test_file_has_no_sumo_ids() -> None:
    config = load_network_mappings(
        file_path=MAPPING_PATH,
    )
    sumo_ids = {config.intersection_mapping.sumo_tls_id}

    for movement in config.movement_mappings:
        sumo_ids.update(movement.sumo_route_edge_ids)

    for lane in config.lane_mappings:
        sumo_ids.update(lane.sumo_lane_ids)

    text = json.dumps(
        study_approaches(),
    )

    assert not [
        sumo_id
        for sumo_id in sumo_ids
        if f'"{sumo_id}"' in text
    ]


def test_frontend_copy_is_up_to_date() -> None:
    with FRONTEND_COPY_PATH.open(
        encoding="utf-8",
    ) as file:
        frontend_copy = json.load(file)

    assert frontend_copy == study_approaches()

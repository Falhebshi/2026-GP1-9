"""
The frontend holds no SUMO knowledge (M10-D, task 9).

The traffic files the website reads (the run, its vehicles, signal
indications and KPI results, the approaches and the intersection) use
only Jaadah IDs. The 3D road drawing is the one agreed exception: its
drawn lanes and roads are tagged with their SUMO lane and edge IDs, so
the view can connect lanes, arrows and signal heads. Those tags are
display-only and may appear only under the drawing's tag keys.
"""

import json
import re
from pathlib import Path

import sumolib

from backend.outputs.intersections import (
    REPO_ROOT,
)


FRONTEND_DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"

NETWORK_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "jaadah_study_area.net.xml"
)

# The keys that tag a drawn lane or road in the 3D road drawing
DRAWING_TAG_KEYS = {
    "edge",
    "id",
    "lane",
    "lane_id",
}

# A SUMO signal state string, e.g. "GGrryy"
SIGNAL_STATE = re.compile(r"[GgyrRuoOs]{4,}")


def sumo_ids() -> set[str]:
    """Return every edge, lane and traffic light ID of the SUMO network."""

    net = sumolib.net.readNet(
        str(NETWORK_PATH),
        withInternal=True,
    )
    ids = {
        light.getID()
        for light in net.getTrafficLights()
    }

    for edge in net.getEdges(withInternal=True):
        ids.add(edge.getID())
        ids.update(
            lane.getID()
            for lane in edge.getLanes()
        )

    return ids


def traffic_files() -> list[Path]:
    """Return the traffic files the website reads."""

    files = [
        FRONTEND_DATA_DIR / "intersections.json",
    ]

    for intersection_dir in FRONTEND_DATA_DIR.iterdir():
        if not intersection_dir.is_dir():
            continue

        files.append(intersection_dir / "network" / "approaches.json")

        for scenario_dir in intersection_dir.iterdir():
            if scenario_dir.name != "network":
                files.extend(sorted(scenario_dir.glob("*.json")))

    return files


def drawing_files() -> list[Path]:
    """Return the files of the 3D road drawing."""

    files = []

    for network_dir in FRONTEND_DATA_DIR.glob("*/network"):
        files.extend(sorted(network_dir.glob("*.geojson")))
        files.append(network_dir / "signal_heads.json")

    return files


def strings_with_keys(
    value,
    key: str | None = None,
):
    """Yield every text in a JSON value, with the key it is stored under."""

    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from strings_with_keys(
                value=child,
                key=child_key,
            )
    elif isinstance(value, list):
        for child in value:
            yield from strings_with_keys(
                value=child,
                key=key,
            )
    elif isinstance(value, str):
        yield key, value


def load(
    path: Path,
):
    """Load one JSON file."""

    with path.open(
        encoding="utf-8",
    ) as file:
        return json.load(file)


def test_traffic_files_have_no_sumo_ids_or_signal_strings() -> None:
    ids = sumo_ids()
    found = []

    for path in traffic_files():
        for key, text in strings_with_keys(
            value=load(
                path=path,
            ),
        ):
            if text in ids or SIGNAL_STATE.fullmatch(text):
                found.append(
                    f"{path.relative_to(FRONTEND_DATA_DIR)}: {key}={text}"
                )

    assert not found


def test_road_drawing_keeps_sumo_ids_to_its_tags() -> None:
    ids = sumo_ids()
    found = []

    for path in drawing_files():
        for key, text in strings_with_keys(
            value=load(
                path=path,
            ),
        ):
            if text in ids and key not in DRAWING_TAG_KEYS:
                found.append(
                    f"{path.relative_to(FRONTEND_DATA_DIR)}: {key}={text}"
                )

    assert not found


def test_every_traffic_file_is_checked() -> None:
    names = {
        path.name
        for path in traffic_files()
    }

    assert {
        "intersections.json",
        "approaches.json",
        "run.json",
        "signals.json",
        "kpis.json",
        "vehicles_0800.json",
    } <= names

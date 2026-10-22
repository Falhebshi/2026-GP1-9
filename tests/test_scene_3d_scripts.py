import ast
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "simulation" / "scene_3d"
RAW_BUILDINGS_DIR = REPO_ROOT / "data" / "raw" / "buildings"
OSM_FILE = REPO_ROOT / "data" / "raw" / "road_network" / "jaadah_study_area.osm"


def find_open_calls_without_utf8(path: Path) -> list[int]:
    """Return the line numbers of open() calls that do not set encoding="utf-8"."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ):
            continue

        encoding = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "encoding"
            ),
            None,
        )

        if not (
            isinstance(encoding, ast.Constant)
            and encoding.value == "utf-8"
        ):
            missing.append(node.lineno)

    return missing


def non_utf8_environment() -> dict:
    """
    Return an environment whose default file encoding is not UTF-8, like
    Windows, so a missing encoding="utf-8" fails here too.
    """

    env = dict(os.environ)
    env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": "0",
        }
    )

    return env


def test_every_script_opens_files_as_utf8() -> None:
    missing = {
        path.name: lines
        for path in sorted(SCRIPTS_DIR.glob("*.py"))
        if (lines := find_open_calls_without_utf8(path))
    }

    assert missing == {}


def test_merge_buildings_reads_committed_sources_without_utf8_locale(
    tmp_path: Path,
) -> None:
    osm_buildings = tmp_path / "buildings_osm.geojson"
    buildings = tmp_path / "buildings.geojson"

    subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "extract_buildings.py"),
            str(OSM_FILE),
            str(osm_buildings),
        ],
        cwd=SCRIPTS_DIR,
        env=non_utf8_environment(),
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8=0",
            str(SCRIPTS_DIR / "merge_buildings.py"),
            str(osm_buildings),
            str(RAW_BUILDINGS_DIR / "overture_buildings.geojson"),
            str(RAW_BUILDINGS_DIR / "landmarks_traced.geojson"),
            str(buildings),
        ],
        cwd=SCRIPTS_DIR,
        env=non_utf8_environment(),
        check=True,
        capture_output=True,
    )

    features = json.loads(
        buildings.read_text(encoding="utf-8")
    )["features"]

    assert len(features) == 900

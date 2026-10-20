"""
Build the data the 3D intersection view reads (frontend/public/data/<intersection>/) from the
SUMO network, the OpenStreetMap extract and the building sources.

Usage (from the repository root):
    python simulation/scene_3d/build_all.py
    python simulation/scene_3d/build_all.py --with-sim

The first form rebuilds the static layers (roads, markings, underpass, sidewalks, background,
buildings). --with-sim also runs SUMO with the test demand and rebuilds the vehicles and signal
states (needs the sumo command, from an installed SUMO or the eclipse-sumo package).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[1]

NET = REPO / "data/processed/road_network/jaadah_study_area.net.xml"
OSM = REPO / "data/raw/road_network/jaadah_study_area.osm"
OVERTURE = REPO / "data/raw/buildings/overture_buildings.geojson"
LANDMARKS = REPO / "data/raw/buildings/landmarks_traced.geojson"
ROUTES = REPO / "simulation/scenarios/tests/stress_test_v2.rou.xml"
OUT = REPO / "frontend/public/data/turki_imamsaud"

# vehicles and signal states are kept for this part of the run, in seconds
SIM_BEGIN = 0
SIM_END = 600
RECORD_FROM = 60
RECORD_TO = 420


def run(script: str, *args) -> None:
    """Run one build script with this Python and stop if it fails."""

    print(f"> {script}")
    subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        cwd=SCRIPTS,
        check=True,
    )


def build_static_layers(network_dir: Path) -> None:
    """Rebuild every layer that depends only on the network, OSM and building sources."""

    network_dir.mkdir(parents=True, exist_ok=True)
    surface = network_dir / "road_surface.geojson"
    underpass = network_dir / "underpass.geojson"
    streetscape = network_dir / "streetscape.geojson"
    buildings = network_dir / "buildings.geojson"

    with tempfile.TemporaryDirectory() as tmp:
        osm_buildings = Path(tmp) / "buildings_osm.geojson"
        run("extract_buildings.py", OSM, osm_buildings)
        run("merge_buildings.py", osm_buildings, OVERTURE, LANDMARKS, buildings)

    # the underpass is built from the road surface, and the road markings need the underpass,
    # so the road layers are built twice
    if underpass.exists():
        underpass.unlink()
    run("build_network_layers.py", NET, OSM, network_dir)
    run("build_underpass.py", NET, OSM, surface, underpass)
    run("build_network_layers.py", NET, OSM, network_dir, underpass)

    run("build_streetscape.py", NET, surface, underpass, streetscape)
    run("build_context.py", OSM, NET, surface, network_dir / "context.geojson")
    run(
        "build_surface_detail.py",
        NET,
        OSM,
        surface,
        streetscape,
        buildings,
        network_dir / "surface_detail.geojson",
    )


def find_sumo() -> str:
    """Return the sumo command from SUMO_HOME, the PATH or the eclipse-sumo package."""

    if os.environ.get("SUMO_HOME"):
        return str(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")
    if shutil.which("sumo"):
        return "sumo"
    try:
        import sumo

        return str(Path(sumo.SUMO_HOME) / "bin" / "sumo")
    except ImportError:
        sys.exit("sumo was not found: install SUMO or run pip install eclipse-sumo")


def build_simulation(scenario_dir: Path) -> None:
    """Run SUMO with the test demand and convert its output for the 3D view."""

    scenario_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(SCRIPTS / "tls_record.add.xml", tmp)
        print("> sumo")
        subprocess.run(
            [
                find_sumo(),
                "-n", str(NET),
                "-r", str(ROUTES),
                "-a", "tls_record.add.xml",
                "-b", str(SIM_BEGIN),
                "-e", str(SIM_END),
                "--step-length", "0.2",
                "--lanechange.duration", "2",
                "--seed", "42",
                "--fcd-output", "fcd.xml",
                "--fcd-output.geo",
                "--fcd-output.signals",
                "--device.fcd.begin", str(RECORD_FROM),
                "--device.fcd.period", "0.4",
                "--no-step-log",
            ],
            cwd=tmp,
            check=True,
        )
        run(
            "convert_sim.py",
            NET,
            OSM,
            tmp / "fcd.xml",
            tmp / "tls_states.xml",
            scenario_dir,
            RECORD_FROM,
            RECORD_TO,
            "SUMO run on the study-area network with the Stress Test v2 test demand",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument(
        "--with-sim",
        action="store_true",
        help="also run SUMO and rebuild the vehicles and signal states",
    )
    args = parser.parse_args()

    build_static_layers(OUT / "network")
    if args.with_sim:
        build_simulation(OUT / "baseline")

    print(f"Done: {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()

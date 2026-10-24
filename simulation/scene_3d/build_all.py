"""
Build the static layers the 3D intersection view reads (frontend/public/data/<intersection>/network/)
from the SUMO network, the network mappings, the OpenStreetMap extract and the building sources:
roads, markings, underpass, sidewalks, background, buildings and signal heads.

Usage (from the repository root):
    python simulation/scene_3d/build_all.py

The vehicles and signal indications come from a simulation run: see build_playback.py.
"""

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
OUT = REPO / "frontend/public/data/INT_001"


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
    run("build_signal_heads.py", network_dir / "signal_heads.json")
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


def main() -> None:
    build_static_layers(OUT / "network")
    print(f"Done: {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()

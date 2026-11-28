"""
Draw the main roads around the study intersection for the Login page.

The Login page shows Jaadah's own road network behind its name: the
segments of the network map near the study intersection, coloured like
the map. The colours come from each segment's estimated share of city
traffic (segment_demand.json, open data), not from any stored speeds, so
the picture holds no RCRC data and can be committed.

Rules applied, and why:

- Area: a box around the study intersection with the panel's shape
  (portrait, about 4:5), so the picture fills the panel without
  stretching.
- Colour: the busiest quarter of the segments in the box is drawn red,
  the next third amber and the rest green, as Low, Moderate and High on
  the map. Segments without a share are left out.
- Width: wider for bigger roads, so the motorways read first.
- The study intersection is marked with a dot, as on the map.

Output: frontend/src/assets/login-roads.svg

    python -m jaadah.network_congestion.login_roads
"""

import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEGMENTS = REPO_ROOT / "data/processed/network/road_segments.json"
DEMAND = REPO_ROOT / "data/processed/network/segment_demand.json"
INTERSECTIONS = REPO_ROOT / "frontend/public/data/intersections.json"
OUTPUT = REPO_ROOT / "frontend/src/assets/login-roads.svg"

WIDTH, HEIGHT = 800, 1000  # the panel's shape
SPAN_LAT = 0.075  # degrees of latitude shown, about 8 km
COLORS = {"low": "#2e8b70", "moderate": "#e5a33d", "high": "#c8473f"}  # as in index.css
STROKE = {"motorway": 5, "trunk": 4, "primary": 3, "secondary": 2.2}


def main() -> None:
    segments = json.loads(SEGMENTS.read_text())["segments"]
    demand = json.loads(DEMAND.read_text())
    shares = {
        sid: max(demand["to_activities"].get(sid, 0.0), demand["to_homes"].get(sid, 0.0))
        for sid in set(demand["to_activities"]) | set(demand["to_homes"])
    }
    site = json.loads(INTERSECTIONS.read_text())[0]
    lon0, lat0 = site["center_longitude"], site["center_latitude"]

    # Equirectangular around the intersection: enough for a few kilometres
    scale = HEIGHT / SPAN_LAT
    kx = math.cos(math.radians(lat0))

    def point(lon: float, lat: float) -> tuple[float, float]:
        return (WIDTH / 2 + (lon - lon0) * kx * scale, HEIGHT / 2 - (lat - lat0) * scale)

    def inside(x: float, y: float) -> bool:
        return -50 <= x <= WIDTH + 50 and -50 <= y <= HEIGHT + 50

    shown = []
    for segment in segments:
        share = shares.get(segment["segment_id"])
        if not share:
            continue
        line = [point(lon, lat) for lon, lat in segment["geometry"]]
        if any(inside(x, y) for x, y in line):
            shown.append((share, segment["road_class"], line))

    ranked = sorted(share for share, _, _ in shown)
    high = ranked[int(len(ranked) * 0.75)]
    moderate = ranked[int(len(ranked) * 0.42)]

    paths = []
    # quiet roads first, so the busy ones are drawn on top
    for share, road_class, line in sorted(shown, key=lambda item: item[0]):
        level = "high" if share >= high else "moderate" if share >= moderate else "low"
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in line)
        paths.append(
            f'<path d="{d}" stroke="{COLORS[level]}" stroke-width="{STROKE.get(road_class, 2)}"/>'
        )

    cx, cy = point(lon0, lat0)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'preserveAspectRatio="xMidYMid slice">'
        f'<g fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.75">'
        + "".join(paths)
        + "</g>"
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="16" fill="#ffffff" opacity="0.25"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="#ffffff" stroke="#2e2365" stroke-width="3"/>'
        "</svg>\n"
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg)
    print(f"{len(paths)} segments written to {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

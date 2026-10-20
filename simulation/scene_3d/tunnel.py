"""Tunnel elevation model for the Jaadah study area.

SUMO's network is flat (no z), but Prince Turki bin Abdulaziz Al-Awwal Road passes UNDER the
central intersection (OSM: tunnel=yes, layer=-1). This module gives every point on the two
main-line carriageways an elevation so the visualization can draw the underpass below ground.

  z(point) = -DEPTH                       inside the covered tunnel section
           = -DEPTH * (1 - d / RAMP)      on the approach/exit ramps, d = metres from the portal
           = 0                            elsewhere (surface level)

The covered section of each direction = the OSM tunnel way (569788807 SE-bound, 569788810 NW-bound).
ASSUMPTIONS (agreed 2026-10-08): the underpass depth is assumed at 7 m for visualization only
(5.5 m minimum vertical clearance in Saudi practice plus approximately 1.5 m of structure).
Ramp length 140 m per side (5% grade), also assumed. Does not affect simulation results.
Replace DEPTH / RAMP if the real design values become available (height sign, drawings, RCRC).
"""
import xml.etree.ElementTree as ET
from shapely.geometry import LineString, Point

DEPTH = 7.0   # m below surface at the covered section (≈5.5 m clearance + deck)
RAMP = 140.0  # m of ramp on each side (= 5% grade)

# main-line SUMO edges of each direction (checked against the final network, 2026-10-08)
MAINLINE = {
    "569788807": ["161824693#2", "569788807", "569788809", "994922063#0"],          # south-east bound
    "569788810": ["994922064#1.708", "994922064#2-AddedOnRampEdge",
                  "994922064#2-AddedOnRampEdge.48", "994922064#2"],                  # north-west bound
}


class TunnelModel:
    def __init__(self, net, osm_file):
        want = set(MAINLINE)
        nodes, refs = {}, {}
        for _, el in ET.iterparse(osm_file):
            if el.tag == "node":
                nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
            elif el.tag == "way":
                if el.get("id") in want:
                    refs[el.get("id")] = [n.get("ref") for n in el.findall("nd")]
                el.clear()
        self.axis = {}   # way id -> LineString in SUMO x/y metres
        for wid, r in refs.items():
            self.axis[wid] = LineString([net.convertLonLat2XY(*nodes[i]) for i in r if i in nodes])
        self.edge_axis = {e: wid for wid, edges in MAINLINE.items() for e in edges}

    def is_mainline(self, edge_id):
        return edge_id in self.edge_axis

    def z(self, edge_id, x, y):
        """Elevation (m) of point x,y (SUMO metres) lying on edge_id."""
        wid = self.edge_axis.get(edge_id)
        if wid is None:
            return 0.0
        ax = self.axis[wid]
        s = ax.project(Point(x, y))           # position along the tunnel axis (clamped to [0, L])
        # distance beyond the portal along the road direction
        p0, p1 = ax.interpolate(0), ax.interpolate(ax.length)
        if 0 < s < ax.length:
            d = 0.0
        else:
            d = Point(x, y).distance(p0 if s <= 0 else p1)
        return -DEPTH * max(0.0, 1.0 - d / RAMP)

    def covered(self, edge_id, x, y):
        """True if the point is inside the roofed part of the tunnel."""
        wid = self.edge_axis.get(edge_id)
        if wid is None:
            return False
        ax = self.axis[wid]
        s = ax.project(Point(x, y))
        return 0 < s < ax.length and Point(x, y).distance(ax) < 15

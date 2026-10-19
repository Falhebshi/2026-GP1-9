"""Extra surface detail for realistic rendering (visual only, derived from existing data):
  lane_centre   centre-line of every SUMO lane (with z), used to draw tyre-wear tracks along the wheel paths
  apron         paved strip (3 m) around every building footprint, clipped away from roads/sidewalks/medians
                (an approximation: most Riyadh buildings stand on a paved forecourt; marked as such)

Usage: python build_surface_detail.py <net.xml> <osm file> <road_surface.geojson> <streetscape.geojson> <buildings.geojson> <out.geojson>
"""
import sys, json
import sumolib
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union
from tunnel import TunnelModel

net_file, osm, surface_file, ss_file, bld_file, out_file = sys.argv[1:7]
net = sumolib.net.readNet(net_file, withInternal=True)
tm = TunnelModel(net, osm)
MAIN = set(tm.edge_axis)
to_xy = lambda lon, lat: net.convertLonLat2XY(lon, lat)
to_ll = lambda x, y: [round(c, 7) for c in net.convertXY2LonLat(x, y)]

feats = []
# ---- lane centre-lines (z from the tunnel model for main-line edges) ----
for e in net.getEdges(withInternal=True):
    if e.getFunction() == "crossing":
        continue
    for ln in e.getLanes():
        sh = ln.getShape()
        if len(sh) < 2:
            continue
        eid = e.getID()
        coords = [to_ll(x, y) + [round(tm.z(eid, x, y), 2) if eid in MAIN else 0.0] for x, y in sh]
        feats.append({"type": "Feature", "properties": {"kind": "lane_centre", "lane": ln.getID(), "width": round(ln.getWidth(), 2),
                                                        "internal": e.isSpecial()},
                      "geometry": {"type": "LineString", "coordinates": coords}})

# ---- building aprons ----
def poly_xy(ring):
    return Polygon([to_xy(c[0], c[1]) for c in ring]).buffer(0)
road = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in json.load(open(surface_file, encoding="utf-8"))["features"]])
ss = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in json.load(open(ss_file, encoding="utf-8"))["features"]])
blds = [poly_xy(f["geometry"]["coordinates"][0]) for f in json.load(open(bld_file, encoding="utf-8"))["features"] if not f["properties"].get("base_m")]
aprons = unary_union([b.buffer(3.0, join_style=2) for b in blds]).difference(unary_union(blds)).difference(road.buffer(0.5)).difference(ss)
n_ap = 0
for g in getattr(aprons, "geoms", [aprons]):
    if g.geom_type != "Polygon" or g.area < 2:
        continue
    g = g.simplify(0.1)
    feats.append({"type": "Feature", "properties": {"kind": "apron"},
                  "geometry": {"type": "Polygon", "coordinates": [[to_ll(x, y) for x, y in g.exterior.coords]] +
                               [[to_ll(x, y) for x, y in r.coords] for r in g.interiors]}})
    n_ap += 1
# ---- the whole street-level road surface as ONE outline (for large-scale tone variation without seams) ----
surface_feats = json.load(open(surface_file, encoding="utf-8"))["features"]
street = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in surface_feats if f["properties"].get("level") != "underground"])
for g in getattr(street, "geoms", [street]):
    if g.geom_type == "Polygon" and g.area > 1:
        g = g.simplify(0.05)
        feats.append({"type": "Feature", "properties": {"kind": "road_outline"},
                      "geometry": {"type": "Polygon", "coordinates": [[to_ll(x, y) for x, y in g.exterior.coords]] +
                                   [[to_ll(x, y) for x, y in r.coords] for r in g.interiors]}})
json.dump({"type": "FeatureCollection", "note": "Visual detail only. Aprons are an approximation (3 m paved strip around buildings).",
           "features": feats}, open(out_file, "w", encoding="utf-8"), separators=(",", ":"))
print("lane centres:", sum(1 for f in feats if f["properties"]["kind"] == "lane_centre"), "| aprons:", n_ap)

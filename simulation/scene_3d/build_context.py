"""Background (context) map layer from the study-area OSM file: everything a map like Google Maps shows
around the buildings that is NOT part of the SUMO simulation.

  areas  : parking lots, sports pitches, gardens/grass/shrubs, campus & land-use areas
  lines  : streets, service roads, parking aisles, footpaths and steps that are NOT in the SUMO network

Drawn for looks only, under the simulated roads; no vehicles use it.
Usage: python build_context.py <osm file> <net.xml> <road_surface.geojson> <out context.geojson>
"""
import sys, json
import xml.etree.ElementTree as ET
import sumolib
from shapely.geometry import LineString, Polygon, shape, mapping
from shapely.ops import unary_union, polygonize, transform

osm_file, net_file, surface_file, out_file = sys.argv[1:5]
net = sumolib.net.readNet(net_file)
to_xy = lambda lon, lat: net.convertLonLat2XY(lon, lat)
to_ll = lambda x, y: tuple(round(c, 7) for c in net.convertXY2LonLat(x, y))

AREA = {  # (tag, value) -> class
    ("amenity", "parking"): "parking", ("amenity", "parking_space"): "parking",
    ("leisure", "pitch"): "pitch", ("leisure", "stadium"): "pitch",
    ("leisure", "garden"): "green", ("leisure", "park"): "green", ("landuse", "grass"): "green",
    ("natural", "shrubbery"): "green", ("natural", "scrub"): "green",
    ("amenity", "university"): "campus", ("amenity", "college"): "campus", ("amenity", "school"): "campus",
    ("landuse", "residential"): "landuse", ("landuse", "commercial"): "landuse", ("landuse", "military"): "landuse",
    ("amenity", "fountain"): "water",
}
WIDTH = {  # highway type -> drawn width (m)
    "primary": 10, "secondary": 9, "tertiary": 7, "unclassified": 6, "residential": 6, "living_street": 5,
    "primary_link": 6, "secondary_link": 6, "tertiary_link": 5, "service": 4.5, "pedestrian": 4,
    "footway": 1.6, "path": 1.4, "steps": 2.0, "cycleway": 1.6,
}
nodes, ways, rels = {}, {}, []
for _, el in ET.iterparse(osm_file):
    if el.tag == "node":
        nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
    elif el.tag == "way":
        ways[el.get("id")] = ({t.get("k"): t.get("v") for t in el.findall("tag")}, [n.get("ref") for n in el.findall("nd")])
        el.clear()
    elif el.tag == "relation":
        rels.append(({t.get("k"): t.get("v") for t in el.findall("tag")},
                     [(m.get("ref"), m.get("role")) for m in el.findall("member") if m.get("type") == "way"]))

# SUMO network footprint (in metres) and the OSM way ids it was built from
surface = json.load(open(surface_file, encoding="utf-8"))["features"]
road_xy = unary_union([Polygon([to_xy(c[0], c[1]) for c in f["geometry"]["coordinates"][0]]).buffer(0)
                       for f in surface]).buffer(2.0)           # incl. the underpass: its OSM ways must not reappear
net_way_ids = {e.getID().split("#")[0].lstrip("-") for e in net.getEdges()}

def xy_line(nds):
    pts = [to_xy(*nodes[n]) for n in nds if n in nodes]
    return LineString(pts) if len(pts) > 1 else None

feats = []
# ---- areas (closed ways) ----
for wid, (t, nds) in ways.items():
    if "building" in t or len(nds) < 4 or nds[0] != nds[-1]:
        continue
    cls = next((AREA[(k, t[k])] for k in t if (k, t[k]) in AREA), None)
    if not cls:
        continue
    pts = [nodes[n] for n in nds if n in nodes]
    if len(pts) >= 4:
        feats.append({"type": "Feature", "properties": {"kind": "area", "class": cls, "name": t.get("name:en") or t.get("name", "")},
                      "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in pts]]}})
# ---- areas (multipolygon relations, e.g. the university campus) ----
for t, members in rels:
    if t.get("type") != "multipolygon":
        continue
    cls = next((AREA[(k, t[k])] for k in t if (k, t[k]) in AREA), None)
    if not cls:
        continue
    lines = [LineString([nodes[n] for n in ways[w][1] if n in nodes]) for w, role in members if w in ways and role != "inner"]
    for poly in polygonize(unary_union([l for l in lines if l.length > 0])):
        feats.append({"type": "Feature", "properties": {"kind": "area", "class": cls, "name": t.get("name:en") or t.get("name", "")},
                      "geometry": mapping(poly)})
# ---- lines: streets and paths NOT in the simulation ----
kept = skipped = 0
for wid, (t, nds) in ways.items():
    hw = t.get("highway")
    if hw not in WIDTH or wid in net_way_ids or t.get("area") == "yes" or t.get("tunnel") or t.get("layer", "0").startswith("-"):
        continue
    g = xy_line(nds)
    if g is None or g.length < 3:
        continue
    outside = g.difference(road_xy)                       # drop the parts already drawn by the SUMO roads
    for part in getattr(outside, "geoms", [outside]):
        if part.is_empty or part.length < 4:
            continue
        cls = "path" if hw in ("footway", "path", "steps", "cycleway", "pedestrian") else \
              "aisle" if t.get("service") == "parking_aisle" else "street"
        feats.append({"type": "Feature", "properties": {"kind": "line", "class": cls, "highway": hw,
                                                        "width_m": WIDTH[hw] if cls != "aisle" else 4.0},
                      "geometry": {"type": "LineString", "coordinates": [list(to_ll(x, y)) for x, y in part.coords]}})
        kept += 1
json.dump({"type": "FeatureCollection", "note": "Context only - not part of the SUMO simulation.", "features": feats},
          open(out_file, "w", encoding="utf-8"), separators=(",", ":"))
from collections import Counter
print("context features:", Counter((f["properties"]["kind"], f["properties"]["class"]) for f in feats))

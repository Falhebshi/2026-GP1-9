"""3D street furniture around the simulated roads (visual only, derived from the road surface):
  kerb      15 cm concrete kerb along every road edge (0.3 m wide)
  sidewalk  raised pavement strip (~2 m) outside the kerb, at kerb height
  median    raised island between carriageways / inside junction gaps narrower than ~24 m (20 cm)
Not cut where a road continues into the underpass ramps or leaves the study area.

Usage: python build_streetscape.py <net.xml> <road_surface.geojson> <underpass.geojson> <out streetscape.geojson>
"""
import sys, json
import sumolib
from shapely.geometry import Polygon, Point, mapping
from shapely.ops import unary_union

net_file, surface_file, underpass_file, out_file = sys.argv[1:5]
net = sumolib.net.readNet(net_file)
to_xy = lambda lon, lat: net.convertLonLat2XY(lon, lat)
to_ll = lambda x, y: [round(c, 7) for c in net.convertXY2LonLat(x, y)]

def poly_xy(ring):
    return Polygon([to_xy(c[0], c[1]) for c in ring]).buffer(0)

surface = json.load(open(surface_file))["features"]
under = json.load(open(underpass_file))["features"]
road = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in surface]).buffer(0.05).buffer(-0.05)
openings = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in under if f["properties"]["kind"] == "ramp_floor"]).buffer(0.5)
roof = unary_union([poly_xy(f["geometry"]["coordinates"][0]) for f in under if f["properties"]["kind"] == "roof"]).buffer(0.5)
# road ends at the edge of the study area: no kerb across them
ends = unary_union([Point(n.getCoord()).buffer(9) for n in net.getNodes() if n.getType() == "dead_end"])
keep_out = unary_union([openings, roof, ends])

median = road.buffer(12, join_style=2).buffer(-12, join_style=2).difference(road.buffer(0.3)).difference(keep_out)
median = unary_union([g for g in getattr(median, "geoms", [median]) if g.area > 8])
kerb = road.buffer(0.3, join_style=2).difference(road).difference(keep_out)
sidewalk = road.buffer(2.3, join_style=2).difference(road.buffer(0.3, join_style=2)).difference(median.buffer(0.01)).difference(keep_out)

feats = []
for kind, geom, h in (("sidewalk", sidewalk, 0.15), ("median", median, 0.2), ("kerb", kerb, 0.16)):
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type != "Polygon" or g.area < 0.2:
            continue
        g = g.simplify(0.05)
        rings = [[to_ll(x, y) for x, y in g.exterior.coords]] + [[to_ll(x, y) for x, y in r.coords] for r in g.interiors]
        feats.append({"type": "Feature", "properties": {"kind": kind, "height_m": h}, "geometry": {"type": "Polygon", "coordinates": rings}})
json.dump({"type": "FeatureCollection", "note": "Visual only: kerbs, sidewalks and medians derived from the road surface.",
           "features": feats}, open(out_file, "w"), separators=(",", ":"))
from collections import Counter
print("streetscape:", Counter(f["properties"]["kind"] for f in feats),
      "| areas m2: kerb %.0f sidewalk %.0f median %.0f" % (kerb.area, sidewalk.area, median.area))

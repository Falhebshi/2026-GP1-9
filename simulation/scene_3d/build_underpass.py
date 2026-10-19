"""Build the street-level ground with openings over the OPEN underpass ramps, plus the ramp
floor and retaining walls, so the 3D view shows the underpass the way it looks in reality:
the covered tunnel hidden under the street, the open ramps visible between concrete walls.

Usage: python build_underpass.py <net.xml> <osm file> <road_surface.geojson> <out underpass.geojson>
Output features (lon, lat, z; z in metres relative to street level):
  kind=ground        street-level ground polygon with holes where the ramps are open
  kind=ramp_floor    concrete floor of the open ramps (follows the road depth)
  kind=wall          retaining-wall pieces: base z = road depth, height_m up to street level
  kind=portal_beam   beam over each tunnel mouth (roof edge), from roof underside to street level
Assumption carried from tunnel.py: 7 m depth, ~5.5 m headroom (roof underside at -1.5 m).
"""
import sys, json, math
import sumolib
from shapely.geometry import shape, Polygon, LineString, Point, mapping
from shapely.ops import unary_union
from tunnel import TunnelModel, DEPTH

net_file, osm_file, surface_file, out_file = sys.argv[1:5]
net = sumolib.net.readNet(net_file, withInternal=True)
tm = TunnelModel(net, osm_file)
HEADROOM = 5.5
ROOF_UNDERSIDE = -(DEPTH - HEADROOM)          # -1.5 m
WALL_T = 0.4                                  # wall thickness (m)
STEP = 3.0                                    # wall piece length (m)

# work in SUMO metres
to_xy = lambda lon, lat: net.convertLonLat2XY(lon, lat)
to_ll = lambda x, y: [round(c, 7) for c in net.convertXY2LonLat(x, y)]

surface = json.load(open(surface_file, encoding="utf-8"))["features"]
under_polys, depth_samples = [], []
for f in surface:
    if f["properties"].get("level") != "underground":
        continue
    ring = f["geometry"]["coordinates"][0]
    pts = [to_xy(c[0], c[1]) for c in ring]
    under_polys.append(Polygon(pts).buffer(0))
    depth_samples += [(x, y, c[2]) for (x, y), c in zip(pts, ring)]

footprint = unary_union(under_polys).buffer(0.3).buffer(-0.3)          # whole underground carriageway
covered = unary_union([ax.buffer(9, cap_style=2) for ax in tm.axis.values()])   # roofed section (OSM tunnel)
opening = footprint.difference(covered)
# keep only parts that actually go below street level (ignore slivers at grade)
from shapely.strtree import STRtree
dpts = [Point(x, y) for x, y, _ in depth_samples]
dz = [z for _, _, z in depth_samples]
tree = STRtree(dpts)
def depth_at(x, y):
    i = tree.nearest(Point(x, y))
    return dz[int(i)]
parts = [g for g in getattr(opening, "geoms", [opening]) if g.area > 20 and min(depth_at(*c) for c in g.exterior.coords) < -0.5]
opening = unary_union(parts)

# ---------- ground: big rectangle around the network with the openings as holes ----------
minx, miny, maxx, maxy = unary_union([Polygon([to_xy(c[0], c[1]) for c in f["geometry"]["coordinates"][0]]).buffer(0) for f in surface]).bounds
outer = Polygon([(minx - 2000, miny - 2000), (maxx + 2000, miny - 2000), (maxx + 2000, maxy + 2000), (minx - 2000, maxy + 2000)])
ground = outer.difference(opening)
feats = []
for g in getattr(ground, "geoms", [ground]):
    rings = [[to_ll(x, y) + [0.0] for x, y in g.exterior.coords]] + [[to_ll(x, y) + [0.0] for x, y in r.coords] for r in g.interiors]
    feats.append({"type": "Feature", "properties": {"kind": "ground"}, "geometry": {"type": "Polygon", "coordinates": rings}})

# ---------- slatted roof over the covered tunnel (as seen on satellite imagery) ----------
# z just above the ground (-0.3 in the renderer) and below the road (0), so roads crossing over it win.
roof_area = footprint.intersection(covered)
n_slat = 0
for g in getattr(roof_area, "geoms", [roof_area]):
    if g.area < 5:
        continue
    feats.append({"type": "Feature", "properties": {"kind": "roof"},
                  "geometry": {"type": "Polygon", "coordinates": [[to_ll(x, y) + [-0.26] for x, y in g.exterior.coords]]}})
# Slats are laid out from ONE reference axis (the longer tunnel bore) and cut across BOTH roofs,
# so the stripes over the two directions line up instead of being offset from each other.
for ax in [max(tm.axis.values(), key=lambda a: a.length)]:
    s = 0.8
    while s < ax.length:
        p, q = ax.interpolate(s), ax.interpolate(min(s + 0.5, ax.length))
        ux, uy = q.x - p.x, q.y - p.y
        L = math.hypot(ux, uy) or 1
        nx, ny = -uy / L, ux / L
        cross = LineString([(p.x - nx * 40, p.y - ny * 40), (p.x + nx * 40, p.y + ny * 40)])
        slat = cross.buffer(0.35, cap_style=2).intersection(roof_area)
        for sg in getattr(slat, "geoms", [slat]):
            if sg.geom_type == "Polygon" and sg.area > 0.2:
                feats.append({"type": "Feature", "properties": {"kind": "roof_slat"},
                              "geometry": {"type": "Polygon", "coordinates": [[to_ll(x, y) + [-0.24] for x, y in sg.exterior.coords]]}})
                n_slat += 1
        s += 1.6

# ---------- ramp floor + walls ----------
n_wall = n_beam = 0
for g in getattr(opening, "geoms", [opening]):
    floor = [to_ll(x, y) + [round(depth_at(x, y) - 0.05, 2)] for x, y in g.exterior.coords]
    feats.append({"type": "Feature", "properties": {"kind": "ramp_floor"}, "geometry": {"type": "Polygon", "coordinates": [floor]}})
    ring = LineString(g.exterior.coords)
    d = 0.0
    while d < ring.length:
        a, b = ring.interpolate(d), ring.interpolate(min(d + STEP, ring.length))
        d += STEP
        seg = LineString([a, b])
        if seg.length < 0.2:
            continue
        mid = seg.interpolate(0.5, normalized=True)
        z = depth_at(mid.x, mid.y)
        on_portal = covered.buffer(0.5).contains(mid)       # edge shared with the roofed section = tunnel mouth
        if not on_portal and z > -0.25:
            continue                                         # at grade: no wall needed
        # thin quad on the OUTSIDE of the opening
        ux, uy = (b.x - a.x) / seg.length, (b.y - a.y) / seg.length
        nx, ny = -uy, ux
        if g.contains(Point(mid.x + nx * 0.5, mid.y + ny * 0.5)):
            nx, ny = -nx, -ny
        quad = [(a.x, a.y), (b.x, b.y), (b.x + nx * WALL_T, b.y + ny * WALL_T), (a.x + nx * WALL_T, a.y + ny * WALL_T), (a.x, a.y)]
        if on_portal:
            base, height, kind = ROOF_UNDERSIDE, -ROOF_UNDERSIDE, "portal_beam"
            n_beam += 1
        else:
            base, height, kind = z, -z, "wall"
            n_wall += 1
        feats.append({"type": "Feature", "properties": {"kind": kind, "height_m": round(height, 2)},
                      "geometry": {"type": "Polygon", "coordinates": [[to_ll(x, y) + [round(base, 2)] for x, y in quad]]}})

json.dump({"type": "FeatureCollection", "features": feats}, open(out_file, "w", encoding="utf-8"), separators=(",", ":"))
print(f"open ramp area {opening.area:.0f} m2 in {len(parts)} part(s) | covered tunnel hidden | "
      f"wall pieces {n_wall} | portal beam pieces {n_beam} | roof slats {n_slat}")

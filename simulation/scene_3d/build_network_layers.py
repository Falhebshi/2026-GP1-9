"""Build every static network layer the 3D intersection view draws, from the FINAL SUMO network.

Usage:  python build_network_layers.py <net.xml> <osm file> <out dir> [underpass.geojson]
Writes (lon, lat, z) GeoJSON — z is metres relative to street level (negative = underground):
  road_surface.geojson   lane + junction polygons (property level: surface | underground)
  road_markings.geojson  edge_right / edge_left / lane_divider / stop_line lines
  turn_arrows.geojson    painted turn arrows before signalized stop lines
  flow_arrows.geojson    direction chevrons every 35 m
Needs: pip install sumolib pyproj shapely
"""
import sys, os, json, math
import sumolib
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import substring
from tunnel import TunnelModel

net_file, osm_file, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
# the underpass outline keeps edge lines off the tunnel ramps; it is built from road_surface.geojson,
# so the first run has none yet and build_all.py runs this script a second time
underpass_file = sys.argv[4] if len(sys.argv) > 4 else os.path.join(out_dir, "underpass.geojson")
os.makedirs(out_dir, exist_ok=True)
net = sumolib.net.readNet(net_file, withInternal=True)
tm = TunnelModel(net, osm_file)
MAIN = set(tm.edge_axis)

def node_of_internal(edge_id):            # ':5220442351_3' -> '5220442351'
    return edge_id[1:].rsplit("_", 1)[0]

def mainline_node(node_id):
    """Node whose every incident edge is a tunnel main-line edge (a junction INSIDE the underpass)."""
    try:
        n = net.getNode(node_id)
    except KeyError:
        return False
    inc = [e.getID() for e in n.getIncoming() + n.getOutgoing() if not e.isSpecial()]
    return bool(inc) and all(e in MAIN for e in inc)

def is_tls_internal(edge_id):
    """Internal (junction) lane of the signalised junction? Other junctions are drawn like normal road."""
    if not edge_id.startswith(":"):
        return False
    try:
        return net.getNode(node_of_internal(edge_id)).getType().startswith("traffic_light")
    except KeyError:
        return False

def z_on(edge_id, x, y):
    if edge_id in MAIN:
        return tm.z(edge_id, x, y)
    if edge_id.startswith(":") and mainline_node(node_of_internal(edge_id)):
        return nearest_main_z(x, y)
    return 0.0

def nearest_main_z(x, y):
    """Elevation of the closest tunnel main-line edge (for junction pieces inside the underpass)."""
    pt = Point(x, y)
    eid = min(MAIN, key=lambda m: LineString(net.getEdge(m).getShape()).distance(pt))
    return tm.z(eid, x, y)

def ll3(x, y, z):
    lon, lat = net.convertXY2LonLat(x, y)
    return [round(lon, 7), round(lat, 7), round(z, 2)]

def line3(geom, edge_id, lift=0.0):
    return [ll3(x, y, z_on(edge_id, x, y) + lift) for x, y in geom.coords]

# ---------- SHC 602 paint definitions (Saudi Highway Code 602, Chapter 4 Markings) ----------
PAINT = {
    "edge_right":         {"kind": "edge_right", "color": "yellow", "width_m": 0.15, "pattern": "solid", "standard": "SHC 602 L5-1b"},
    "edge_left":          {"kind": "edge_left", "color": "yellow", "width_m": 0.15, "pattern": "solid", "standard": "SHC 602 L5-1b / §4.1.3"},
    "lane_divider":       {"kind": "lane_divider", "color": "white", "width_m": 0.15, "pattern": "broken", "dash_m": 3.0, "gap_m": 6.0, "standard": "SHC 602 L2-1b"},
    "lane_divider_solid": {"kind": "lane_divider_solid", "color": "white", "width_m": 0.15, "pattern": "solid", "standard": "SHC 602 L4-1c (25 m before stop line)"},
    "stop_line":          {"kind": "stop_line", "color": "white", "width_m": 0.30, "pattern": "solid", "standard": "SHC 602 L16-1"},
}

def arrow_polygon(dirs, base, fwd):
    """Filled arrow in local metres, per SHC 602 Fig. 4-28 (L13-1) and 4-29 (L13-2).
    Straight: 1.4 m shaft + 1.6 m head = 3.0 m.  Turn: shaft, a tight bend and a short head = 2.5 m.
    Drawn slim (0.18 m shaft, 0.6 m head) so they read cleanly from above, and the whole shape is
    centred in the lane: a turn head sticks out sideways, so without this the arrow sits off-centre."""
    fx, fy = fwd
    rx, ry = fy, -fx                                  # right-hand normal
    P = lambda a, b: (base[0] + fx * a + rx * b, base[1] + fy * a + ry * b)   # a = forward, b = right
    parts = []
    if "s" in dirs:
        parts.append(LineString([P(0, 0), P(1.5, 0)]).buffer(0.09, cap_style=2))
        parts.append(Polygon([P(1.5, -0.3), P(3.0, 0), P(1.5, 0.3)]))
    # on a combined arrow (straight + turn) the turn branches off low on the shaft, so its head
    # stays clear of the straight head instead of overlapping it
    branch = 0.2 if "s" in dirs else 0.9
    for side, sign in (("l", -1), ("r", 1)):
        if side in dirs:
            pts = [P(0, 0), P(branch, 0)]
            for k in range(1, 10):                    # quarter bend, centre-line radius 0.6 m
                t = math.pi / 2 * k / 9
                pts.append(P(branch + 0.6 * math.sin(t), sign * 0.6 * (1 - math.cos(t))))
            parts.append(LineString(pts).buffer(0.09, cap_style=2, join_style=1))
            tip_a, tip_b = branch + 0.6, sign * (0.6 + 0.6)
            parts.append(Polygon([P(tip_a - 0.3, sign * 0.6), P(tip_a, tip_b), P(tip_a + 0.3, sign * 0.6)]))
    if not parts:
        return None
    from shapely.ops import unary_union
    u = unary_union(parts)
    u = u if u.geom_type == "Polygon" else max(u.geoms, key=lambda g: g.area)
    # centre the shape across the lane
    lat = [(x - base[0]) * rx + (y - base[1]) * ry for x, y in u.exterior.coords]
    shift = -(min(lat) + max(lat)) / 2
    from shapely.affinity import translate
    return translate(u, rx * shift, ry * shift)

def extend(shape, d):
    """Polyline lengthened by d metres at both ends, along the first / last segment direction."""
    (ax, ay), (bx, by) = shape[0], shape[1]
    (cx, cy), (ex, ey) = shape[-2], shape[-1]
    l1 = math.hypot(bx - ax, by - ay) or 1
    l2 = math.hypot(ex - cx, ey - cy) or 1
    return [(ax - (bx - ax) / l1 * d, ay - (by - ay) / l1 * d)] + list(shape[1:-1]) + \
           [(ex + (ex - cx) / l2 * d, ey + (ey - cy) / l2 * d)] if len(shape) > 2 else \
           [(ax - (bx - ax) / l1 * d, ay - (by - ay) / l1 * d), (ex + (ex - cx) / l2 * d, ey + (ey - cy) / l2 * d)]

def off(shape, d):
    g = LineString(shape).offset_curve(d, join_style=2)
    return g if (not g.is_empty and g.geom_type == "LineString") else None

surface, lines, arrows, flows = [], [], [], []

# ---------- lanes ----------
for e in net.getEdges(withInternal=True):
    if e.getFunction() == "crossing":
        continue
    eid = e.getID()
    lanes = e.getLanes()
    for i, ln in enumerate(lanes):
        sh, w = ln.getShape(), ln.getWidth()
        if len(sh) < 2:
            continue
        # Each lane strip is extended 0.25 m past both ends (along its end direction) so consecutive
        # pieces overlap: SUMO lane pieces meet at slight angles, and flat-ended strips leave thin
        # wedge-shaped seams where the road looks broken. Purely visual; lane geometry is unchanged.
        poly = LineString(extend(sh, 0.25)).buffer(w / 2.0, cap_style=2, join_style=2)
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        ring = [ll3(x, y, z_on(eid, x, y)) for x, y in poly.exterior.coords]
        under = min(p[2] for p in ring) < -0.5
        mx, my = sumolib.geomhelper.positionAtShapeOffset(sh, LineString(sh).length / 2)
        surface.append({"type": "Feature",
                        "properties": {"kind": "lane", "id": ln.getID(), "edge": eid, "internal": e.isSpecial(), "tls": is_tls_internal(eid),
                                       "width": round(w, 2), "level": "underground" if under else "surface",
                                       "covered": tm.covered(eid, mx, my)},
                        "geometry": {"type": "Polygon", "coordinates": [ring]}})
        if e.isSpecial():
            continue
        # painted lines, per SHC 602 Chapter 4 (divided roads, posted speed 80-100 km/h):
        #   edge lines both sides: YELLOW, 150 mm (L5-1b, Table 4-6; §4.1.3 left edge next to median)
        #   lane lines: broken WHITE, 3 m line / 6 m gap, 150 mm (L2-1b, Table 4-2)
        #   last 25 m before a signal/stop line: solid WHITE prohibitory line, 150 mm (L4-1c, §4.2.4)
        controlled = e.getToNode().getType() in ("traffic_light", "traffic_light_right_on_red", "priority_stop", "allway_stop")
        # length of solid (no lane change) line at the end of this edge: the last 25 m before a stop line,
        # continued onto the upstream edge when SUMO split the approach just before the junction
        solid_m = 25.0 if controlled else 0.0
        if not controlled:
            nxt = [o for o in e.getOutgoing() if not o.isSpecial()]
            if len(nxt) == 1 and nxt[0].getToNode().getType() in ("traffic_light", "traffic_light_right_on_red") \
                    and nxt[0].getLength() < 25.0 and len(nxt[0].getLanes()) == len(lanes):
                solid_m = 25.0 - nxt[0].getLength()
        if i == 0:
            g = off(sh, -w / 2)
            if g: lines.append({"type": "Feature", "properties": {**PAINT["edge_right"], "edge": eid},
                                "geometry": {"type": "LineString", "coordinates": line3(g, eid, 0.06)}})
        g = off(sh, w / 2)
        if g:
            if i == len(lanes) - 1:
                lines.append({"type": "Feature", "properties": {**PAINT["edge_left"], "edge": eid},
                              "geometry": {"type": "LineString", "coordinates": line3(g, eid, 0.06)}})
            elif solid_m > 0 and g.length > 1:
                cut = max(0.0, g.length - solid_m)
                if cut > 1:
                    lines.append({"type": "Feature", "properties": {**PAINT["lane_divider"], "edge": eid},
                                  "geometry": {"type": "LineString", "coordinates": line3(substring(g, 0, cut), eid, 0.06)}})
                lines.append({"type": "Feature", "properties": {**PAINT["lane_divider_solid"], "edge": eid},
                              "geometry": {"type": "LineString", "coordinates": line3(substring(g, cut, g.length), eid, 0.06)}})
            else:
                lines.append({"type": "Feature", "properties": {**PAINT["lane_divider"], "edge": eid},
                              "geometry": {"type": "LineString", "coordinates": line3(g, eid, 0.06)}})
        # direction chevrons
        G = LineString(sh)
        k = 20.0
        while k < G.length - 15:
            p, q = G.interpolate(k), G.interpolate(k + 1)
            hd = (90 - math.degrees(math.atan2(q.y - p.y, q.x - p.x))) % 360
            flows.append({"type": "Feature", "properties": {"heading_deg": round(hd, 1), "edge": eid},
                          "geometry": {"type": "Point", "coordinates": ll3(p.x, p.y, z_on(eid, p.x, p.y) + 0.06)}})
            k += 35.0

# ---------- stop lines + turn arrows on every approach of a controlled junction ----------
# One STRAIGHT stop line across the whole approach (perpendicular to the travel direction, at the most
# upstream lane end), and the arrows of all lanes side by side in one row ~10 m before it. Lanes that are
# too short in SUMO (the network splits some approaches 2 m before the junction) borrow the geometry of the
# lane feeding them, so every approach lane gets its arrow.
CONTROLLED = ("traffic_light", "traffic_light_right_on_red", "priority_stop", "allway_stop")

def approach_line(ln, need=16.0):
    """Lane centre-line extended upstream through straight predecessors until it is >= need metres."""
    pts = list(ln.getShape())
    cur = ln
    while LineString(pts).length < need:
        prev = [l for l in cur.getIncoming() if not l.getEdge().isSpecial()]
        if not prev:
            break
        prev.sort(key=lambda l: abs(l.getIndex() - cur.getIndex()))
        cur = prev[0]
        pts = list(cur.getShape())[:-1] + pts
    return LineString(pts)

STOP_AT = {}
for e in net.getEdges():
    if e.isSpecial() or e.getToNode().getType() not in CONTROLLED:
        continue
    eid = e.getID()
    lanes = [ln for ln in e.getLanes() if ln.getOutgoing()]
    if not lanes:
        continue
    # travel direction = mean of the lanes' last segments
    ux = uy = 0.0
    for ln in lanes:
        (x1, y1), (x2, y2) = ln.getShape()[-2], ln.getShape()[-1]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        ux += (x2 - x1) / L; uy += (y2 - y1) / L
    L = math.hypot(ux, uy) or 1
    ux, uy = ux / L, uy / L
    nx, ny = -uy, ux                                       # left normal
    ends = [ln.getShape()[-1] for ln in lanes]
    s_stop = min(x * ux + y * uy for x, y in ends) - 0.3  # most upstream lane end
    lat = [(x * nx + y * ny) for x, y in ends]
    half = [ln.getWidth() / 2 for ln in lanes]
    t_lo = min(t - h for t, h in zip(lat, half)); t_hi = max(t + h for t, h in zip(lat, half))
    P = lambda s_, t_: (s_ * ux + t_ * nx, s_ * uy + t_ * ny)
    STOP_AT[eid] = (ux, uy, s_stop)
    # stop line: continuous WHITE, 300 mm, straight across all lanes of the approach (L16-1, §4.4.3)
    a_, b_ = P(s_stop, t_lo), P(s_stop, t_hi)
    lines.append({"type": "Feature", "properties": {**PAINT["stop_line"], "edge": eid},
                  "geometry": {"type": "LineString", "coordinates": [ll3(*a_, 0.06), ll3(*b_, 0.06)]}})
    # turn arrows: filled WHITE shapes at the SHC 602 sizes (L13-1 straight 3.0 m, L13-2 turn 2.5 m), one row
    for ln, t in zip(lanes, lat):
        dirs = sorted({c.getDirection().lower() for c in ln.getOutgoing() if c.getDirection() not in ("t", "T")})
        if not dirs:
            continue
        G = approach_line(ln)
        # point on this lane's centre-line whose along-coordinate is 10 m before the stop line
        target = s_stop - 10.0
        best, bd = None, 1e9
        k = 0.0
        while k <= G.length:
            q = G.interpolate(k)
            d = abs(q.x * ux + q.y * uy - target)
            if d < bd:
                best, bd = k, d
            k += 0.25
        if best is None or bd > 1.0:
            continue
        q, q2 = G.interpolate(best), G.interpolate(min(G.length, best + 1.0))
        fx, fy = q2.x - q.x, q2.y - q.y
        Lf = math.hypot(fx, fy) or 1
        shape = arrow_polygon("".join(dirs), (q.x, q.y), (fx / Lf, fy / Lf))
        if shape is not None:
            arrows.append({"type": "Feature",
                           "properties": {"dirs": "".join(dirs), "lane": ln.getID(), "color": "white",
                                          "standard": "SHC 602 L13-1 (straight 3.0 m) / L13-2 (turn 2.5 m)"},
                           "geometry": {"type": "Polygon", "coordinates": [[ll3(x, y, 0.07) for x, y in shape.exterior.coords]]}})

# ---------- markings continued THROUGH non-signalised junctions ----------
# SUMO splits a road into separate edges wherever a way is split or lanes are added/dropped; the joint is a
# small "junction". Real roads keep their markings through these joints, so the edge lines and lane lines
# are drawn along the straight-through internal lanes there too (signalised junction box stays unmarked).
n_through = 0
for j in net.getNodes():
    if j.getType().startswith("traffic_light"):
        continue
    groups = {}
    for c in j.getConnections():
        if c.getDirection() != "s" or not c.getViaLaneID():
            continue
        groups.setdefault((c.getFrom().getID(), c.getTo().getID()), []).append(c)
    for (fid, tid), cons in groups.items():
        cons.sort(key=lambda c: c.getFromLane().getIndex())
        n_from = len(net.getEdge(fid).getLanes())
        same_width = n_from == len(net.getEdge(tid).getLanes())   # where lanes are added/dropped, the edge
        # lines would cut diagonally across the road, so only lane lines are continued there
        vias = []
        for c in cons:
            via = net.getLane(c.getViaLaneID())
            sh = via.getShape()
            if len(sh) >= 2 and LineString(sh).length > 0.5:
                vias.append((c, via, sh))
        for k, (c, via, sh) in enumerate(vias):
            vid, w = via.getEdge().getID(), via.getWidth()
            if c.getFromLane().getIndex() == 0 and same_width:
                g = off(sh, -w / 2)
                if g: lines.append({"type": "Feature", "properties": {**PAINT["edge_right"], "edge": vid},
                                    "geometry": {"type": "LineString", "coordinates": line3(g, vid, 0.06)}})
            g = off(sh, w / 2)
            if not g:
                continue
            if c.getFromLane().getIndex() == n_from - 1 and k == len(vias) - 1:
                if not same_width:
                    continue
                lines.append({"type": "Feature", "properties": {**PAINT["edge_left"], "edge": vid},
                              "geometry": {"type": "LineString", "coordinates": line3(g, vid, 0.06)}})
            elif k < len(vias) - 1 and same_width:
                lines.append({"type": "Feature", "properties": {**PAINT["lane_divider"], "edge": vid},
                              "geometry": {"type": "LineString", "coordinates": line3(g, vid, 0.06)}})
            n_through += 1
print("through-junction marking pieces:", n_through)

# ---------- junction areas ----------
for j in net.getNodes():
    shp = j.getShape()
    if not shp or len(shp) < 3:
        continue
    p = Polygon(shp)
    if not p.is_valid:
        p = p.buffer(0)
    if p.geom_type != "Polygon" or p.area < 1:
        continue
    inside = mainline_node(j.getID())
    ring = [ll3(x, y, nearest_main_z(x, y) if inside else 0.0) for x, y in p.exterior.coords]
    surface.append({"type": "Feature", "properties": {"kind": "junction", "id": j.getID(), "tls": j.getType().startswith("traffic_light"),
                                                      "level": "underground" if inside and min(r[2] for r in ring) < -0.5 else "surface"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]}})

# ---------- lane/edge lines end AT the straight stop line (they must not run on into the junction) ----------
n_clip = 0
for f in lines:
    k = f["properties"].get("kind")
    eid = f["properties"].get("edge")
    if k == "stop_line" or eid not in STOP_AT:
        continue
    ux, uy, s_stop = STOP_AT[eid]
    pts = [(net.convertLonLat2XY(c[0], c[1]), c[2]) for c in f["geometry"]["coordinates"]]
    out, cut = [], False
    for i, ((x, y), z) in enumerate(pts):
        a_ = x * ux + y * uy
        if a_ <= s_stop:
            out.append(((x, y), z))
            continue
        if i > 0:                                   # cut the segment exactly at the stop line
            (px, py), pz = pts[i - 1]
            pa = px * ux + py * uy
            if pa < s_stop:
                t = (s_stop - pa) / (a_ - pa)
                out.append(((px + (x - px) * t, py + (y - py) * t), pz + (z - pz) * t))
        cut = True
        break
    if cut:
        n_clip += 1
        f["geometry"]["coordinates"] = [ll3(x, y, z) for (x, y), z in out] if len(out) >= 2 else []
lines = [f for f in lines if len(f["geometry"]["coordinates"]) >= 2]
print("lines trimmed at the stop line:", n_clip)

# ---------- edge and lane lines must not be painted across another carriageway ----------
# Where two SUMO edges overlap (a ramp lane joining, or two parallel pieces of the same road), the
# edge line of one ends up in the middle of the other's lanes. Those parts are removed: a line is
# cut wherever it lies more than 0.4 m inside the street-level lanes of a different edge.
from shapely.ops import unary_union
from shapely.strtree import STRtree
lane_polys, lane_edges = [], []
for e in net.getEdges():
    if e.isSpecial():
        continue
    for ln in e.getLanes():
        shp = ln.getShape()
        if len(shp) < 2:
            continue
        mid = LineString(shp).interpolate(0.5, normalized=True)
        if z_on(e.getID(), mid.x, mid.y) < -0.3:      # tunnel lanes are below the street, not across it
            continue
        lane_polys.append(LineString(shp).buffer(ln.getWidth() / 2 - 0.4, cap_style=2))
        lane_edges.append(e.getID())
tree = STRtree(lane_polys)
n_cross = 0
kept = []
for f in lines:
    k = f["properties"].get("kind")
    eid = f["properties"].get("edge", "")
    if k not in ("edge_left", "edge_right", "lane_divider", "lane_divider_solid") or eid.startswith(":"):
        kept.append(f)
        continue
    coords = f["geometry"]["coordinates"]
    if min(c[2] if len(c) > 2 else 0.0 for c in coords) < -0.3:
        kept.append(f)
        continue
    xy = [net.convertLonLat2XY(c[0], c[1]) for c in coords]
    g = LineString(xy)
    others = [lane_polys[i] for i in tree.query(g) if lane_edges[i] != eid]
    if not others:
        kept.append(f)
        continue
    rest = g.difference(unary_union(others))
    if rest.equals(g):
        kept.append(f)
        continue
    n_cross += 1
    z0 = coords[0][2] if len(coords[0]) > 2 else 0.0
    for part in getattr(rest, "geoms", [rest]):
        if part.geom_type == "LineString" and part.length > 1.0:
            kept.append({**f, "geometry": {"type": "LineString", "coordinates": [ll3(x, y, z0) for x, y in part.coords]}})
lines = kept
print("lines cut where they crossed another carriageway:", n_cross)

# ---------- one line where two lines lie on top of each other ----------
# On a two-way road without a median, each direction draws its own left edge line along the same
# centre, which shows as a doubled, flickering line. Keep the first and drop the copy.
kept, kept_geoms, n_dup = [], [], 0
for f in lines:
    coords = f["geometry"]["coordinates"]
    g = LineString([net.convertLonLat2XY(c[0], c[1]) for c in coords])
    near = g.buffer(0.35)
    if any(near.intersection(h).length > 0.5 * min(g.length, h.length) and g.length > 1 for h in kept_geoms if h.distance(g) < 0.35):
        n_dup += 1
        continue
    kept.append(f)
    kept_geoms.append(g)
lines = kept
print("doubled lines removed:", n_dup)

# ---------- street-level edge lines drawn along the real road edge ----------
# Drawing the yellow edge lines lane by lane left gaps wherever SUMO adds or drops a lane (the joint
# piece has no edge line, since a lane-based one would cut across the road). Instead, the street-level
# edge lines are traced along the outline of the whole street-level road surface, 0.3 m inside it, so
# they run unbroken along every kerb. They stop at real junctions (where traffic can turn), not at
# the joints where a road only changes its number of lanes. Edge lines in the tunnel keep the old way.
from shapely.ops import unary_union, linemerge
street_parts = []
for e in net.getEdges():
    if e.isSpecial():
        continue
    for ln in e.getLanes():
        sh = ln.getShape()
        if len(sh) < 2:
            continue
        mid = LineString(sh).interpolate(0.5, normalized=True)
        if z_on(e.getID(), mid.x, mid.y) < -0.3:
            continue
        street_parts.append(LineString(sh).buffer(ln.getWidth() / 2, cap_style=2, join_style=2))
joints, crossings = [], []
for j in net.getNodes():
    shp = j.getShape()
    if not shp or len(shp) < 3:
        continue
    p = Polygon(shp).buffer(0)
    if p.is_empty or mainline_node(j.getID()):
        continue
    turns = any(c.getDirection() in ("l", "r", "L", "R") for c in j.getConnections())
    (crossings if turns or j.getType().startswith("traffic_light") else joints).append(p)
street = unary_union(street_parts + [p.buffer(0.05) for p in joints])
# smooth the outline: fill small notches between lane pieces, then trim thin spikes, so the line
# doesn't zig-zag where pieces meet at an angle
street = street.buffer(0.8, join_style=1).buffer(-0.8, join_style=1)
street = street.buffer(-0.6, join_style=1).buffer(0.6, join_style=1)
inner = street.buffer(-0.3, join_style=2)
boundary = unary_union([g.boundary for g in getattr(inner, "geoms", [inner])])
# no edge line along the open tunnel ramps either: there the street just ends at the ramp wall, and
# from above the line looked like it ran through the middle of the road
under_parts = []
for e in net.getEdges():
    if e.isSpecial():
        continue
    for ln in e.getLanes():
        sh = ln.getShape()
        if len(sh) < 2:
            continue
        mid = LineString(sh).interpolate(0.5, normalized=True)
        if z_on(e.getID(), mid.x, mid.y) < -0.3:
            under_parts.append(LineString(sh).buffer(ln.getWidth() / 2 + 4.0, cap_style=2))
# and none along the tunnel structure (open ramps, walls and the covered roof), from underpass.geojson
if os.path.exists(underpass_file):
    for f in json.load(open(underpass_file))["features"]:
        if f["properties"].get("kind") in ("ramp_floor", "wall", "roof"):
            ring = [net.convertLonLat2XY(c[0], c[1]) for c in f["geometry"]["coordinates"][0]]
            if len(ring) >= 3:
                under_parts.append(Polygon(ring).buffer(1.0))
gaps = unary_union([p.buffer(1.5) for p in crossings] + under_parts) if crossings or under_parts else None
if gaps is not None:
    boundary = boundary.difference(gaps)
# never paint an edge line inside a lane: where two road pieces leave a thin gap between them, the
# outline would run down the middle of the lane, under the cars
lane_cores = [p.buffer(-0.6) for p in street_parts]
# the lanes through junctions too (e.g. a right-turn slip lane): cars drive along their middle
for e in net.getEdges():
    if not e.isSpecial():
        continue
    for ln in e.getLanes():
        sh = ln.getShape()
        if len(sh) < 2:
            continue
        mid = LineString(sh).interpolate(0.5, normalized=True)
        if z_on(e.getID(), mid.x, mid.y) < -0.3:
            continue
        lane_cores.append(LineString(sh).buffer(ln.getWidth() / 2 - 0.6, cap_style=2))
boundary = boundary.difference(unary_union([p for p in lane_cores if not p.is_empty]))
boundary = linemerge(boundary) if boundary.geom_type == "MultiLineString" else boundary
old_n = sum(1 for f in lines if f["properties"]["kind"] in ("edge_left", "edge_right"))
# all lane-based edge lines go, including the ones down in the tunnel ramps: seen from above they
# looked like extra yellow lines in the middle of the road
lines = [f for f in lines if f["properties"]["kind"] not in ("edge_left", "edge_right")]
n_new = 0
for g in getattr(boundary, "geoms", [boundary]):
    if g.geom_type != "LineString" or g.length < 2:
        continue
    g = g.simplify(0.05)
    lines.append({"type": "Feature", "properties": {**PAINT["edge_right"], "edge": "outline"},
                  "geometry": {"type": "LineString", "coordinates": [ll3(x, y, 0.06) for x, y in g.coords]}})
    n_new += 1
print("street edge lines: replaced", old_n, "lane-based pieces with", n_new, "traced lines")


def dump(name, feats):
    json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(out_dir, name), "w"), separators=(",", ":"))

dump("road_surface.geojson", surface)
dump("road_markings.geojson", lines)
dump("turn_arrows.geojson", arrows)
dump("flow_arrows.geojson", flows)

from collections import Counter
print("surface:", dict(Counter((f["properties"]["kind"], f["properties"]["level"]) for f in surface)))
print("covered (roofed) lanes:", sum(1 for f in surface if f["properties"].get("covered")))
print("markings:", dict(Counter(f["properties"]["kind"] for f in lines)), "| turn arrows:", len(arrows), "| chevrons:", len(flows))

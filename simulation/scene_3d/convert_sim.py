"""Convert a SUMO run into the files the 3D intersection view reads.

Usage: python convert_sim.py <net.xml> <osm file> <fcd.xml> <tls_states.xml> <out dir> [t0] [t1] [source note]
SUMO must be run with: --fcd-output.geo --fcd-output.signals and the SaveTLSStates timedEvent.
Writes:
  sim.json      per vehicle: path [lon,lat], z (m, negative = in the underpass), timestamps, angles,
                speeds (m/s), signals (SUMO bitmask: 1 right blinker, 2 left blinker, 8 brake light)
  signals.json  heads per signal link + state changes only
"""
import sys, os, json, xml.etree.ElementTree as ET
import sumolib
from shapely.geometry import LineString, Point
from tunnel import TunnelModel

net_file, osm_file, fcd_file, tls_file, out_dir = sys.argv[1:6]
T0 = float(sys.argv[6]) if len(sys.argv) > 6 else 300.0
T1 = float(sys.argv[7]) if len(sys.argv) > 7 else 420.0
SOURCE = sys.argv[8] if len(sys.argv) > 8 else "SUMO run"
os.makedirs(out_dir, exist_ok=True)

net = sumolib.net.readNet(net_file, withInternal=True)
tm = TunnelModel(net, osm_file)
MAIN = set(tm.edge_axis)

def mainline_node(node_id):
    try:
        n = net.getNode(node_id)
    except KeyError:
        return False
    inc = [e.getID() for e in n.getIncoming() + n.getOutgoing() if not e.isSpecial()]
    return bool(inc) and all(e in MAIN for e in inc)

def z_for(lane_id, lon, lat):
    edge = lane_id.rsplit("_", 1)[0]
    x, y = net.convertLonLat2XY(lon, lat)
    if edge in MAIN:
        return tm.z(edge, x, y)
    if edge.startswith(":") and mainline_node(edge[1:].rsplit("_", 1)[0]):
        pt = Point(x, y)
        m = min(MAIN, key=lambda e: LineString(net.getEdge(e).getShape()).distance(pt))
        return tm.z(m, x, y)
    return 0.0

# ---------- vehicles ----------
veh = {}
for _, el in ET.iterparse(fcd_file, events=("end",)):
    if el.tag != "timestep":
        continue
    t = float(el.get("time")) - T0
    if 0 <= t <= T1 - T0:
        for v in el.findall("vehicle"):
            lon, lat = float(v.get("x")), float(v.get("y"))
            d = veh.setdefault(v.get("id"), {"vehicle_id": "veh_" + v.get("id"), "type": v.get("type").replace("j_", ""),
                                             "path": [], "z": [], "timestamps": [], "angles": [], "speeds": [], "signals": []})
            d["path"].append([round(lon, 7), round(lat, 7)])
            d["z"].append(round(z_for(v.get("lane"), lon, lat), 2))
            d["timestamps"].append(round(t, 2))
            d["angles"].append(round(float(v.get("angle")), 1))
            d["speeds"].append(round(float(v.get("speed")), 2))
            d["signals"].append(int(v.get("signals", "0")))
    el.clear()
trips = [d for d in veh.values() if len(d["path"]) >= 2]
sim = {"intersection_id": "turki_imamsaud", "scenario": "baseline", "source": SOURCE,
       "t_start": 0, "t_end": T1 - T0, "time_unit": "seconds", "available": True,
       "angle_convention": "SUMO navigation degrees: 0 = north, clockwise", "speed_unit": "m/s",
       "z_unit": "m relative to street level (negative = underpass)",
       "signals_bits": {"1": "right blinker", "2": "left blinker", "8": "brake light"},
       "vehicle_types": {"car": {"length": 4.5, "width": 1.8, "height": 1.5},
                         "bus": {"length": 12.0, "width": 2.5, "height": 3.1},
                         "truck": {"length": 9.0, "width": 2.4, "height": 3.3}},
       "trips": trips}
json.dump(sim, open(os.path.join(out_dir, "sim.json"), "w", encoding="utf-8"), separators=(",", ":"))

# ---------- traffic lights ----------
ll = lambda x, y: [round(c, 7) for c in net.convertXY2LonLat(x, y)]
states = {}
for _, el in ET.iterparse(tls_file, events=("end",)):
    if el.tag == "tlsState":
        tid, t, st = el.get("id"), float(el.get("time")), el.get("state")
        lst = states.setdefault(tid, [])
        if t <= T0:
            lst[:] = [[0.0, st]]
        elif t <= T1 and lst[-1][1] != st:
            lst.append([round(t - T0, 2), st])
        el.clear()
tls_out = []
for tls in net.getTrafficLights():
    heads = []
    for inLane, outLane, idx in tls.getConnections():
        sh = inLane.getShape()
        (x1, y1), (x2, y2) = sh[-2], sh[-1]
        heads.append({"link_index": idx, "in_lane": inLane.getID(), "out_lane": outLane.getID(),
                      "position": ll(x2, y2), "toward": ll(x2 + (x2 - x1) * 0.01, y2 + (y2 - y1) * 0.01)})
    tls_out.append({"tls_id": tls.getID(), "cycle_s": 120, "heads": heads, "states": states.get(tls.getID(), [])})
json.dump({"t_start": 0, "t_end": T1 - T0, "state_chars": "r=red y=yellow g/G=green o=off", "traffic_lights": tls_out},
          open(os.path.join(out_dir, "signals.json"), "w", encoding="utf-8"), separators=(",", ":"))

under = sum(1 for d in trips if min(d["z"]) < -0.5)
print(f"vehicles: {len(trips)} | through the underpass: {under} | heads: {sum(len(t['heads']) for t in tls_out)}"
      f" | signal changes: {sum(len(t['states']) for t in tls_out)}")

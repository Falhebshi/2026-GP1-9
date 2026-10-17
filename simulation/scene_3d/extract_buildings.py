"""Extract 3D building footprints from the study-area OSM file.

Usage: python extract_buildings.py <osm file> <out buildings.geojson>
Height rule (OSM in Riyadh rarely has heights):
  1. tag `height` (m) if present
  2. tag `building:levels` x 3.2 m
  3. otherwise an estimate from the building type (see TYPE_HEIGHT) — marked height_source="estimated"
"""
import sys, json, xml.etree.ElementTree as ET
from collections import Counter

osm_file, out = sys.argv[1], sys.argv[2]
TYPE_HEIGHT = {  # metres, typical Riyadh values
    "house": 7, "residential": 7, "detached": 7, "villa": 8, "apartments": 13,
    "commercial": 9, "retail": 7, "office": 16, "mosque": 9, "school": 9, "university": 12,
    "hospital": 16, "hotel": 20, "industrial": 8, "warehouse": 8, "garage": 3.5, "garages": 3.5,
    "roof": 4, "carport": 3, "public": 9, "parking": 10, "shed": 3, "service": 4, "construction": 6, "yes": 7,
}
nodes, feats, src = {}, [], Counter()
for _, el in ET.iterparse(osm_file):
    if el.tag == "node":
        nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
    elif el.tag == "way":
        tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
        btype = tags.get("building")
        if btype and btype != "no" and tags.get("location") != "underground":
            ring = [nodes[n.get("ref")] for n in el.findall("nd") if n.get("ref") in nodes]
            if len(ring) >= 4 and ring[0] == ring[-1]:
                if "height" in tags:
                    try:
                        h, s = float(tags["height"].split()[0]), "osm_height"
                    except ValueError:
                        h, s = TYPE_HEIGHT.get(btype, 7), "estimated"
                elif "building:levels" in tags:
                    try:
                        h, s = float(tags["building:levels"]) * 3.2, "osm_levels"
                    except ValueError:
                        h, s = TYPE_HEIGHT.get(btype, 7), "estimated"
                else:
                    h, s = TYPE_HEIGHT.get(btype, 7), "estimated"
                src[s] += 1
                feats.append({"type": "Feature",
                              "properties": {"osm_id": el.get("id"), "type": btype, "name": tags.get("name:en") or tags.get("name", ""),
                                             "height_m": round(h, 1), "height_source": s},
                              "geometry": {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}})
        el.clear()
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"), separators=(",", ":"))
print("buildings:", len(feats), "| height source:", dict(src))
print("types:", Counter(f["properties"]["type"] for f in feats).most_common(8))

"""Merge building sources into one buildings.geojson
  1. OSM footprints (extract_buildings.py output, kept separately as buildings_osm.geojson)
  2. Overture Maps additions that OSM lacks (Microsoft ML footprints), skipping anything that overlaps 1 or 3
  3. Landmarks traced by the team from Esri World Imagery (landmarks_traced.geojson); they replace any OSM
     footprint they overlap by more than 50 % (e.g. the shifted SASO outline)
Every feature keeps: name, height_m, height_source (osm_levels | estimated), source (osm | overture_ms | traced).
Usage: python merge_buildings.py <buildings_osm.geojson> <overture_buildings.geojson> <landmarks_traced.geojson> <out buildings.geojson>
"""
import sys, json
from shapely.geometry import shape
from shapely.strtree import STRtree
osm_file, overture_file, landmarks_file, out_file = sys.argv[1:5]
osm = json.load(open(osm_file, encoding="utf-8"))["features"]
ovt = json.load(open(overture_file, encoding="utf-8"))["features"]
lm = json.load(open(landmarks_file, encoding="utf-8"))["features"]
lm_g = [shape(f["geometry"]) for f in lm]
out = []
SPHERE_H = 20  # the CST sphere: OSM gives no height; estimated from imagery
# OSM footprints left out by hand: 1380326952 drew a second block inside the traced CST podium
# (removed from the 3D view on 14 Oct as a duplicate)
EXCLUDED_OSM_IDS = {"1380326952"}
for f in osm:
    if f["properties"].get("osm_id") in EXCLUDED_OSM_IDS:
        continue
    g = shape(f["geometry"]).buffer(0)
    if any(g.intersection(l).area > 0.5 * g.area for l in lm_g) and g.area > 1e-8 and f["properties"]["height_m"] <= 7:
        # replaced by a traced landmark (unless it is a small part fully inside, like the sphere)
        if not any(l.contains(g.centroid) and g.area < 0.15 * l.area for l in lm_g):
            continue
        f["properties"].update(height_m=SPHERE_H, height_source="estimated")
    f["properties"]["source"] = "osm"
    out.append(f)
taken = [shape(f["geometry"]).buffer(0) for f in out] + lm_g
tree = STRtree(taken)
added = 0
for f in ovt:
    p = f["properties"]
    if "Microsoft" not in json.dumps(p.get("sources", "")):
        continue                                  # OSM-derived: already in 1
    g = shape(f["geometry"]).buffer(0)
    if any(g.intersects(taken[i]) for i in tree.query(g)):
        continue
    out.append({"type": "Feature", "properties": {"osm_id": "", "type": "yes", "name": "", "height_m": 7,
                "height_source": "estimated", "source": "overture_ms"}, "geometry": f["geometry"]})
    added += 1
for f in lm:
    out.append({"type": "Feature", "properties": {"osm_id": "", "type": "landmark", **f["properties"]}, "geometry": f["geometry"]})
json.dump({"type": "FeatureCollection", "features": out}, open(out_file, "w", encoding="utf-8"), separators=(",", ":"))
from collections import Counter
print("total", len(out), Counter(f["properties"]["source"] for f in out), "| overture added", added)

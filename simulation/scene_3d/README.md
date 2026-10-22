# Frontend data for the 3D intersection view

These scripts build the files the 3D intersection view reads from
`frontend/public/data/INT_001/`. Everything is generated from data already in the
repository, so the view can be rebuilt whenever the network or the demand changes.

## Run

From the repository root:

```bash
pip install -r requirements.txt
python simulation/scene_3d/build_all.py              # roads, buildings, background
python simulation/scene_3d/build_all.py --with-sim   # also vehicles and signal states
```

`--with-sim` runs SUMO, so it needs the `sumo` command (an installed SUMO with `SUMO_HOME` set,
or `pip install eclipse-sumo`). A full run takes about 20 seconds.

## Inputs

| File | What it is |
|---|---|
| `data/processed/road_network/jaadah_study_area.net.xml` | The SUMO network |
| `data/raw/road_network/jaadah_study_area.osm` | OpenStreetMap extract of the study area |
| `data/raw/buildings/overture_buildings.geojson` | Building footprints from Overture Maps (adds the Microsoft footprints OSM lacks) |
| `data/raw/buildings/landmarks_traced.geojson` | 8 landmark outlines traced by the team from Esri World Imagery |
| `simulation/scenarios/tests/stress_test_v2.rou.xml` | Test demand used for the vehicles (`--with-sim` only) |

## Outputs

`frontend/public/data/INT_001/network/`

| File | Built by | Contents |
|---|---|---|
| `road_surface.geojson` | `build_network_layers.py` | Lane and junction surfaces, with height (negative in the underpass) |
| `road_markings.geojson` | `build_network_layers.py` | Lane dividers, edge lines and stop lines |
| `turn_arrows.geojson` | `build_network_layers.py` | Painted turn arrows before the stop lines |
| `flow_arrows.geojson` | `build_network_layers.py` | Direction chevrons along the roads |
| `underpass.geojson` | `build_underpass.py` | Open ramps, walls and roof of the Prince Turki Rd underpass |
| `streetscape.geojson` | `build_streetscape.py` | Kerbs, sidewalks and medians |
| `context.geojson` | `build_context.py` | Parking, green areas, land use and side streets around the roads |
| `buildings.geojson` | `extract_buildings.py`, `merge_buildings.py` | Building footprints with heights |
| `surface_detail.geojson` | `build_surface_detail.py` | Lane centre lines and paved aprons around buildings |

`frontend/public/data/INT_001/baseline/` (with `--with-sim`)

| File | Built by | Contents |
|---|---|---|
| `sim.json` | `convert_sim.py` | Vehicle paths and times from the SUMO run |
| `signals.json` | `convert_sim.py` | Signal heads and their state changes |

`tunnel.py` is shared by several scripts: SUMO's network is flat, so it gives every point on the
roads through the underpass its depth below street level.

## Order

`build_all.py` runs the scripts in this order:

1. `extract_buildings.py`, then `merge_buildings.py`
2. `build_network_layers.py`
3. `build_underpass.py` (needs the road surface from step 2)
4. `build_network_layers.py` again, so the edge lines stay off the underpass ramps
5. `build_streetscape.py`, `build_context.py`, `build_surface_detail.py`
6. With `--with-sim`: SUMO, then `convert_sim.py`

Each script can also be run on its own; its usage is at the top of the file.

## Notes

- The data is for display only. No KPI is calculated from it.
- Building heights: OSM rarely has them in Riyadh, so most heights are estimated (see
  `extract_buildings.py`). Each building records whether its height is from OSM or estimated.
- One OSM footprint is left out on purpose (`EXCLUDED_OSM_IDS` in `merge_buildings.py`): it
  duplicated the traced CST podium.
- The vehicles come from test demand. Replace the routes with the real demand once it exists.
- Map data: OpenStreetMap contributors (ODbL), Overture Maps Foundation (ODbL), Esri World
  Imagery for the traced landmarks.

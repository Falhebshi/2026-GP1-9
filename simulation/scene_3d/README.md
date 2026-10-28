# Frontend data for the 3D intersection view

These scripts build the files the 3D intersection view reads from
`frontend/public/data/INT_001/`. Everything is generated from data in the repository and from a
simulation run, so the view can be rebuilt whenever the network or the run changes.

## Run

From the repository root:

```bash
pip install -r requirements.txt
python simulation/scene_3d/build_all.py                   # roads, buildings, background, signal heads
python simulation/scene_3d/build_test_run.py              # the test run shown until the baseline run exists
python simulation/scene_3d/build_playback.py <run folder> \
    --run-id <run id> --run-start 2026-10-20T07:45:00+03:00 --duration-s 5400 \
    --warm-up-s 900 --clearance-s 900
```

`build_playback.py` turns one simulation run into the vehicles and signal indications. The run
folder holds the SUMO outputs `fcd.xml` (written with `--fcd-output.geo`, `--fcd-output.signals`
and `--device.fcd.period 0.4`) and `tls_states.xml` (the `SaveTLSStates` timed event), and the
manifest and demand files of the SUMO demand generation. `--run-start` is the real time of SUMO
second 0 (analysis start minus warm-up), `--duration-s` the length of the run, and `--warm-up-s`
and `--clearance-s` the parts before and after the analysis period, all in whole 15-minute
intervals (the window of the SUMO demand generation).

## Inputs

| File | What it is |
|---|---|
| `data/processed/road_network/jaadah_study_area.net.xml` | The SUMO network |
| `data/processed/road_network/network_mappings.json` | The network mappings (movements, approaches, signal links) |
| `data/raw/road_network/jaadah_study_area.osm` | OpenStreetMap extract of the study area |
| `data/raw/buildings/overture_buildings.geojson` | Building footprints from Overture Maps (adds the Microsoft footprints OSM lacks) |
| `data/raw/buildings/landmarks_traced.geojson` | 8 landmark outlines traced by the team from Esri World Imagery |
| a run folder | SUMO outputs and the demand files of one run (`build_playback.py` only) |

## Outputs

`frontend/public/data/INT_001/network/` (`build_all.py`)

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
| `signal_heads.json` | `build_signal_heads.py` | The signal heads of every approach, one per lane at the stop line, and the approach's movements |

`frontend/public/data/INT_001/<scenario>/` (`build_playback.py`)

| File | Contents |
|---|---|
| `run.json` | The run: ID, real start time, length, analysis period and its 15-minute vehicle files |
| `vehicles_HHMM.json` | The vehicles of one 15-minute interval, named by the interval end (`vehicles_0815.json` = 08:00–08:15). A sample on a boundary is in both files |
| `signals.json` | The indication (green, yellow, red) of every signal-controlled movement each time one changes |

The vehicle records and signal changes are produced by `backend/outputs/vehicles.py` and
`backend/outputs/signals.py` (M10-B) and are checked against the `VehicleState` and
`MovementSignalState` models. `build_playback.py` adds the underpass depth for display and stops
if the movements of one approach ever show different indications, because the view colours a
whole approach with one indication.

`tunnel.py` is shared by several scripts: SUMO's network is flat, so it gives every point on the
roads through the underpass its depth below street level.

## Order

`build_all.py` runs the scripts in this order:

1. `extract_buildings.py`, then `merge_buildings.py`
2. `build_network_layers.py`
3. `build_underpass.py` (needs the road surface from step 2)
4. `build_network_layers.py` again, so the edge lines stay off the underpass ramps
5. `build_streetscape.py`, `build_signal_heads.py`, `build_context.py`, `build_surface_detail.py`

Each script can also be run on its own; its usage is at the top of the file.

## Notes

- The data is for display only. No KPI is calculated from it.
- Building heights: OSM rarely has them in Riyadh, so most heights are estimated (see
  `extract_buildings.py`). Each building records whether its height is from OSM or estimated.
- One OSM footprint is left out on purpose (`EXCLUDED_OSM_IDS` in `merge_buildings.py`): it
  duplicated the traced CST podium.
- The committed `baseline/` files come from a test run (`TEST_SUMO_DEMAND_CHECK`), built with
  `python simulation/scene_3d/build_test_run.py`: made-up demand of 20 vehicles per movement and
  15-minute interval, planned with the SUMO demand generation and simulated with SUMO. Replace them
  with `build_playback.py` from the baseline run once it exists.
- No detector counts the tunnel movements (`MOV_N_S_TUNNEL`, `MOV_S_N_TUNNEL`,
  `MOV_TUNNEL_ONRAMP`), so the detector demand leaves the underpass empty. The test run gives them
  the same made-up demand as every other movement, for display only. They pass under the junction
  and no KPI uses this run.
- The view shows only the analysis period (`analysis_start_s` to `analysis_end_s` in `run.json`),
  never the warm-up, when the network is still filling up, or the clearance. The warm-up and
  clearance vehicles stay in the files.
- SUMO changes lanes in one step, as the KPIs need. The view spreads each lane change over 2 s
  on screen (`smoothLaneChanges` in `vehicles.js`); the files keep SUMO's positions.
- Map data: OpenStreetMap contributors (ODbL), Overture Maps Foundation (ODbL), Esri World
  Imagery for the traced landmarks.

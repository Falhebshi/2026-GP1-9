# SUMO network

This is a documentation file for the road network used by Jaadah's study-area simulation. The current network is `data/processed/road_network/jaadah_study_area.net.xml`. It is the file the checked-in test configurations and baseline runner load. The network mapping in `data/processed/road_network/network_mappings.json` describes Jaadah movements, lanes, detectors, and their SUMO IDs; it is a separate file and must stay consistent with the network.

## Files and structure

| File or folder | Purpose |
| --- | --- |
| `data/raw/road_network/jaadah_study_area.osm` | Original study-area OSM extract, not the edited simulation network. |
| `data/processed/road_network/jaadah_study_area.net.xml` | Current SUMO edges, lanes, connections, junctions, and traffic-light program. |
| `data/processed/road_network/network_mappings.json` | Jaadah approach, movement, route, lane, and detector mappings. |
| `data/processed/traffic_signals/jaadah_tls_program.xml` | Separate copy of the signal program; the baseline uses the program inside the `.net.xml`. |
| `data/processed/road_network/backups/` | Historical snapshots from earlier editing stages, not a replacement for the current network. |
| `simulation/configs/tests/` and `simulation/scenarios/tests/` | SUMO test configurations and their route files. |

The network contains the central signalized intersection, slip and bypass roads, U-turns, ramps, and a main road that passes under the surface junction. The underpass is separated by road connections in SUMO, but SUMO-GUI draws the roads on one plane. The 3D frontend adds visual depth separately; see [its scene guide](../simulation/scene_3d/README.md).

The current `.net.xml` has 299 edges (128 non-internal and 171 internal), 111 junctions, 628 connection elements, and one traffic-light program. An internal edge, whose ID starts with `:`, represents travel through a junction; an external edge is a road segment that routes name directly. Connections specify which incoming lane can reach which outgoing lane, including via an internal lane. A line that looks connected in SUMO-GUI is not by itself a legal route.

The mapping file currently defines four approaches, 18 complete movement routes, 16 canonical approach lanes, and 16 synthetic detector mappings. Its route IDs and lane chains belong to Jaadah's data model; they are not a second network. In particular, the 19 routes in the old fixed stress file are test paths with different names and boundaries, not the 18 canonical movement definitions. See [network mapping](network_mapping.md) for the actual assignments.

### Signal program

The central signal has one fixed 120-second program (`programID="0"`) inside the network. It serves one approach at a time in this order:

| Approach | Green | Yellow | All-red |
| --- | ---: | ---: | ---: |
| East | 40 s | 3 s | 2 s |
| South | 15 s | 3 s | 2 s |
| West | 30 s | 3 s | 2 s |
| North | 15 s | 3 s | 2 s |

Those 12 phases sum to 120 seconds. The separate `jaadah_tls_program.xml` is useful for inspection, but a SUMO config that loads only the `.net.xml` uses the network's embedded program. Pedestrian actuation on the real South-to-East movement is outside the current baseline model; the signal is fixed-time here. Signal changes affect both SUMO runs and the KPI engine's signal inputs, so check both after an edit.

### Network geometry versus measurement scope

The full road network is larger than the part Jaadah measures as an intersection approach. The 16 canonical approach lanes comprise 12 signal-entry lanes and four slip/bypass lanes. Outgoing roads, ramps, U-turn paths, and tunnel roads can still be part of complete SUMO routes without becoming extra canonical approach lanes. `network_mappings.json` chooses the ordered SUMO lane segments for each canonical lane and the upstream/downstream measurement distances. These boundaries are modeling choices; they are not implied by every edge visible in NetEdit.

The 16 synthetic detectors have modeled positions near selected lane endpoints. They are not surveyed RCRC detector coordinates. The current mapping leaves queue-detection lane lists empty while separate queue-measurement work uses its own zone definitions. If an edit shifts, splits, or removes a mapped lane, check detector positions and measurement-zone distances as well as route legality. [Network mapping](network_mapping.md) documents the lane chains and detector assumptions; [KPI measurements](kpi_measurements.md) explains how those zones affect reported delay and queue values.

## How the network reached this state

- The original OSM extract was converted and then edited for the study area. The checked-in network includes manual road and lane geometry, connections, speed limits, slip roads, ramps, U-turns, and the traffic signal. The snapshots in `backups/` show earlier stages.
- Commit `2092709` (16 October 2026) edited the `.net.xml` in NetEdit, changing junction/internal-lane geometry and some road-lane shapes and connections, and added the `stress_test_v2` assets. For example, its diff changes the north off-ramp connections from `133973525#0` and the south approach fan-out from `539502456#7` to `539502456#8`. These are lane-connection edits, not merely drawing changes. Treat the current `.net.xml` as authoritative rather than rebuilding it from the OSM extract.
- Commit `51191b7` (28 October 2026) changed the **mapping routes**, not the network geometry: five West-origin routes now begin at `133793906#0` instead of `133793727#0`. At 600 vehicles/hour in the documented demand check, the earlier start caused up to about 22 seconds of insertion delay; the revised start reduced that to about 1.4 seconds. See [KPI measurements](kpi_measurements.md) for the measurement context. The old `stress_test_v2.rou.xml` still starts some routes on the earlier edge, so it does not represent the current generated-demand routes.

The mapping currently labels the network `jaadah_network_v2` and its own data revision `2.4-west-route-start`. If a network edit changes edge or lane IDs, geometry used for measurements, connections, or signal phases, review the mapping, routes, network checksum, and downstream KPI assumptions together. [Network mapping](network_mapping.md) explains the checksum and version rules.

The October network diff gives two concrete examples of why this review matters. On the north off-ramp, the direct connections from `133973525#0` to `133973525#0-AddedOffRampEdge` were reduced from four to three and their lane targets changed. At the south approach split, the connections from `539502456#7` toward `539502456#8` and `569790078` changed their lane assignments. The same commit also changed internal connector shapes and lengths. A vehicle's ability to follow a turn depends on those connection records, while measured travel distance and queue positions can depend on the edited geometry. The commit does not by itself prove that every possible route was revalidated; use the checks below after future edits.

### What the snapshots can tell us

The backup filenames describe editing stages, but they are not a complete, dated change log. Their contents show the scale of the study-area reduction and later connection work:

| Snapshot | External edges | Connections | How to use it |
| --- | ---: | ---: | --- |
| `backups/jaadah_study_area_before_reduction.net.xml` | 1,597 | 8,571 | Larger imported network before the study-area reduction. |
| `backups/jaadah_study_area_before_corrections.net.xml` | 1,590 | 8,351 | Another large historical state, still much wider than today's model. |
| `backups/jaadah_study_area_before_signals.net.xml` | 128 | 634 | Reduced network snapshot; its name alone does not establish the absence of every traffic-light element. |
| `backups/jaadah_study_area_pre_network_fixes_backup.net.xml` | 128 | 634 | Snapshot before the later network fixes. |
| `backups/jaadah_study_area_post_fixes_test_b_backup.net.xml` | 128 | 628 | Snapshot after those fixes; compare it with the current file when investigating a later difference. |
| `jaadah_study_area.net.xml` | 128 | 628 | Current file used by test and baseline configurations. |

The snapshots are evidence for comparing XML, not files to substitute into an existing simulation config. The historical `.netccfg` shows the original OSM import settings: geometry removal, junction joining, signal and ramp guessing, and removal of several non-road vehicle classes. Those settings do not recreate the team's subsequent NetEdit changes or the current mapping.

## Open and inspect it

Install SUMO and make `sumo` and `netedit` available on your `PATH`. From the repository root:

```powershell
netedit --sumo-net-file data/processed/road_network/jaadah_study_area.net.xml
```

Open the `.net.xml` directly. The checked-in `.netecfg` and `.netccfg` are historical NetEdit/netconvert configurations with machine-specific or stale input paths; they are not portable one-command rebuild recipes. If you save a network edit, check the diff before replacing the current file. Revalidate mapped edge and lane IDs, legal routes, connections, and the signal program after any change. Rebuilding from OSM alone would lose manual edits.

In NetEdit, inspect edges and lanes around the relevant junction, then inspect the lane-to-lane connections and traffic-light program before changing them. For a route problem, follow the route's ordered edges from the mapping JSON or route XML and check each handoff between edges. For a geometry problem, check whether the visible line is an external road lane or a generated internal junction lane. SUMO may regenerate internal IDs when junction connections change, which can affect routes and measurements that refer to lanes.

To inspect traffic in SUMO-GUI, open one of the test `.sumocfg` files under `simulation/configs/tests/`, or start it from the repository root:

```powershell
sumo-gui -c simulation/configs/tests/smoke_test.sumocfg
```

The configs resolve their network and route paths relative to their own folder. For command-line runs:

```powershell
sumo -c simulation/configs/tests/smoke_test.sumocfg
sumo -c simulation/configs/tests/stress_test.sumocfg
```

These are temporary validation routes, not the synthetic baseline demand. The smoke config ends at 300 simulation seconds; the original stress config ends at 600. Their route files are in `simulation/scenarios/tests/`.

### What each fixed test drives

The smoke route file schedules seven individual vehicles at the central junction. It is useful for seeing whether the selected signalized turns load and finish, but it does not exercise every ramp, U-turn, tunnel, or mapped movement.

The original stress route file defines 19 named route paths and 19 flows, totalling 349 planned vehicles. Six central signalized routes have 25 vehicles each; slip/bypass and east ramp/continuation routes have 12 each; two tunnel through routes have 40 each and a tunnel on-ramp has 15; two West U-turns and two additional road movements have 8 each. Most flows depart between 0 and 360 seconds; the U-turn and additional movements depart between 30 and 330 seconds. The config continues to 600 seconds so the fixed demand has time to clear. Those counts are test inputs, not observed intersection volumes.

`stress_test_v2.rou.xml` keeps the same 19 route families and 349 planned vehicles, but extends many routes toward the model boundaries. Its `vType` also sets `lcSpeedGain="0.3"`, while its config sets a 2-second lane-change duration and a 0.2-second step. That makes v2 a different experiment. Do not use its output or tuning as the baseline network's normal traffic behavior.

## Stress tests and what they show

| Check | Setup | Evidence and limit |
| --- | --- | --- |
| Smoke | `smoke_test.sumocfg` with `smoke_test_routes.rou.xml` | A direct SUMO 1.27.1 run on the current network reached 300 s, inserted 7 vehicles, and ended with none running or waiting. This is a small connectivity check. |
| Original stress | `stress_test.sumocfg` with `stress_test_routes.rou.xml` | A direct SUMO 1.27.1 run on the current network reached 600 s, inserted 349 vehicles, and ended with none running or waiting. This checks its fixed test demand, not real-world capacity. |
| Stress v2 | `stress_test_v2.sumocfg` with `stress_test_v2.rou.xml` | A separate 600 s test configuration with seed 42, 0.2 s steps, and `lanechange.duration=2`; it writes logs, statistics, trips, lane changes, and collisions to `simulation/outputs/tests/stress_test_v2/`. These settings are for this test/visualization and are **not** baseline demand settings. Its generated results are ignored by Git, so the repository does not provide a reproducible completed-run result for v2. |
| Generated-demand check | `simulation/scripts/tests/run_sumo_demand_check.py` | The [demand-generation documentation](sumo_demand_generation.md) reports that the seed-42 check inserted all 1,080 vehicles, with no teleports or collisions, and 297 of 300 slip-road vehicles crossed in their interval. This checks generated demand, not either fixed stress route file. |

The smoke and original stress results above were reproduced against the current `.net.xml` with direct SUMO 1.27.1 commands. Their standard output establishes the end times, insertion totals, and final running/waiting counts. Those commands did not produce dedicated collision or teleport statistics, so these results should not be read as a numerical collision/teleport audit. For v2, the config describes the intended 600-second run, but generated output is ignored by Git; a teammate must run it and inspect its log and statistics before claiming a completed result.

Later generated-demand and KPI checks probe a different question: what happens when demand is created from Jaadah's movement mapping. [KPI measurements](kpi_measurements.md) records checks at 80 and 600 vehicles/hour per demand movement, plus a 1,600 vehicles/hour overload case. At 600 vehicles/hour, the South left turn exceeds its approximate 440 vehicles/hour capacity, the longest approach queue reaches 314 m, and the check still passes its stated measurement rules. In the overload case, 4,689 of 14,400 planned vehicles could not enter before the run ended; the measurement pipeline records them as uninserted rather than pretending they traversed the intersection. These are documented simulation checks, not evidence that the modeled capacity or traffic demand has been calibrated to observed road conditions.

For a route-by-route check against the **current mapping**, use `python simulation/scripts/tests/run_movement_smoke.py` from the repository root. It runs each of the 18 mapped movements in isolation and records arrival and teleport results under `simulation/outputs/tests/movement_smoke/`. Use `--out` with a fresh folder if you need to preserve existing results. The demand check is documented in [SUMO demand generation](sumo_demand_generation.md). Neither test proves that all real traffic conditions have been calibrated or that a changed network remains compatible with the KPI pipeline.

After a network edit, a practical order is: inspect the `.net.xml` diff; check edge and lane IDs used by `network_mappings.json`; review signal phases and lane connections in NetEdit; run the short fixed tests; then run the 18-movement check and generated-demand check if their inputs are available. Compare their outputs with the previous run using the same SUMO version and test demand. A green fixed stress run cannot replace movement-by-movement validation, and a mapping check cannot replace a live SUMO run.

## Precautions and troubleshooting

- **A route or lane ID is missing:** compare the test route or `network_mappings.json` with the current `.net.xml`. After editing in NetEdit, run the mapping validator/tests and the 18-movement smoke check before using generated demand. Do not copy an ID from a historical backup without checking its connections.
- **Vehicles wait before appearing in the network:** check the departure edge and lane as well as the in-network queue. Insertion delay is not intersection control delay; the West route-start correction above is an example.
- **A test reports teleports, collisions, or unfinished vehicles:** inspect its SUMO log, route file, demand level, and end time. A successful process exit alone does not establish that a stress test passed every traffic check.
- **NetEdit or netconvert cannot find an input:** open the current `.net.xml` directly instead of relying on the stored `.netecfg` or `.netccfg` paths. Keep the original and the edited file distinct until the route and mapping checks pass.
- **The underpass looks flat in SUMO-GUI:** this is a display limitation of the network view, not proof that the two roads connect. Inspect the actual junction connections and routes.

The test routes and configuration outputs do not define final baseline demand. Use the generated-demand and scenario-run workflow in [simulation integration](simulation_integration.md) for baseline runs.

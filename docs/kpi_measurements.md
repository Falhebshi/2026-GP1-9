# KPI Measurements

The KPI engine (`kpi_engine.md`) calculates its indicators from canonical measurement records. This document defines how those records are produced from a SUMO run: where each measurement is taken, and the rules that turn SUMO's output into the records.

The engine itself does not depend on these rules; it uses the finished records.

The code is in the `jaadah/kpi_inputs/` package, with its tests in `jaadah/kpi_inputs/kpi_inputs_tests/`:

```text
jaadah/kpi_inputs/
├── __init__.py
├── network_inputs.py     the engine's lanes, movements and movement attributes
├── signal_program.py     the run's SignalProgram from the network file
├── vehicle_passages.py   VehicleDelayRecord and IncompletePassage from FCD output
├── cycle_queues.py       CycleQueueRecord and ApproachCycleQueueRecord from FCD output
└── kpi_inputs_tests/
    ├── __init__.py
    ├── test_cycle_queues.py
    ├── test_network_inputs.py
    ├── test_signal_program.py
    └── test_vehicle_passages.py
```

`simulation/scripts/tests/run_kpi_measurement_check.py` runs SUMO once with the measurement output and checks the records (section 6).

---

# 1. Measurement Zones

Delay, queue duration and throughput are measured per vehicle while it passes through the **measurement zone** of its approach. Each zone has two parts:

- **upstream**, a fixed distance before the stop line, along the vehicle's route;
- **downstream**, a fixed distance after the **junction exit**, the end of the junction's internal lane, where the outgoing road begins.

| Approach | Upstream (before the stop line) | Downstream (after the junction exit) | Approach speed limit |
| --- | --- | --- | --- |
| East | 388 m | 155 m | 90 km/h |
| West | 450 m | 105 m | 70 km/h |
| North | 500 m | 65 m | 50 km/h |
| South | 500 m | 65 m | 50 km/h |

The upstream distances come from the Approach Study Distances Reference. The distances are stored on each approach in `network_mappings.json` (`zone_upstream_m`, `zone_downstream_m`; see [Network mapping](network_mapping.md#measurement-zones)), and the network validator checks that every movement's route starts before its zone and continues beyond it, so each zone lies entirely inside the modelled network.

A vehicle's zone is therefore the upstream part, the path through the junction, and the downstream part. The path through the junction differs by movement (about 46–70 m for the signalised movements and under 8 m for the slips), so the zone length differs by movement. Within a movement it differs by a few metres with the lane a vehicle uses through the junction (for `MOV_E_S`, about 589–593 m).

## 1.1 Reference points

- **Stop line:** the end of the last SUMO lane of the movement's canonical lanes (`LaneMapping.sumo_lane_ids`).
- **Junction exit:** the end of the junction's internal lane(s) on the vehicle's path, which is the start of the next route edge.

Distances are path lengths along the lanes the vehicle drives, using the lane lengths in the network file, not straight-line distances:

- **zone entry:** the point `zone_upstream_m` before the stop line; it usually falls inside a lane, several lanes back;
- **zone exit:** the point `zone_downstream_m` after the junction exit.

Example: `MOV_E_W` has 388 m before the stop line, its 63.8 m internal lane, and 155 m of outgoing road, so its zone is 606.8 m long.

The lanes of one road in this network differ in length by less than 0.5 m, so the boundaries do not depend on which lane of a road the vehicle uses.

## 1.2 Why the downstream part is measured from the junction exit

Measured from the stop line, North's 65 m would end the zone inside the junction for left turners, whose path through it is 64–70 m long. Measuring from the junction exit gives every movement its whole path through the junction plus a stretch of outgoing road, where vehicles that stopped regain their speed.

## 1.3 Why a fixed distance is enough

A vehicle starting from the stop line regains the speed limit within speed² ÷ (2 × acceleration), with SUMO's passenger-car acceleration of 2.6 m/s²:

| Approach | Speed limit | Distance to regain it from a stop | Distance available after the stop line |
| --- | --- | --- | --- |
| East | 25.0 m/s | ≈120 m | junction + 155 m |
| West | 19.4 m/s | ≈72 m | junction + 105 m |
| North, South | 13.9 m/s | ≈37 m | junction + 65 m |

The acceleration after a stop therefore lies inside the zone. A fixed zone was preferred to ending each vehicle's zone where it regains its speed, because every vehicle of a movement is then measured over the same stretch of road.

---

# 2. Control Delay and Queue Duration

Each vehicle that enters a zone produces one `VehicleDelayRecord` (data model section 4.3), or an `IncompletePassage` (section 4.4) when it has not left the zone when the run ends. Records are produced from SUMO's vehicle position output (FCD), recorded every 0.4 s.

Implemented in `jaadah/kpi_inputs/vehicle_passages.py` (`collect_vehicle_passages`).

## 2.1 Crossing times

A vehicle almost never stands exactly on the zone entry, the stop line or the zone exit at an FCD time. Each crossing time is **interpolated** between the two FCD rows on either side of the point.

Example: a vehicle 394 m before the stop line at 08:03:10.0 and 384 m before it at 08:03:10.4 crossed the 388 m zone entry 6 m into those 10 m, at 08:03:10.0 + 0.6 × 0.4 s = **08:03:10.24**.

Taking the first row past each point instead would place both the entry and the exit up to 0.4 s late, by different amounts, so the time in the zone could appear up to 0.4 s shorter than it was. A vehicle that met no delay would then show a negative time loss.

## 2.2 Free-flow travel time

The free-flow travel time is how long the vehicle itself would take through its zone with no other traffic and no signal:

free-flow time = Σ over the pieces of its path (length ÷ (the piece's speed limit × the vehicle's speed factor))

- **Each piece uses its own speed limit:** approach lanes, the junction's internal lane, and outgoing lanes, along the lanes the vehicle actually used. A turning vehicle drives the junction at the internal lane's lower speed (East's left turn: 61 km/h against the approach's 90 km/h); one speed for the whole zone would charge every turning vehicle delay it did not suffer.
- **Each vehicle uses its own desired speed:** SUMO gives every vehicle a speed factor (spread of about ±10 % around 1.0, from the vehicle type's `speedDev`), so a vehicle with factor 1.1 drives 10 % above the limit on an empty road. Measuring against the limit alone would give such a vehicle a negative time loss and a slow driver delay it did not suffer. Each vehicle's speed factor is read from SUMO's output. This matches SUMO's own definition of time loss, which allows a check against the tripinfo output.
- Lengths at the zone entry and exit count only the part of the piece inside the zone.

The departure planning of the demand writer uses the speed limit (factor 1.0) for every vehicle, because the factors are drawn by SUMO only when each vehicle is created. It aims the average vehicle at its planned time; the measurement uses each vehicle's actual factor.

## 2.3 Rounding tolerance

After interpolation, rounding can still leave a vehicle that met no delay slightly below zero. A time loss between −0.4 s (one FCD step) and 0 is recorded as 0: the free-flow time is set to the time in the zone. A time loss below −0.4 s is an error, because it can only come from a fault in the measurement.

## 2.4 Time stopped

`halted_time_s` is the time the vehicle stood still between its zone entry and exit: the FCD steps in which its speed was below 0.1 m/s, SUMO's standstill threshold.

## 2.5 Clearance

A vehicle that arrived in the analysis period but has not left its zone when the run ends has no time loss, and the engine reports its interval as `unavailable` (KPI engine section 7.4). The clearance (`SimulationConfig.clearance_duration_s`) must be long enough for the last arrivals to leave their zones.

## 2.6 Inputs and position along the path

| Input | SUMO option or file | Provides |
| --- | --- | --- |
| FCD output | `--fcd-output`, `--device.fcd.period 0.4`, `--fcd-output.attributes lane,pos,speed,odometer` | each vehicle's lane, position on the lane, speed and odometer every 0.4 s |
| tripinfo output | `--tripinfo-output`, `--tripinfo-output.write-unfinished true` | each vehicle's speed factor, including vehicles unfinished at the end |
| Output precision | `--precision 3` | three decimals; with the default two, speed factors such as `1.07` are rounded by up to 0.005 (about 0.1 s of free-flow time on a 600 m zone) |
| Demand manifest and demand file | written by `jaadah/sumo_demand` | vehicle → demand record → movement (KPI engine section 13.6) |

SUMO does not write the speed factor in FCD output, so it is taken from tripinfo.

The position along a vehicle's path is its **odometer**, the distance SUMO has driven it since it entered the network. It includes the junctions' internal lanes and the vehicle's lane changes, so no path length is rebuilt from the network file:

- **stop line:** the vehicle's last row on the stop-line edge, plus the rest of that lane (lane length − pos). Example: odometer 512.3 m with 6.1 m left on the lane places the stop line at 518.4 m;
- **junction exit:** the first row on the next route edge, minus its pos;
- **zone entry and exit:** `zone_upstream_m` before the stop line and `zone_downstream_m` after the junction exit.

A vehicle still queued before the stop-line edge when the run ends has no row on that edge. Its stop line is placed from its last row on an earlier route edge: the rest of that lane, plus the route length from there to the stop line (edges and junction internal lanes, from the network file). It is recorded as an `IncompletePassage` if it had entered its zone, never dropped.

Every vehicle that entered its zone during the run is recorded, including those of the warm-up and clearance; the engine uses those that arrived in the analysis period.

---

# 3. Signal Program

Implemented in `jaadah/kpi_inputs/signal_program.py` (`build_signal_program`).

The HCM saturation flow, capacity, v/c and delay use the run's `SignalProgram`. It is built from the traffic-light plan in the network file that SUMO runs, so the simulation and the HCM calculation use the same greens (KPI engine section 13.6).

## 3.1 Rules

- **Plan:** the plan of the intersection's signal (`IntersectionMapping.sumo_tls_id`); only fixed-time (`static`) plans are supported. When the signal has several plans, one is chosen with `program_id`.
- **Steps:** consecutive steps with the same state count as one step, so a green written as two identical steps is one green.
- **Phases:** each step with a green (`G`) starts a phase; the yellow steps after it are its yellow time and the all-red steps its all-red time. The plan must start with a green.
- **A movement may have several greens per cycle:** it is then listed in each phase that serves it, and the engine keeps its capacity and reports its HCM delay as `unavailable` (KPI engine section 9.5).
- **Overlaps are not supported:** a movement that stays green from one phase into the next (including from the last phase into the first) would look like two separate greens, with its lost time counted twice and its HCM delay `unavailable` for the wrong reason. `SignalProgram` represents sequential, non-overlapping phases only, so such a plan is rejected. The study-area plan serves one approach at a time and ends every green with yellow and all-red before the next begins, so it has no overlap.
- **Served movements:** a movement is served by a phase when all of its signal links (`MovementMapping.signal_crossings`) are green in the phase's green step. Only the analysed movements, those with `MovementAttributes`, are listed. Ramps and U-turns share their phases with analysed movements, so leaving them out changes no phase timing.
- **Source:** `baseline_model`, so the engine reports the signal timing as a *modelled assumption*.
- **Network:** the network file must match the mapping's network checksum.

A plan the engine cannot use correctly is rejected with every problem listed, rather than approximated: signal states other than `G`, `y` and `r` (such as a permitted green `g`), an overlap, a movement only partly green in a step, a green that serves no analysed movement, or an analysed signalised movement that is never green.

## 3.2 Study-area plan

| Phase | Movements | Green | Yellow | All-red |
| --- | --- | --- | --- | --- |
| `PHASE_1` | `MOV_E_W`, `MOV_E_S` | 40 s | 3 s | 2 s |
| `PHASE_2` | `MOV_S_W` | 15 s | 3 s | 2 s |
| `PHASE_3` | `MOV_W_E`, `MOV_W_N` | 30 s | 3 s | 2 s |
| `PHASE_4` | `MOV_N_E` | 15 s | 3 s | 2 s |

Cycle length: 120 s. The slips are unsignalised and appear in no phase.

---

# 4. Network Inputs

Implemented in `jaadah/kpi_inputs/network_inputs.py` (`build_network_inputs`).

The engine functions take three network inputs. They are taken from the loaded network mapping:

| Input | Source | Used for |
| --- | --- | --- |
| `lanes` | `approach_lanes` | lane groups, saturation flow, queues |
| `movements` | `canonical_movements` of the analysed movements | roll-up to approaches |
| `movement_attributes` | `movement_attributes`, keyed by movement ID | lane groups, HCM factors, slip handling |

Only the analysed movements, those with `MovementAttributes`, are included; ramp, U-turn and tunnel movements have no KPIs.

The mapping accepts drafts in which some attributes are missing; the engine does not. A mapping is rejected, with every gap listed, when an approach lane serves a movement without attributes, or when an analysed movement is served by no approach lane and so has no lane group, capacity or queue.

With these inputs and the signal program (section 3), the engine calculates the HCM saturation flow, capacity, v/c, HCM delay and level of service without any simulation output; only the demand is needed besides. `backend/analytics/kpi/kpi_tests/test_study_area_inputs.py` runs the engine on the study area's real inputs.

---

# 5. Queue Length

Implemented in `jaadah/kpi_inputs/cycle_queues.py` (`collect_cycle_queues`). Queues are measured from the same FCD output as the vehicle passages (section 2.6), read once step by step without keeping the rows, so memory does not grow with the number of vehicles. Lane queues and approach queues are measured with the same rules.

## 5.1 Lane sections

Each canonical lane's queue is measured over its **section** (KPI engine section 13.1): its lane chain (`LaneMapping.sumo_lane_ids`) together with the junction lanes that join the chain's segments, from the start of the first segment to the stop line. A junction lane between two segments can be long, and vehicles on it are part of the section.

| Lanes | Lane chain segments | Junction lanes between them | Section |
| --- | --- | --- | --- |
| East 1–4 | 388.1 m | 6.8 m | 394.8 m |
| South 1–2 | 86.3 m | 32.6 m | 118.9 m |
| South 3–4 (bypass) | 183.4 m | 23.8 m | 207.2 m |
| West 1–3 | 91.9 m | 3.1 m | 95.0 m |
| West 4 (slip) | 107.7 m | 3.1 m | 110.8 m |
| North 1–3 | 82.0 m | 2.8 m | 84.8 m |
| North 4 (slip) | 113.2 m | 2.1 m | 115.3 m |

## 5.2 What counts as queued

A vehicle is queued when it is slower than **1.39 m/s (5 km/h) for at least 1 s**. Vehicles creeping at the back of a queue count, so the queue length is how far back the queue reaches; with a standstill-only rule, a long queue moving forward a metre would briefly look much shorter. Queue duration keeps its standstill threshold (section 2.4), because it measures the time a vehicle stood still.

## 5.3 Queue length at one moment

The queue is **anchored at the stop line**: it starts with a queued vehicle whose front is less than **10 m** from the stop line, and continues through queued vehicles less than 10 m behind the back of the one before. Its length is the distance from the stop line to the back of its last vehicle (vehicle fronts from FCD, plus the 5 m vehicle length). Queued vehicles separated from it by a larger gap are not part of it.

Example: 8 cars stopped every 7.5 m from 1 m before the stop line give a queue of 1 + 7 × 7.5 + 5 = 58.5 m and 8 vehicles. A group of slow cars at 75–95 m, more than 10 m behind, is not part of it.

## 5.4 Queues that reach the section end

When the back of a lane's queue is less than 10 m from the start of its section, the queue may continue upstream, where lanes merge and a queued vehicle belongs to the approach but to no single lane. The lane's queue is then capped at the section length and the record is marked `reaches_section_end`; the KPI engine reports it as a minimum value, and the full queue is measured on the approach (KPI engine section 13.1).

## 5.5 Records

One `CycleQueueRecord` (data model section 4.5) is written for every canonical lane and every whole signal cycle of the run, aligned with the cycle start (KPI engine section 6.1). The cycle is the signal program's (120 s, section 3), and the signal's offset must be a whole number of cycles. The record holds the longest queue of the cycle in metres and in vehicles, each the largest of the cycle, and whether the queue reached the section end during the cycle. A cycle without a queue is a measured 0.

## 5.6 Approach queue

The full queue of an approach answers how far back from the signal its queue reaches, over the approach's whole upstream zone (`zone_upstream_m`: East 388 m, West 450 m, North and South 500 m) and across the points where its lanes merge. It is measured with the same rules as the lane queues (sections 5.2 and 5.3), anchored at the **signal stop line**, over:

- the sections of the lanes that serve the approach's signalised movements;
- the route edges behind them, back to the zone start;
- the junction lanes between those edges, each with its own length (on West, 9.8–12.7 m by lane at the first junction).

Slip and bypass lanes are left out; their queues are lane queues. Vehicles on the road behind the signal lanes count whichever way they turn: a vehicle heading for a slip that waits behind the signal queue is part of it.

When the back of the queue is less than 10 m from the far end of the zone, the queue may continue beyond what is measured: it is capped at the zone length and the record is marked `reaches_zone_end`.

One `ApproachCycleQueueRecord` (data model section 4.6) is written for every approach with signalised movements and every whole signal cycle of the run, with the longest queue of the cycle in metres and vehicles. An approach's queue continues its lanes' queues, so it is never shorter than the queue of one of its signal lanes in the same cycle.

---

# 6. Measurement Check

`simulation/scripts/tests/run_kpi_measurement_check.py` generates demand with `jaadah/sumo_demand` (hand-made by default, or from a `SimulationDemand` file with `--demand`), builds the signal program, runs SUMO once with the inputs of section 2.6, and reduces the output to records. It passes when:

1. SUMO ends without an error;
2. every vehicle that arrived in its zone during the analysis period has left it by the end of the run, so the clearance is long enough;
3. no vehicle's time loss in its zone exceeds its time loss over the whole trip reported by SUMO (tripinfo `timeLoss`) by more than one FCD period, since the zone is part of the trip;
4. every canonical lane and every signalised approach has a queue record for every whole signal cycle of the run, since a missing record would be reported as unavailable;
5. no approach's queue is shorter than the queue of one of its signal lanes in the same cycle.

The records are saved as `vehicle_delay_records.json`, `incomplete_passages.json`, `cycle_queue_records.json` and `approach_cycle_queue_records.json`, with a `summary.json`, in `simulation/outputs/tests/kpi_measurement_check/`, which is not committed. The script exits with 0 when all rules pass, 1 when a rule fails, and 2 when the check cannot run.

Results of the check with hand-made demand, the same for every demand movement:

| Demand per movement | Vehicles | Rules | South left time loss | Longest lane queue | Cycles reaching a section end (of 30) | Longest approach queue |
| --- | --- | --- | --- | --- | --- | --- |
| 80 veh/h | 1,080 | all pass | 51 s | 3 vehicles (21 m) | none | 21 m |
| 600 veh/h | 8,100 | all pass | 204 s | 16 vehicles (South lane 2, its whole 118.9 m section) | South 25–28, West 1–7 | South 291 m (54 vehicles) |

At 600 veh/h South's left turn is over its capacity of about 440 veh/h, so its queue grows beyond its lanes' sections and reaches 291 m back on the approach; no approach queue reaches its zone end. The slip lanes have no queue at either level.

At 600 veh/h West's vehicles wait up to 22 s to enter the network although West's queue reaches only 104 m: the demand file inserts every West vehicle on lane 0 of the three-lane entry edge (`departLane="best"`), and one lane cannot take 1,800 veh/h at full speed. South's vehicles, also all on one entry lane, wait up to 5.5 s. A long wait to enter is therefore not on its own evidence that the queue reached the model edge.

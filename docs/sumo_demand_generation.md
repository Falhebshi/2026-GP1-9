# SUMO Demand Generation

## Overview

Jaadah's SUMO demand generation converts movement-level `SimulationDemand` records into the traffic input that SUMO simulates.

For each demand record requesting `N` vehicles on a movement in a 15-minute interval, it creates exactly `N` vehicles on the movement's mapped SUMO route, each with a reproducible departure time inside the run.

The generation flow is:

```text
SimulationDemand records
        |
        v
Run window and record checks
        |
        v
Departure planning
        |
        v
DemandPlan (planned departures)
        |
        v
File writing
        |
        v
SUMO route file, manifest and demand file
```

SUMO demand generation does not transform detector observations into movement demand, run SUMO, or read SUMO results.

---

## Package Structure

The implementation is located under:

```text
jaadah/
└── sumo_demand/
    ├── __init__.py
    ├── planner.py
    ├── writer.py
    ├── checks.py
    └── sumo_demand_tests/
        ├── __init__.py
        ├── test_sumo_demand_planner.py
        ├── test_sumo_demand_writer.py
        └── test_sumo_demand_checks.py
```

The tests are kept with the module, in `jaadah/sumo_demand/sumo_demand_tests/`.

Each module has a separate responsibility:

| Module | Responsibility |
|---|---|
| `planner.py` | Builds the run window, checks the demand records and plans every vehicle's departure |
| `writer.py` | Writes the SUMO route file, the manifest and the demand file, and returns their fingerprints |
| `checks.py` | Checks the files of a generated folder before a run |

The planner contains no file output, and the writer contains no planning logic.

---

## Role in the Jaadah Data Pipeline

```text
TrafficObservation
        |
        v
Traffic demand transformation
        |
        v
SimulationDemand
        |
        v
SUMO demand generation
        |
        v
SUMO route file  ------------------>  SUMO simulation run
manifest + demand file  ----------->  output standardization and KPI engine
```

The SUMO route file is SUMO's input format and is read by SUMO only. Jaadah components read the manifest and the demand file instead, so that no component outside the simulation needs to parse SUMO XML.

---

## Run Window

One simulation run covers three consecutive parts:

```text
| warm-up | analysis period | clearance |
```

The analysis period is `Scenario.start_time` to `Scenario.end_time`. The warm-up and clearance durations come from `SimulationConfig`.

SUMO counts time in seconds from 0. Second 0 is the analysis start minus the warm-up.

For an 08:00–09:00 analysis with 15 minutes of warm-up and 15 minutes of clearance:

| Real time | SUMO second | Part |
|---|---:|---|
| 07:45 | 0 | warm-up starts |
| 08:00 | 900 | analysis starts |
| 09:00 | 4500 | clearance starts |
| 09:15 | 5400 | run ends |

The run contains 6 demand intervals: one in the warm-up, four in the analysis period and one in the clearance.

Demand is generated for the warm-up and the clearance as well as for the analysis period:

- during the warm-up, so that queues and signal state are realistic when the analysis period starts;
- during the clearance, so that the last analysis-period vehicles finish their passage in realistic traffic rather than in an emptying network.

`build_run_window` raises an error when:

- the scenario has no `end_time`;
- the warm-up, analysis period or clearance is not a whole number of 15-minute intervals;
- the analysis period does not start on a quarter hour (:00, :15, :30 or :45);
- `SimulationConfig.simulation_duration_s` is set and differs from warm-up + analysis period + clearance.

---

## Required Demand Records

The movements that receive demand are the candidate movements of every detector mapping whose status is not `unresolved`. For the study area these are nine movements:

- `MOV_E_W`, `MOV_E_S`
- `MOV_W_E`, `MOV_W_N`
- `MOV_N_E`, `MOV_S_W`
- `MOV_W_S_SLIP`, `MOV_N_W_SLIP`, `MOV_S_E_BYPASS`

Each of these movements must have exactly one record for every interval of the run. For an 08:00–09:00 analysis this is 6 intervals × 9 movements = 54 records.

Before any vehicle is planned, every record is checked. Generation stops with a `DemandPlanningError` that lists every problem found when:

| Problem | Example message |
|---|---|
| A movement is not in the mapping | `DEM_X (MOV_X, 2026-10-20T08:00:00+03:00): unknown movement` |
| A mapped movement receives no detector demand | `... movement receives no detector demand` |
| An interval is not 15 minutes long | `... interval is not 15 minutes` |
| An interval is off the 15-minute grid or outside the run | `... interval is outside the run window or not on the 15-minute grid` |
| A movement has two records for one interval | `... duplicate record for this movement and interval` |
| A record is missing | `missing demand: MOV_E_S 2026-10-20T08:15:00+03:00 - 2026-10-20T08:30:00+03:00` |

A missing record is never treated as zero vehicles. Zero vehicles on one movement also changes the traffic of the movements that share its lanes: with no left-turning vehicles on `MOV_E_S`, the lane it shares with `MOV_E_W` is emptier than it really was, and the delays and queues of `MOV_E_W` come out too low without any visible sign. For synthetic demand, every detector reports in every interval, so a missing record indicates an error in an earlier stage.

Records with `vehicle_count = 0` are valid: they are measured zeros, not missing data.

---

## Routes

Each movement is simulated on its own mapped route, `MovementMapping.sumo_route_edge_ids`.

A detector counts vehicles at the stop line and cannot see what a vehicle does beyond it. The through-detector counts therefore contain several routes:

| Movement | Contains these routes |
|---|---|
| `MOV_E_W` | `MOV_E_W`, `MOV_E_W_ONRAMP`, `MOV_E_E_UTURN` |
| `MOV_W_E` | `MOV_W_E`, `MOV_W_E_OFFRAMP`, `MOV_E_E_UTURN` |

No detector measures how a through count divides between these routes, so the count is not split. All of it is simulated on the movement's main route.

This keeps three properties:

- no turning split is invented (Data Design, section 6.4);
- the number of vehicles at every stop line equals the detector count;
- the demand simulated in SUMO equals the demand `v` used by the KPI engine's capacity and volume-to-capacity calculation (KPI Engine, section 9.7).

The six routes that pass no detector receive no demand: `MOV_W_W_UTURN`, `MOV_S_S_UTURN`, `MOV_N_N_UTURN`, `MOV_N_S_TUNNEL`, `MOV_S_N_TUNNEL` and `MOV_TUNNEL_ONRAMP`.

---

## Departure Times

A demand record gives the number of vehicles in an interval, not the moment each one arrived. Arrivals within an interval are treated as random: the `N` vehicles of a record receive `N` independent, uniformly random times within the interval.

This is a Poisson arrival process conditioned on exactly `N` arrivals. Random arrivals are the standard assumption when no information on platoons exists, and they are the arrival type used by the KPI engine's HCM delay calculation (arrival type 3, random arrivals; HCM 7th edition, Exhibit 19-13; KPI Engine, section 10.1).

Evenly spaced arrivals, or one vehicle per equal slot of the interval, were not used. Both are smoother than random arrivals, which reduces chance bunching and therefore queues and delays, making the KPIs optimistic without support from the data.

SUMO does not insert a vehicle without a safe gap. When two random times fall very close together on one lane, SUMO delays the second insertion until there is room, so minimum headways are enforced by the simulator.

Departure times are kept in whole hundredths of a second.

---

## Free-Flow Departure Shift

A detector counts a vehicle about 1 m before the stop line, but SUMO creates the vehicle at the edge of the network, several hundred metres upstream. Each departure is therefore moved earlier by the movement's free-flow travel time from the start of its route to the stop line, so that the vehicle reaches the stop line in the interval in which it was counted.

The free-flow time is the sum, over the route edges up to and including the stop-line edge, of edge length divided by the edge's highest lane speed limit. The stop-line edge is the edge of the last SUMO segment of the canonical lanes that serve the movement. Internal junction lanes are not included; they add a few metres.

For the study area:

| Movement | Free-flow time |
|---|---:|
| `MOV_W_E`, `MOV_W_N` | 28.72 s |
| `MOV_W_S_SLIP` | 30.30 s |
| `MOV_E_W`, `MOV_E_S` | 33.24 s |
| `MOV_N_E` | 45.03 s |
| `MOV_N_W_SLIP` | 47.28 s |
| `MOV_S_W` | 50.32 s |
| `MOV_S_E_BYPASS` | 57.31 s |

For example, a `MOV_S_E_BYPASS` vehicle of 08:00–08:15 (SUMO seconds 900–1800) that is due at the stop line at 910.32 s departs at 910.32 − 57.31 = 853.01 s.

Only free-flow time is used. Any additional time a vehicle spends slowing down and queueing is the delay that the KPIs measure, and compensating for it in advance would hide part of that delay.

In the first warm-up interval, the shifted window would start before second 0. Departures of that interval are drawn between second 0 and the shifted end of the interval instead. The warm-up is not measured, so this does not affect any KPI.

---

## Reproducibility

Each demand record has its own random-number generator, seeded with a SHA-256 hash of the run seed, the movement and the interval start, for example `42|MOV_S_E_BYPASS|2026-10-20T08:00:00+03:00`. SHA-256 is used instead of Python's `hash()`, which changes between Python processes.

As a result:

- the same demand records and seed always produce the same departures, on any computer;
- changing one record does not change the departures of any other record.

The second property matters for sensitivity runs that change the shared-lane split: only the affected movements change, and every other movement keeps identical vehicles, so differences in the results come from the changed split rather than from random variation.

The seed is owned by `SimulationRun.random_seed` and is passed to the planner.

---

## Vehicle IDs

A vehicle ID is the movement, the interval end and the vehicle's number within its record:

```text
MOV_S_E_BYPASS__20261020T0815__001
```

is the first vehicle of `MOV_S_E_BYPASS` in 08:00–08:15. The interval is labelled by its end, as in the source records and the `SimulationDemand` IDs. Vehicles are numbered in order of their departure within the record.

---

## Planned Departures

The planner returns a `DemandPlan`, the list of planned departures sorted by departure time. A planned departure stores only the facts the planner creates:

| Field | Meaning |
|---|---|
| `vehicle_id` | The vehicle's ID |
| `demand_id` | The demand record the vehicle belongs to |
| `depart_s` | The departure time in SUMO seconds |

Every other value is found from its owner, following the data-model rule of one source of truth per fact:

| Value | Found through |
|---|---|
| Movement and interval | `demand_id` → `SimulationDemand` |
| Stop-line time | `depart_s` + the movement's free-flow time |
| Route | `movement_id` → `MovementMapping` |
| Run window | `Scenario` and `SimulationConfig` |
| Seed | `SimulationRun` |

---

## Vehicle Type and Insertion

All vehicles use one passenger-car type with SUMO's default values for passenger cars, written out in the route file so that a change of SUMO default cannot change the baseline unnoticed:

| Attribute | Value | Meaning |
|---|---|---|
| `vClass` | `passenger` | Passenger car |
| `accel` | 2.6 m/s² | Acceleration |
| `decel` | 4.5 m/s² | Normal braking |
| `sigma` | 0.5 | Driver imperfection |
| `length` | 5.0 m | Vehicle length |
| `minGap` | 2.5 m | Gap to the leader when stopped |
| `speedDev` | 0.1 | Spread of preferred speeds around the speed limit |

Sources: SUMO documentation, *Vehicle Type Parameter Defaults* and *Definition of Vehicles, Vehicle Types, and Routes*. No calibration data exists to justify other values.

Every vehicle is inserted with:

| Attribute | Value | Reason |
|---|---|---|
| `departLane` | `best` | The vehicle starts in a lane that leads to its turn, avoiding forced lane changes at the network edge |
| `departSpeed` | `max` | The vehicle starts at the lane's speed limit, as the free-flow departure shift assumes, instead of accelerating from 0 |

Lane changes stay instantaneous, the SUMO default: no lane-change duration and no lane-change tuning such as `lcSpeedGain` are set. With a lane-change duration, a vehicle that must stop during the manoeuvre stops between two lanes and blocks both, which changes the queues the KPIs measure. Smooth display of lane changes belongs to the visualization.

---

## Output Files

The writer saves three files into one output folder. Each file name starts with the folder's name, so a file still shows which set it belongs to when copied elsewhere.

For the default folder `simulation/outputs/baseline/`:

| File | Content | Read by |
|---|---|---|
| `baseline_routes.rou.xml` | The vehicle type, one route per movement with vehicles, and every vehicle in departure order | SUMO |
| `baseline_manifest.json` | The `DemandPlan`: every vehicle's `vehicle_id`, `demand_id` and `depart_s` | Jaadah components, with `DemandPlan.model_validate_json` |
| `baseline_demand.json` | The `SimulationDemand` records the plan was made from, sorted by interval and movement | Jaadah components, to look up `demand_id` |

The demand records are stored once, here, so that a vehicle's movement, interval and demand origin (`is_allocated`, `is_imputed`) can be looked up through its `demand_id`. They are saved without their computed fields, which are recalculated when the records are read.

A set of demand with different records, such as a sensitivity run, is written to its own folder, for example `simulation/outputs/baseline_left_minus_20/`, giving `baseline_left_minus_20_routes.rou.xml` and so on.

The output files are not committed. The same demand records and seed always reproduce identical files, and `simulation/outputs/baseline/` is listed in `.gitignore`.

Part of the route file for the study area:

```xml
<routes>
    <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5.0" minGap="2.5" speedDev="0.1" />
    <route id="MOV_E_S" edges="713369663#1 713369663#1.469 713369663#2-AddedOnRampEdge 713369663#2 569790080 ..." />
    <vehicle id="MOV_E_S__20261020T0800__001" type="car" route="MOV_E_S" depart="16.20" departLane="best" departSpeed="max" />
</routes>
```

---

## Writing Safeguards

### Checks before writing

Nothing is written until every input has been checked. The writer raises a `DemandWritingError` listing every problem found when:

- two demand records have the same `demand_id`;
- a demand record's movement is not in the mapping;
- a planned vehicle's `demand_id` is not among the demand records;
- the planned vehicles are not in departure order, which SUMO requires.

For example:

```text
Cannot write SUMO demand:
MOV_X__20261020T0815__001: demand_id DEM_UNKNOWN is not among the demand records
DEM_X_0815 (MOV_X): movement is not in the mapping
```

### Identical bytes on every computer

The files are written as bytes with `\n` line endings. Writing them as text on Windows would add `\r` to every line, so the same vehicles would give different SHA-256 fingerprints on different computers.

### No partial output

Each file is first written under a temporary name ending in `.tmp`. The three files are renamed to their final names only once all three have been written. If writing fails, for example because a file is open in another program, the temporary files are removed, a `DemandWritingError` reports which file could not be written, and the previous files remain unchanged.

---

## Result Returned to the Caller

`write_sumo_demand` returns a `GeneratedDemand`:

| Field | Meaning |
|---|---|
| `route_file`, `manifest_file`, `demand_file` | Paths of the three files |
| `route_file_sha256`, `manifest_sha256`, `demand_sha256` | SHA-256 fingerprint of each file |

The result is not stored by itself. The simulation run passes `route_file` to SUMO and records the fingerprints on its `SimulationRun`, together with the mapping version and network checksum it already holds from the mapping configuration. A fingerprint changes when even one byte of its file changes, so it shows whether a run used exactly these files.

---

## Validation and Test Run

### File checks

`check_generated_demand(output_dir, mapping, network_path)` reads the three files of a generated folder and confirms that every record has exactly its `vehicle_count` vehicles, that the manifest and route file list the same vehicles, order and departure times, that every vehicle uses its movement's route with the agreed vehicle type and insertion settings, and that every route equals the mapping. It first runs the mapping validator (`validate_network_mappings`) against the network, so every route SUMO receives is legal in the network. All problems are reported together in a `DemandCheckError`.

### SUMO test run

```bash
python simulation/scripts/tests/run_sumo_demand_check.py
```

The script generates hand-made demand (20 vehicles per demand movement and interval for an 08:00–09:00 analysis), checks the files and runs SUMO until the end of the clearance. With `--demand`, it uses exported `SimulationDemand` records instead. The run passes when:

| Rule | Measured from |
|---|---|
| SUMO reports no errors | SUMO log |
| Every vehicle enters | Statistics output |
| Every vehicle due before the end of the analysis period has left the network | Trip output |
| No teleports and no collisions | Statistics output |
| At least 95 % of slip-road vehicles cross the stop line in their own interval | Route output with edge exit times |

Insertion delay is reported but not judged. Slip roads are used for the timing rule because they have no signal, so a vehicle's crossing time depends only on its departure and speed; preferred speeds vary by about ±10 %, which is why the rule requires 95 % rather than all vehicles. Results are saved in `simulation/outputs/tests/sumo_demand_check/`, which is not committed. The script exits with 0 when all rules pass, 1 when a rule fails, and 2 when the check cannot run.

For example, with seed 42 the study-area run inserts all 1,080 vehicles, 296 of the 300 slip-road vehicles cross in their interval (98.7 %), and the mean insertion delay is 0.1 s.

---

## Usage

```python
from jaadah.mapping.loader import load_network_mappings
from jaadah.sumo_demand.planner import (
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.checks import check_generated_demand
from jaadah.sumo_demand.writer import write_sumo_demand

network = "data/processed/road_network/jaadah_study_area.net.xml"
mapping = load_network_mappings(
    "data/processed/road_network/network_mappings.json",
    network_path=network,
)

window = build_run_window(scenario, simulation_config)
plan = plan_departures(
    demands,
    window=window,
    routes=movement_routes(mapping),
    expected_movements=demand_movement_ids(mapping),
    free_flow_s=compute_free_flow_times(mapping, network),
    seed=run.random_seed,
)
result = write_sumo_demand(
    plan,
    demands,
    mapping,
    output_dir="simulation/outputs/baseline",
)
check_generated_demand("simulation/outputs/baseline", mapping, network)
```

`demands` are the `SimulationDemand` records for the whole run window, warm-up and clearance included.

---

## Testing

| Test file | Tests | Covers |
|---|---:|---|
| `test_sumo_demand_planner.py` | 38 | Run window, exact counts, timing and shift, reproducibility, vehicle IDs, stored fields, invalid records, stop-line edges and free-flow times on a small network and on the study-area network |
| `test_sumo_demand_writer.py` | 19 | Route file content, manifest and demand file round trips, fingerprints, file names, line endings, temporary files, invalid input and write failures |
| `test_sumo_demand_checks.py` | 13 | A correct folder, and each check failing on a deliberately broken file: missing files, counts, departures, routes, demand IDs, vehicle type, insertion settings, order and network validity |

The study-area tests read `data/processed/road_network/network_mappings.json` and `jaadah_study_area.net.xml`, and are skipped when those files are not present.

Run the tests from the repository root:

```bash
python -m pytest jaadah/sumo_demand/sumo_demand_tests
```

The SUMO test run is separate from pytest because it needs SUMO (see Validation and Test Run).

---

## Difficulties and Conflicts

| Difficulty | Resolution |
|---|---|
| Through counts also contain ramp and U-turn vehicles, and East U-turn vehicles are counted by both the East and West detectors | Each movement uses its main route only; no split is invented and no vehicle is counted twice |
| Skipping an interval with no demand record is the same as simulating zero vehicles in a continuous run | Generation stops and lists every missing record |
| Detectors count at the stop line, but SUMO creates vehicles 558–831 m upstream | Departures are moved earlier by the free-flow time to the stop line |
| One vehicle per equal slot is smoother than real arrivals and makes delays too low | Random arrival times are used |
| Lane-change settings chosen to make the display smoother change queues and delays | Lane changes stay instantaneous; smooth display belongs to the visualization |
| Storing each vehicle's movement and interval would copy facts owned by `SimulationDemand` | A planned departure stores only `vehicle_id`, `demand_id` and `depart_s` |

---

## Limitations

- **Route variants:** vehicles that leave by the East on-ramp, the West off-ramp or the East U-turn are simulated on the main through route, because no detector separates them.
- **Routes without demand:** the three U-turns of the West, South and North approaches and the three tunnel routes are not simulated, because no detector observes them.
- **Served volume:** a stop-line detector counts vehicles as they are served. In oversaturated periods the counts are lower than the demand that arrived, so the simulated queues are shorter than the real ones.
- **Platoons:** arrivals are random; platoons released by upstream signals are not represented. The nearest other signals are 1.3–2.1 km away.
- **Driving behaviour:** the vehicle type uses SUMO defaults and is not calibrated; the KPI engine's comparison of measured and HCM saturation flow serves as a check.
- **Data with gaps:** a missing demand record stops generation. Demand with gaps, as expected from observed data, needs a documented gap rule before it can be simulated.

---

## Design Summary

- Exactly `vehicle_count` vehicles per demand record, on the movement's main route.
- Second 0 is the analysis start minus the warm-up; demand covers warm-up, analysis period and clearance.
- Random arrival times within each interval, reproducible from the run seed.
- Departures moved earlier by the free-flow time to the stop line.
- A missing, duplicate or misaligned record stops generation; it is never filled with zero.
- Planned departures store only `vehicle_id`, `demand_id` and `depart_s`.
- SUMO passenger defaults, `departLane="best"`, `departSpeed="max"`, instantaneous lane changes.
- Three regenerated output files with platform-independent fingerprints, written completely or not at all.

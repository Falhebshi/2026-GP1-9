# Jaadah Canonical Data Models

## Overview

Jaadah uses a canonical data model to standardize the information exchanged between traffic-data sources, the simulation pipeline, SUMO, visualization, analytics, the KPI engine and backend components.

The models are implemented in Python using **Pydantic**, which provides validation, serialization and a consistent structure across the system.

Two architectural rules shape every model:

> **1. SUMO adapts to Jaadah.** External traffic data and SUMO-specific representations are adapted to Jaadah's canonical model. Downstream components consume Jaadah structures rather than depending directly on source-specific or SUMO-specific formats.

> **2. One source of truth per fact.** A model never stores a second, independent copy of a fact that another model already owns, or a value it can calculate from its own fields. A record stores only its **most specific identifiers**; parents are looked up (for example, the scenario of a record is found through its `run_id`, and the approach and intersection of a movement through its `movement_id`).

The first rule lets external datasets and SUMO network identifiers change without forcing changes throughout the application. The second means two copies of the same fact can never disagree.

---

## Package Structure

The canonical models are implemented under:

```text
jaadah/
├── __init__.py
└── models/
    ├── __init__.py
    ├── traffic.py     traffic input and simulation demand
    ├── network.py     intersections, approaches, movements, lanes
    ├── scenario.py    scenarios, runs, configuration, replication
    ├── outputs.py     standardized simulation outputs
    ├── signals.py     signal programs and signal state
    └── kpis.py        KPI results and comparisons
```

Their tests are located under:

```text
tests/
├── test_traffic_observation.py
├── test_simulation_demand.py
├── test_network_models.py
├── test_movement_lane_models.py
├── test_scenario_models.py
├── test_replication_set.py
├── test_output_models.py
├── test_vehicle_delay_record.py
├── test_cycle_queue_record.py
├── test_incomplete_passage.py
├── test_signal_models.py
├── test_kpi_models.py
└── test_kpi_comparison.py
```

The current implementation contains **25 canonical models**:

| File | Models |
| --- | --- |
| `traffic.py` | `TrafficObservation`, `ImputedDetector`,`SimulationDemand` |
| `network.py` | `Intersection`, `Approach`, `Movement`, `MovementAttributes`, `ApproachLane` |
| `scenario.py` | `Scenario`, `SimulationRun`, `SimulationConfig`, `ReplicationPair`, `ReplicationSet` |
| `outputs.py` | `VehicleState`, `EdgeTrafficState`, `VehicleDelayRecord`, `IncompletePassage`, `CycleQueueRecord` |
| `signals.py` | `SignalPhase`, `SignalProgram`, `MovementSignalState`, `CurrentSignalState` |
| `kpis.py` | `KpiResult`, `KpiComparison` |

---

# 1. Traffic Input and Simulation Demand

Implemented in `jaadah/models/traffic.py`.

The traffic models deliberately separate **what a source reports** from **what Jaadah derives for simulation**. This prevents source measurements from being rewritten in a way that makes inferred information appear externally observed.

## 1.1 `TrafficObservation`

One standardized traffic observation received through Jaadah's ingestion boundary: what the external source actually supplied.

Fields: `observation_id`, `source`, `site_id`, `detector_id`, `interval_start`, `interval_end`, `vehicle_count`, optional `description`, optional `average_speed_kmh`, optional `travel_time_s`.

A `TrafficObservation` intentionally does **not** contain Jaadah movement or intersection IDs, or SUMO edge, lane or route IDs. Those relationships are established separately through mapping and demand-transformation logic. This preserves the distinction between **source truth** and **Jaadah interpretation**.

## 1.2 `SimulationDemand`

The movement-level traffic demand that Jaadah intends SUMO to simulate.

Fields: `demand_id`, `interval_start`, `interval_end`, `movement_id`, `vehicle_count`, `source`, `source_observation_ids`, `allocated_observation_ids`, `imputed_detectors`; computed: `is_allocated`, `is_imputed`.

The intersection is found through `movement_id` (`Movement`), not stored here. RCRC and synthetic demand must reference at least one source observation or imputed detector; forecast demand may reference none.

**Allocated demand.** A shared-lane detector counts two movements together, so its count is split between them by the demand transformation (see [Traffic demand transformation](traffic_demand_transformation.md)). `allocated_observation_ids` lists the observations whose count was split; it is empty when nothing was split, and every ID must also be in `source_observation_ids`. Detector IDs are not stored again; they are reached through each `TrafficObservation`. `is_allocated` is true when the list is not empty. Part of an allocated demand is a modelled assumption, not a measured count, so the KPI engine must add *modelled assumption* to `input_origins` for KPIs that use it, whatever the `source`. This is a requirement for the KPI engine, which does not read the field yet.

**Imputed demand.** When a detector did not report, the demand transformation may estimate its count (see [Traffic demand transformation](traffic_demand_transformation.md)). Such a detector has no observation to reference, so `imputed_detectors` lists it directly as an `ImputedDetector`: `site_id`, `detector_id` and `method` (`ImputationMethod`: `neighbour_regression` or `historical_average`). The same detector may appear only once. `is_imputed` is true when the list is not empty. A demand may consist of imputed detectors only, with no source observation. Like allocated demand, imputed demand is a modelled assumption, and the KPI engine must add *modelled assumption* to `input_origins` for KPIs that use it.

`is_allocated` and `is_imputed` are computed fields, like those of `KpiResult` (section 6.8): they appear in `model_dump()` and JSON output but cannot be passed in. For storage, dump without them:

```python
demand.model_dump(exclude={"is_allocated", "is_imputed"})
```

Unlike `TrafficObservation`, `SimulationDemand` is **derived simulation input**:

```text
External Traffic Source
        ↓
TrafficObservation          What did the source report?
        ↓
Traffic Demand Transformation
        ↓
SimulationDemand            What demand should SUMO simulate?
        ↓
SUMO Input Generation
        ↓
SUMO
```

The demand `v` in the KPI engine's v/c ratio comes from `SimulationDemand`, not from vehicles entered in the simulation.

## 1.3 Traffic Source Enums

Controlled enums are used instead of arbitrary strings.

### `TrafficObservationSource`

```text
synthetic
rcrc
```

### `SimulationDemandSource`

```text
synthetic
rcrc
forecast
```

Using enums prevents inconsistent free-text values from propagating through the application.

For example, values such as:

```text
RCRC
rcrc-data
real
synthetic_data
```

cannot silently become alternative representations of the same concept.

---

# 2. Canonical Network Model

Implemented in `jaadah/models/network.py`.

The network model gives Jaadah its own stable application-level identities. It does not use SUMO-generated edge or lane IDs as the primary identities of the system.

## 2.1 `Intersection`

A Jaadah study intersection.

Fields: `intersection_id`, optional `name_en`, `name_ar`, `center_longitude`, `center_latitude`, `area_label`.

The geographic center is optional, but longitude and latitude must be provided together.

For example:

```text
center_longitude = null
center_latitude  = null
```

is valid.

This is also valid:

```text
center_longitude = 46.65
center_latitude  = 24.72
```

Providing only one coordinate is rejected.

## 2.2 `Approach`

A stable identity for an incoming intersection approach.

Fields: `approach_id`, `intersection_id`. SUMO edges and lanes are stored in the mapping layer, not here.

## 2.3 `Movement`

A traffic movement that Jaadah models independently, for example `MOV_E_W`.

Fields: `movement_id`, `intersection_id`, optional `approach_id`.

`Movement` is the one network model that keeps both a parent and a grandparent ID: `approach_id` is optional (not every movement belongs to a conventional approach), and when it is absent `intersection_id` is the movement's only link to the network.

A movement can map to a sequence of SUMO edges and lanes, but those SUMO identifiers do not define it, so the SUMO network can change without changing what `MOV_E_W` means.

## 2.4 `MovementAttributes`

Jaadah-level facts about one movement that the KPI engine needs, kept separate so that `Movement` remains a pure identity.

Fields: `movement_id`, `movement_type`, `control`.

| Enum | Values |
| --- | --- |
| `MovementType` | `through`, `left`, `right` |
| `MovementControl` | `signalized`, `uncontrolled` (right turns on unsignalised slip roads) |

**Scope:** only movements included in the KPI analysis of the case-study intersection receive `MovementAttributes`. Other simulated movements (ramps, tunnel paths, slips and U-turns elsewhere in the network) remain plain `Movement`s and have no KPIs.

A movement with `MovementAttributes` must have `Movement.approach_id` set, because its results roll up to an approach. That rule spans two models, so it is checked where both are combined, not inside either: `NetworkMappingConfig` checks it.

**Source:** the approved values are stored in `NetworkMappingConfig.movement_attributes` in `network_mappings.json`, the single source for the KPI engine. `control` must agree with the movement mapping's `signal_controlled` flag, and no lane may serve both a signalized and an uncontrolled movement. See [movement attributes](network_mapping.md#movement-attributes).

## 2.5 `ApproachLane`

One lane of an approach and the movements it serves.

Fields: `lane_id`, `approach_id`, `lane_index`, `served_movement_ids`, `lane_width_m`, optional `storage_length_m`.

- `lane_id` (e.g. `LANE_E_2`) is the lane's stable identity. It keeps its meaning if the layout changes; the mapping layer links it to SUMO lane IDs.
- `lane_index` counts from the median: 1 is the lane closest to the median. SUMO counts from the kerb, starting at 0; the mapping layer converts between them.
- A lane shared by several movements lists all of them in `served_movement_ids`, e.g. `["MOV_E_L", "MOV_E_T"]`.
- `storage_length_m` is optional: when it is unknown, the queue storage ratio is reported as unavailable.

**Lane groups are not a stored model.** HCM analyses lane groups (adjacent lanes serving the same movements; a shared lane forms its own group). The KPI engine derives them from `ApproachLane` records each time and gives each a stable ID: the approach ID plus the movement letters in L/T/R order, e.g. `APP_E_L`, `APP_E_LT`, `APP_E_T` (team decision, 17 Oct 2026).

Signal-entry lane subset (12 lanes), from the median outward. The complete
canonical inventory contains 16 lanes, including four slip/bypass lanes; see
the [canonical lane inventory](network_mapping.md#canonical-lane-inventory).

| Approach | Lanes |
| --- | --- |
| East (Imam Saud Rd) | 1 left · 2 left + through (shared) · 3 through · 4 through |
| West (Imam Saud Rd) | 1 left · 2 left + through (shared) · 3 through |
| North | 3 lanes, all left |
| South | 2 lanes, both left (`MOV_S_W`) |

`MOV_S_W` is classified as a protected left turn (`left`, `signalized`): it
leaves the south approach to the driver's left on its own protected phase.
SUMO labels the connection `dir="s"`; that label describes the network
geometry, not the HCM classification, and the movement's identity, routing,
and signal behaviour are unchanged.

## 2.6 Canonical Identity vs. SUMO Identity

The canonical model represents Jaadah concepts; SUMO-specific identifiers belong to the mapping layer:

```text
Jaadah Movement MOV_E_W   →   Movement Mapping   →   SUMO route edges
Jaadah lane LANE_E_2      →   Lane Mapping       →   SUMO lane 713369663#2_2
```

rather than `Jaadah Movement = SUMO edge ID`. The same principle applies to approaches, lanes, detectors, routes and traffic-light controlled links.

---

# 3. Scenario and Simulation Execution

Implemented in `jaadah/models/scenario.py`.

These models distinguish the **traffic/control scenario being represented** from an **individual execution of that scenario**.

## 3.1 `Scenario`

The traffic and control context being represented: what should be simulated, not a specific execution of it.

Fields: `scenario_id`, `intersection_id`, `time_context`, `control_mode`, `start_time`, optional `end_time`, optional `reference_scenario_id`.

| Enum | Values |
| --- | --- |
| `TimeContext` | `historical`, `current`, `forecast` |
| `ControlMode` | `baseline`, `intervention` |

## 3.2 `SimulationRun`

One concrete execution of a scenario.

Fields: `run_id`, `scenario_id`, `random_seed`, `network_version`, `sumo_version`, `step_length_s`, `mapping_version`, `demand_sha256`, `route_file_sha256`, optional `started_at`, `status` (`pending`, `running`, `completed`, `failed`).

Lifecycle rules: `pending` and `failed` runs may have no `started_at`; `running` and `completed` runs require it; a failed run may also have one if execution began before the failure.

**Recorded inputs.** A run records the inputs it used, so that compared runs can be shown to differ only in the intervention: `mapping_version` (the `mapping_version` of `network_mappings.json`), `demand_sha256` (the fingerprint of the `SimulationDemand` file written by the SUMO demand writer) and `route_file_sha256` (the fingerprint of the SUMO route file, which holds every planned departure). The fingerprints are 64 hexadecimal characters. Like `started_at`, the three may be missing while a run is `pending` or `failed` and are required once it is `running` or `completed`. Departures are planned from the run's seed and its demand, so two runs with the same seed and demand have the same route file.

A scenario may have several runs, each with its own seed:

```text
Historical baseline scenario
        ↓
SimulationRun A → seed 42
SimulationRun B → seed 73
SimulationRun C → seed 105
```

`SimulationRun` is the **only owner of the random seed**. Every other model that needs it references the run.

## 3.3 `SimulationConfig`

Configurable simulation settings.

Fields: optional `simulation_duration_s`, `warmup_duration_s`, `clearance_duration_s`.

A run is divided into three parts:

```text
| warm-up | analysis period | clearance |
```

Vehicles are counted only if they enter the measurement zone during the analysis period. The clearance period lets those vehicles finish their passage; traffic keeps arriving during it, but new arrivals are not counted. Both durations are **required** (zero is allowed, but must be written on purpose), and when the total duration is set, warm-up + clearance must leave a non-empty analysis period.

## 3.4 `ReplicationPair` and `ReplicationSet`

A replicated experiment comparing an intervention scenario with its baseline using **matched random seeds** (common random numbers): each pair is a baseline run and an intervention run that used the same seed, so differences between them come from the intervention rather than from random variation.

- `ReplicationPair`: `baseline_run_id`, `intervention_run_id` (must differ). It does **not** store the seed; `SimulationRun` owns it.
- `ReplicationSet`: `replication_set_id`, `baseline_scenario_id`, `intervention_scenario_id` (must differ), `pairs` (at least 2, because a standard deviation needs two values; no run may appear twice). Properties `replication_count`, `baseline_run_ids`, `intervention_run_ids` (in pair order).

Before comparing, the KPI engine (`kpi_engine.md` section 12.6) checks with the `SimulationRun` and `Scenario` objects that both runs of each pair used the same seed, that each pair used a different seed, that each run is completed and belongs to the stated scenario, that the intervention references the baseline, that the two scenarios cover the same time window (`start_time`, `end_time`, `time_context`), that both runs of each pair used the same route file, and that all runs share the network version, SUMO version, step length, mapping version and demand. Baseline and intervention therefore use the same demand file, generated once. The replication runner may repeat these checks when it starts the runs. Replicating a single scenario without a comparison needs no `ReplicationSet`: a `KpiResult` with several `run_ids` already holds the mean and standard deviation.

## 3.5 Scenario Validation

The scenario models enforce structural relationships such as:

- historical and forecast scenarios require an `end_time`;
- intervention scenarios require a `reference_scenario_id`; baseline scenarios cannot reference another scenario; a scenario cannot reference itself;
- scenario data-time timestamps must use Riyadh time;
- `running` and `completed` runs require `started_at`, which must include timezone information, and their recorded inputs (`mapping_version`, `demand_sha256`, `route_file_sha256`);
- warm-up + clearance must be shorter than a known total duration.

These are structural integrity rules rather than traffic-simulation business logic.

---

# 4. Standardized Simulation Outputs

Implemented in `jaadah/models/outputs.py`.

SUMO exposes simulation results in SUMO-specific representations. Jaadah standardizes them before they reach downstream components. KPI runs execute **without TraCI** and write output files; the simulation pipeline reduces those files to the records below.

All output records identify their run by `run_id`; the scenario is found through `SimulationRun`. They are simulation measurements, not final application KPIs.

## 4.1 `VehicleState`

One simulated vehicle at a specific simulation time, for visualization.

Fields: `vehicle_id`, `run_id`, `simulation_time_s`, `timestamp`, `longitude`, `latitude`, `speed_mps`, `heading_deg`, `vehicle_type`, `sumo_edge_id`, and optional `z_m` (elevation), `sumo_lane_id`, `lane_pos_m` (lane position), `vtype_id` (SUMO vehicle type), `length_m`, `width_m`, `signals` (SUMO signal bitset) and `movement_id` (mapped Jaadah movement).

Positions use WGS84 longitude and latitude. Heading: 0° = North, 90° = East, 180° = South, 270° = West, increasing clockwise.

## 4.2 `EdgeTrafficState`

Aggregated traffic conditions for one SUMO edge over an interval.

Fields: `run_id`, `sumo_edge_id`, `interval_start`, `interval_end`, `vehicles_entered`, `vehicles_left`, optional `average_speed_mps`, optional `travel_time_s`, `density_veh_per_km`, optional `time_loss_s`, `sampled_seconds`.

The KPI engine does not use it: it serves network-level views such as speeds and densities on the network overview map.

## 4.3 `VehicleDelayRecord`

One vehicle's complete passage through the **measurement zone** of its approach: a fixed distance before the stop line, the path through the junction, and a fixed distance after the junction exit (East 388 m and 155 m, West 450 m and 105 m, North and South 500 m and 65 m). Records are produced from SUMO vehicle position output (FCD, recorded every 0.4 s); the zones and the rules for producing records are in [KPI measurements](kpi_measurements.md).

Fields: `run_id`, `vehicle_id`, `movement_id`, `zone_entry_time`, `stop_line_time`, `zone_exit_time`, `zone_distance_m`, `free_flow_travel_time_s`, `halted_time_s`.

- `zone_entry_time` is when the vehicle arrived: its delay counts in the 15-minute interval it arrived in.
- `stop_line_time` is when it got through the signal: it counts as served (throughput) in the interval it crossed the stop line.
- `free_flow_travel_time_s` is how long it would have needed through the same zone with no traffic and no signal, at its own desired speed on each piece of its path (each lane's speed limit × the vehicle's speed factor).
- `halted_time_s` is how long it stood still in the zone. The queue-duration KPI is measured per vehicle from it, so it splits cleanly by movement.

Checks: entry ≤ stop line ≤ exit; entry before exit; free-flow time and halted time each no longer than the time in the zone.

Properties (calculated, not stored): `zone_travel_time_s` = exit − entry, and `time_loss_s` = zone travel time − free-flow travel time.

## 4.4 `IncompletePassage`

A vehicle that entered the measurement zone but had not left it when the run ended. Recorded so that unfinished vehicles are **never silently dropped**: they are usually the most delayed (still queued), so leaving them out would make delay look better than it was.

Fields: `run_id`, `vehicle_id`, `movement_id`, `zone_entry_time`, optional `stop_line_time`, `last_seen_time`.

Its delay is unknown, so it has no time loss. A vehicle that crossed the stop line before the run ended was served and still counts for throughput (property `crossed_stop_line`). How the KPI engine reports an interval with incomplete passages is decided in the engine.

## 4.5 `CycleQueueRecord`

Queue length for one lane over one signal cycle, aligned with the cycle start, measured from vehicle positions over the lane's section ([KPI measurements](kpi_measurements.md), section 5).

Fields: `run_id`, `lane_id`, `cycle_start`, `cycle_end`, `max_queue_length_m`, `max_queue_vehicles`, `reaches_section_end` (default false).

`reaches_section_end` is true when the queue reached the start of the lane's section during the cycle, so it may continue upstream where lanes merge; the queue length is then the section length, a minimum value. It requires a queue.

The lane's approach, position and served movements come from its `ApproachLane`. The queue in metres and in vehicles must both be zero or both be above zero. The cycle length is not fixed in the model; it belongs to `SignalProgram` and may change in an intervention.

## 4.6 Vehicle Type Enum

`VehicleType`: `car`. A stable application-level category, rather than arbitrary SUMO vehicle-type identifiers.

---

# 5. Traffic Signal Model

Implemented in `jaadah/models/signals.py`.

Jaadah represents traffic-signal logic with canonical movement-level structures rather than exposing raw positional SUMO TLS strings.

## 5.1 `SignalPhase`

One phase in a signal program.

Fields: `phase_id`, `sequence_order`, `served_movement_ids` (at least one, no duplicates), `green_time_s`, `yellow_time_s`, `all_red_time_s`.

## 5.2 `SignalProgram`

A complete signal program associated with a scenario.

Fields: `signal_program_id`, `scenario_id`, `control_type` (`fixed_time`), `cycle_length_s`, `phases`, `source` (`observed`, `baseline_model`, `intervention`).

The intersection is found through `scenario_id` (`Scenario`). SUMO TLS identifiers belong to the mapping layer.

Rules: at least one phase; unique phase IDs and sequence orders; the cycle length must equal the sum of all phase durations:

```text
cycle length = Σ(green + yellow + all-red)
```

Jaadah represents fixed-time programs as a sequence of non-overlapping phases; concurrent or overlapping phases are outside the current scope.

## 5.3 `MovementSignalState`

The current indication for one movement: `movement_id`, `indication` (`green`, `yellow`, `red`).

## 5.4 `CurrentSignalState`

The signal controller at a specific simulation time, for live views.

Fields: `run_id`, `signal_program_id`, `simulation_time_s`, `timestamp`, `active_phase_id`, `phase_elapsed_s`, optional `phase_remaining_s`, `movement_states` (at least one, no duplicate movements).

The scenario is found through `run_id` and the intersection through `signal_program_id`. That the program belongs to the run's scenario is checked where both objects are available. KPI runs do not produce this model, because they run without TraCI.

---

# 6. KPI Results

Implemented in `jaadah/models/kpis.py`.

`KpiResult` is one KPI value for one element, one interval, and one run or set of runs. `KpiComparison` (section 6.9) is the change in one KPI between a baseline and an intervention scenario. The KPI engine produces both; they are stored and sent to the dashboard.

## 6.1 Fields

| Group | Fields |
| --- | --- |
| What | `kpi`, `method` (`hcm` or `simulation`), `unit` |
| Where | `level` and exactly one matching ID: `lane_id`, `lane_group_id`, `movement_id`, `approach_id` or `intersection_id` |
| When | `interval_start`, `interval_end` (15-minute intervals) |
| Value | `value` (≥ 0) or, for level of service, `los_grade` (A–F); `status`; `reason` |
| Provenance | `input_origins` |
| Runs | `scenario_id`, `run_ids`, `standard_deviation` |
| Shared lanes | `measured_on_lane_id` or `measured_on_lane_group_id` |
| Slips | `uncontrolled_movements` (section 6.7) |

## 6.2 Enums

| Enum | Values |
| --- | --- |
| `KpiName` | `control_delay`, `level_of_service`, `volume_to_capacity_ratio`, `capacity`, `saturation_flow_rate`, `queue_length`, `queue_duration`, `queue_storage_ratio`, `throughput` |
| `KpiLevel` | `lane`, `lane_group`, `movement`, `approach`, `intersection` |
| `KpiMethod` | `hcm`, `simulation` |
| `KpiStatus` | `ok`, `unavailable`, `not_applicable` |
| `KpiUnit` | `s/veh`, `veh/h`, `veh/h/lane`, `ratio`, `m`, `veh`, `s`, `grade` |
| `ValueComputation` | `direct_summary`, `derived` |
| `InputOrigin` | `observed`, `modelled_assumption`, `simulated` |
| `LevelOfServiceGrade` | `A` … `F` |
| `UncontrolledMovements` | `included`, `excluded` |

## 6.3 Missing values are never zero

A result with status `ok` must have a value. A result with status `unavailable` (the KPI applies but data is missing) or `not_applicable` (the KPI does not apply, e.g. LOS for an uncontrolled right turn) must have **no** value and must give a `reason`. A real measured zero (e.g. a 0 m queue) is still allowed with status `ok`.

## 6.4 Three fixed tables

| Table | Says |
| --- | --- |
| `ALLOWED_KPI_UNITS` | which units each KPI may use (every KPI shows its unit) |
| `VALUE_COMPUTATIONS` | for each supported (KPI, method) pair, how the final value is computed; a pair not listed is not a supported result |
| `ALLOWED_KPI_LEVELS` | for each (KPI, method) pair, which levels it may be reported at |

`ALLOWED_KPI_LEVELS` in summary:

| KPI (method) | Levels |
| --- | --- |
| Control delay, LOS, throughput, queue duration (simulation) | movement, approach, intersection |
| Queue length, queue storage ratio (simulation) | lane, movement, approach, intersection |
| Saturation flow (simulation, calibration check) | lane |
| Control delay, LOS, v/c (HCM) | lane group, movement, approach, intersection |
| Capacity (HCM) | lane group, movement, approach |
| Saturation flow (HCM) | lane group, movement |

## 6.5 Provenance: two labels

The four provenance labels overlap (an HCM result can be derived from observed demand plus assumed geometry), so they are split in two:

- **`value_computation`** (computed field): how the final value was computed. `direct_summary` is a mean, maximum, percentile or count of SUMO measurements; `derived` means a formula was applied. It is looked up from the KPI and its method in `VALUE_COMPUTATIONS`, so it can never be set inconsistently. Throughput and measured saturation flow are `direct_summary`; level of service, storage ratio and all HCM results are `derived`. This is separate from `method`: simulation-based LOS is a simulation-method result that is `derived`.
- **`input_origins`** (stored): where the inputs came from, traced back to their source; one or more of `observed`, `modelled_assumption`, `simulated`. Any simulation-method result includes `simulated`.

## 6.6 Runs and replication

- Simulation results summarize at least one run. HCM results may have no runs (e.g. capacity from demand, geometry and signal timing).
- With more than one run, `value` is the mean and `standard_deviation` is required (not for LOS, a letter grade). One run means no standard deviation.
- `scenario_id` is always stored: a result belongs to a scenario, while `run_ids` only lists the executions it summarizes.

## 6.7 Shared lanes (Option C, 17 Oct 2026)

KPIs measured per lane (queue length, storage ratio) or per lane group (HCM capacity measures) cannot be split between the movements of a shared lane. They are reported on their lane or lane group. A movement that uses a shared lane also shows that value, and records where it was measured in `measured_on_lane_id` or `measured_on_lane_group_id` (movement level only, at most one, and only for KPIs reportable on that kind of element). The computed field `is_shared_value` drives the dashboard's "Shared lane" tag; the tooltip text ("Measured on lane 2, shared with East-left") is looked up from `ApproachLane`, not stored.

**Uncontrolled right-turn slips.** An approach or intersection value whose element has slips records whether it covers them in `uncontrolled_movements`: simulation results include them (`included`), HCM results exclude them (`excluded`), because a slip has no lane group. Each method accepts only its own value; the field is allowed only on approach and intersection results with status `ok`, and is empty when the element has no slip. The dashboard shows it as a tag.

## 6.8 Computed fields and storage

`value_computation`, `replication_count` and `is_shared_value` are Pydantic computed fields: they appear in `model_dump()` and JSON output but cannot be passed in. **For storage, dump without them**, otherwise reloading fails, because unknown fields are forbidden:

```python
# for the dashboard / API
result.model_dump()

# for storage
result.model_dump(exclude={"value_computation", "replication_count", "is_shared_value"})
comparison.model_dump(exclude={"percent_change", "is_partial_sample"})
```

## 6.9 `KpiComparison`

The change in one KPI for one element and one interval between a baseline and an intervention scenario. One record per KPI, element and interval.

| Group | Fields |
| --- | --- |
| What, where, when | `kpi`, `method`, `unit`, `level` and one matching ID, `interval_start`, `interval_end` (same checks and tables as `KpiResult`) |
| Scenarios | `baseline_scenario_id`, `intervention_scenario_id` (must differ), `replication_set_id` |
| Pairs | `used_pairs`: the `ReplicationPair`s the change is based on; `pair_count`: the number of pairs in the `ReplicationSet`; computed `is_partial_sample` |
| Change | `status`, `reason`, `mean_change`, `standard_deviation`, `baseline_mean`; computed `percent_change` |
| Level of service | `baseline_los_grade`, `intervention_los_grade` |
| Provenance and slips | `input_origins`, `uncontrolled_movements` |

- **Simulation comparisons** use matched pairs from a `ReplicationSet`: `mean_change` is the mean of the per-pair differences (intervention − baseline) and `standard_deviation` their spread (required with two or more pairs, not allowed with one). `replication_set_id` and at least one used pair are required. A negative change in delay or queue is an improvement.
- **HCM comparisons** have no runs: no `replication_set_id`, no pairs, and `mean_change` is the plain difference.
- **`mean_change` may be negative**, unlike `KpiResult.value`; the intervention mean (`baseline_mean + mean_change`) may not.
- **`baseline_mean`** is the baseline mean over the used pairs, which can differ from the baseline `KpiResult` when pairs were left out. `percent_change` = 100 × `mean_change` / `baseline_mean`; it is empty when the baseline mean is 0.
- **Level of service** has no numeric change: an `ok` LOS comparison holds both grades and no numbers.
- **`pair_count`** is required on simulation comparisons (at least 1, and not fewer than the used pairs) and not allowed on HCM comparisons. **`is_partial_sample`** (computed) is true when a comparison with a value used fewer pairs than `pair_count`: its baseline values can then differ from the baseline scenario's own results, which use all its runs. The dashboard shows it as a tag, e.g. "Based on 2 of 3 matched runs". `pair_count` repeats a fact of the `ReplicationSet` on purpose, so the tag needs no lookup; the KPI engine fills it from the set.
- Missing values follow section 6.3: without status `ok` there is no change, no grade, no pair, no origin, and a `reason` is required.
- **Both scenario IDs are stored** (the same exception as `KpiResult.scenario_id`): an HCM comparison has no `ReplicationSet` to look them up from. For simulation comparisons the KPI engine checks that they agree with the set.

---

# 7. Validation Strategy

Pydantic is a validation boundary throughout Jaadah. Its purpose is to prevent structurally invalid data from silently moving between components.

Validation stays focused on **structural correctness**. Traffic-domain logic such as detector allocation, demand estimation, KPI calculations or intervention selection belongs to the application services, not inside Pydantic validators.

## 7.1 Identifiers

Required identifiers must be present, be strings, and not be empty or whitespace only. Leading and trailing whitespace is removed.

## 7.2 Time

Timestamps must be timezone-aware and use Riyadh time (`Asia/Riyadh`, UTC+03:00). Intervals satisfy `end > start` and are half-open, `[start, end)`: `08:00 → 08:15` includes 08:00 but not 08:15, so consecutive intervals never overlap.

## 7.3 Numbers

Counts, durations, distances and speeds cannot be negative; coordinates must be within geographic bounds; NaN and infinity are rejected where physical values are expected. Booleans are rejected where integers are expected, even though Python treats `True == 1`.

## 7.4 Collections

ID lists are validated where required: no empty entries, no duplicates, and at least one entry where a list must not be empty (e.g. served movements, queue-detection lanes, phases, movement signal states).

## 7.5 Cross-field rules

Some rules compare fields of the same model, for example: coordinates given together; intervention scenarios need a reference; the cycle length equals the phase durations; a KPI result's ID matches its level; a delay record's times are in order.

## 7.6 Cross-model rules

Rules that need several objects at once cannot live inside one model, and are checked by the component that holds them all. Examples: a movement with `MovementAttributes` has an approach; lane indexes are unique per approach; both runs of a replication pair used the same seed; a signal state's program belongs to its run's scenario.

## 7.7 Calculated values are properties, not inputs

Values that can always be calculated from a model's own fields are properties or computed fields, so they cannot disagree with the fields they come from: `time_loss_s`, `zone_travel_time_s`, `crossed_stop_line`, `replication_count`,`value_computation`, `is_shared_value`, `percent_change`, `is_partial_sample`, `is_allocated`, `is_imputed`.
---

# 8. Why Pydantic Is Used

The Pydantic models act as Jaadah's **data gatekeeper**.

Without a validated shared model, different components could accidentally use different names, units, assumptions, or data shapes for the same concept.

For example, without standardization, speed might independently appear as:

```text
speed
avg_speed
speed_kmh
vehicle_speed
```

The canonical model instead establishes a shared representation.

Likewise, invalid data such as:

```text
vehicle_count = -20
```

or:

```text
interval_start = 10:00
interval_end   = 09:45
```

is rejected before it propagates through the rest of the simulation pipeline.

Pydantic also provides consistent serialization for communication between backend services and downstream consumers.

---

# 9. Architectural Boundaries

The canonical model defines shared meanings and structures. It intentionally does not contain all project logic.

## 9.1 Network mapping is separate

Canonical entities do not contain SUMO topology. A separate mapping layer links movements to SUMO routes, lanes to SUMO lanes, and detectors and traffic-light controlled links to their Jaadah identities. This keeps generated SUMO identifiers from becoming application-level identities.

The study area's network IDs, parent relationships, and source/SUMO mappings
live in `data/processed/road_network/network_mappings.json`. This is the single
configuration used to define the network. `NetworkMappingConfig` builds
canonical objects from those records through `canonical_intersection`,
`canonical_approaches`, and `canonical_movements`.

`approach_lanes` holds the canonical lane definitions, while `lane_mappings`
connects them to SUMO lane segments. A known lane may still be waiting for its
SUMO mapping. `movement_attributes` holds the movement type and control of the
analysed movements. The checks catch inconsistent references and ownership; creating
canonical objects from the same records does not independently confirm their
geographic correctness. See [Network mapping](network_mapping.md) for the full
rules, M7 usage, and test commands.

`DetectorMapping.lane_id` is an optional canonical association. Its separate
`sumo_lane_id` and `sumo_position_m` fields describe an exact modeled location:
both may be absent/null, or both must be supplied. Lane IDs are trimmed and
nonblank; positions must be finite, nonnegative numbers, excluding booleans,
in metres from the SUMO lane start along travel direction. Network validation
checks external lane existence, inclusive lane-length bounds, and membership
in the canonical lane chain when that mapping is available. Any chain segment
may be selected. Pending mappings cannot establish membership, and unresolved
detectors may still omit exact locations.

The populated 16-detector synthetic baseline uses 1 m before the selected lane endpoint.
Detectors 1-12 reference modeled signal entries; 13-16 reference uncontrolled
slip/bypass endpoints, not necessarily physical stop lines. These modeled
assumptions are not surveyed RCRC locations or defaults for other sources.
The configuration contains 16 synthetic detector mappings at site `"9"`.
Shared detectors 2 and 10 require allocation; the other 14 are usable. These
statuses do not define allocation algorithms or split proportions. Catalogue
provenance and mapping scope are documented in [Network mapping](network_mapping.md).

## 9.2 Demand transformation is separate

The models do not decide how observed detector counts become movement demand (e.g. splitting 100 detector vehicles 70/30 between two movements). That rule belongs to the Traffic Demand Transformation component, so traffic-domain assumptions are not hidden inside structural validation.

## 9.3 SUMO input generation is separate

`SimulationDemand` expresses movement + interval + vehicle count. The SUMO adapter converts it into SUMO's representation. **SUMO adapts to Jaadah.**

## 9.4 Output reduction is separate

The simulation pipeline turns SUMO output files into canonical records: vehicle position output (FCD) into `VehicleDelayRecord` and `IncompletePassage`; vehicle positions over each lane's section into `CycleQueueRecord`; the network's signal program into `SignalProgram`.

## 9.5 KPI calculation is separate

The output records are simulation measurements. The KPI engine (`backend/analytics/kpi/`, documented in `kpi_engine.md`) turns them into `KpiResult`s and `KpiComparison`s: it derives lane groups, applies the HCM method, aggregates to 15-minute intervals and rolls movements up to approaches and the intersection. Anomaly detection, forecasting and recommendations are also separate application components.

---

# 10. Testing

The canonical model implementation is covered by unit tests using `pytest`.

Run the complete suite from the repository root with:

```bash
python -m pytest -v
```

The tests cover valid model creation as well as invalid cases such as:

- empty or whitespace-only IDs;
- invalid enum values;
- negative vehicle counts;
- booleans supplied as vehicle counts;
- invalid coordinates;
- incomplete coordinate pairs;
- reversed time intervals;
- timestamps without timezone information;
- incorrect source/data-time timezone;
- duplicate provenance IDs;
- invalid scenario relationships;
- invalid `SimulationRun` lifecycle/start-time combinations;
- invalid queue-detection lane lists;
- duplicate queue lanes;
- empty signal phases;
- duplicate served movements;
- duplicate signal phase IDs;
- duplicate signal phase sequence numbers;
- inconsistent signal cycle lengths;
- SUMO-specific TLS identifiers supplied to the canonical `SignalProgram`;
- empty current signal states;
- duplicate movement signal states.

The test suite verifies the shared model before other components rely on it.

---

# 11. Data Flow

```text
        External Traffic Source
                 ↓
         TrafficObservation
                 ↓
     Traffic Demand Transformation
                 ↓
          SimulationDemand
                 ↓
       SUMO Input Generation
                 ↓
     SUMO (KPI runs without TraCI)
                 ↓
         Output Reduction
                 ↓
   ┌─────────────┼──────────────────────┐
   ↓             ↓                      ↓
VehicleState  VehicleDelayRecord     SignalProgram
EdgeTraffic-  IncompletePassage      (CurrentSignalState
State         CycleQueueRecord        for live views)
   ↓             ↓
Visualization  KPI engine (+ ApproachLane, MovementAttributes,
               SignalProgram, SimulationDemand)
                 ↓
     KpiResult, KpiComparison
                 ↓
        Storage, API, dashboard
```

Together, these structures form the common data language used across the Jaadah system.

---

# Change Log

| Date | Change |
| --- | --- |
| Oct 2026 (Sprint 1) | 16 initial models in five areas |
| 14–17 Oct 2026 | Added `KpiResult` and its enums and tables (`kpis.py`); `MovementAttributes` and `ApproachLane`; `VehicleDelayRecord`, `IncompletePassage` and `CycleQueueRecord`; `ReplicationPair` and `ReplicationSet`; `SimulationConfig.clearance_duration_s`. Shared-lane reporting (Option C) with lane and lane-group levels |
| 17 Oct 2026 (cleanup) | Removed `Segment` and `EdgeTrafficState.segment_id` (unused). Applied "most specific identifiers only" to the existing models: `VehicleState`, `EdgeTrafficState` and `ApproachTrafficState` no longer store `scenario_id`; `ApproachTrafficState`, `SimulationDemand` and `SignalProgram` no longer store `intersection_id`; `CurrentSignalState` no longer stores `scenario_id` or `intersection_id`. `EdgeTrafficState` and `ApproachTrafficState` documented as not used by the KPI engine |
| 18 Oct 2026 (network mapping) | Added `ApproachSide` and `LaneMapping` (`mappings.py`); `DetectorMapping.lane_id`; `NetworkMappingConfig.approach_lanes` and `lane_mappings`. Renamed `ApproachMapping.direction` to `approach_side` and removed `source_detectors`. Mapping schema set to `2.0`. `network_mappings.json` defines network identities and parent relationships; canonical `Intersection`, `Approach`, and `Movement` objects are built from these records. Added lane ownership and detector candidate checks. Canonical lane references allow pending SUMO mappings |
| 19 Oct 2026 (detector mapping) | Added optional, paired `DetectorMapping.sumo_lane_id` and `sumo_position_m` for exact modeled detector locations. Positions are finite, nonnegative metres from the selected SUMO lane start; booleans are rejected. Network validation checks external lane existence, inclusive position bounds, and membership in an available canonical lane chain. Missing locations and pending lane mappings remain supported. Documented the synthetic 1 m-before-endpoint convention; detector records remain unpopulated |
| 19 Oct 2026 (detector population) | Populated 16 synthetic detector mappings at site `"9"`, with approved canonical lanes, Option A local movement candidates, and explicit SUMO positions 1 m before selected lane endpoints. Detectors 2 and 10 require allocation; the other 14 are usable. Existing canonical lanes, lane chains, and movement routes are unchanged |
| 20 Oct 2026 (KPI comparison) | Added `KpiComparison` (baseline vs intervention over matched pairs, computed `percent_change`) and `UncontrolledMovements` with `KpiResult.uncontrolled_movements`. Lane-group ID examples updated to the engine's format (`APP_E_LT`); KPI engine location updated to `backend/analytics/kpi/` |
| 20 Oct 2026 (demand allocation) | Added `SimulationDemand.allocated_observation_ids` (a subset of `source_observation_ids`) and the computed `is_allocated`, marking demand that includes part of a split shared-lane detector count |
| 20 Oct 2026 (demand imputation) | Added `ImputationMethod`, `ImputedDetector`, `SimulationDemand.imputed_detectors` and the computed `is_imputed`, marking demand that includes an estimated count for a detector that did not report. RCRC and synthetic demand may consist of imputed detectors only |
| 22 Oct 2026 (KPI comparison review) | Added `KpiComparison.pair_count` and the computed `is_partial_sample`, marking comparisons based on fewer pairs than the replication set holds |
| 23 Oct 2026 (run inputs) | Added `SimulationRun.mapping_version`, `demand_sha256` and `route_file_sha256`, required for running and completed runs, so that compared runs can be checked for identical inputs |
| 23 Oct 2026 (movement attributes) | Added `NetworkMappingConfig.movement_attributes`, optional and empty by default, holding the approved `MovementAttributes` of the nine analysed movements. Checks: no duplicates, known movement with an approach, `control` agrees with `signal_controlled`, no lane mixing signalized and uncontrolled movements. `MOV_S_W` classified as a protected left. `mapping_version` set to `2.2-movement-attributes`; `schema_version` stays `2.0` |
| 25 Oct 2026 (measurement zones) | Added optional `ApproachMapping.zone_upstream_m` and `zone_downstream_m` (given together, finite and positive), holding each approach's measurement zone; the network validator checks that each zone fits on the routes of its movements. `mapping_version` set to `2.3-measurement-zones`; `schema_version` stays `2.0` |
| 26 Oct 2026 (approach traffic state) | Removed `ApproachTrafficState` (unused: queue length is measured per lane in `CycleQueueRecord` and time loss per vehicle in `VehicleDelayRecord`) |
| 26 Oct 2026 (cycle queues) | Added `CycleQueueRecord.reaches_section_end` (default false; requires a queue). Cycle queues are measured from vehicle positions over each lane's section instead of lane-area detectors |

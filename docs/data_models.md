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
    └── kpis.py        KPI results
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
└── test_kpi_models.py
```

The current implementation contains **23 canonical models**:

| File | Models |
| --- | --- |
| `traffic.py` | `TrafficObservation`, `SimulationDemand` |
| `network.py` | `Intersection`, `Approach`, `Movement`, `MovementAttributes`, `ApproachLane` |
| `scenario.py` | `Scenario`, `SimulationRun`, `SimulationConfig`, `ReplicationPair`, `ReplicationSet` |
| `outputs.py` | `VehicleState`, `EdgeTrafficState`, `ApproachTrafficState`, `VehicleDelayRecord`, `IncompletePassage`, `CycleQueueRecord` |
| `signals.py` | `SignalPhase`, `SignalProgram`, `MovementSignalState`, `CurrentSignalState` |
| `kpis.py` | `KpiResult` |

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

Fields: `demand_id`, `interval_start`, `interval_end`, `movement_id`, `vehicle_count`, `source`, `source_observation_ids`.

The intersection is found through `movement_id` (`Movement`), not stored here. RCRC and synthetic demand must reference at least one source observation; forecast demand may reference none.

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

A movement with `MovementAttributes` must have `Movement.approach_id` set, because its results roll up to an approach. That rule spans two models, so it is checked where both are combined, not inside either.

## 2.5 `ApproachLane`

One lane of an approach and the movements it serves.

Fields: `lane_id`, `approach_id`, `lane_index`, `served_movement_ids`, `lane_width_m`, optional `storage_length_m`.

- `lane_id` (e.g. `LANE_E_2`) is the lane's stable identity. It keeps its meaning if the layout changes; the mapping layer links it to SUMO lane IDs.
- `lane_index` counts from the median: 1 is the lane closest to the median. SUMO counts from the kerb, starting at 0; the mapping layer converts between them.
- A lane shared by several movements lists all of them in `served_movement_ids`, e.g. `["MOV_E_L", "MOV_E_T"]`.
- `storage_length_m` is optional: when it is unknown, the queue storage ratio is reported as unavailable.

**Lane groups are not a stored model.** HCM analyses lane groups (adjacent lanes serving the same movements; a shared lane forms its own group). The KPI engine derives them from `ApproachLane` records each time and gives each a stable ID such as `east_L`, `east_LT`, `east_T` (team decision, 17 Oct 2026).

Confirmed layout of the case-study intersection, from the median outward:

| Approach | Lanes |
| --- | --- |
| East (Imam Saud Rd) | 1 left · 2 left + through (shared) · 3 through · 4 through |
| West (Imam Saud Rd) | 1 left · 2 left + through (shared) · 3 through |
| North | 3 lanes, all left |
| South | 2 lanes, both through |

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

Fields: `run_id`, `scenario_id`, `random_seed`, `network_version`, `sumo_version`, `step_length_s`, optional `started_at`, `status` (`pending`, `running`, `completed`, `failed`).

Lifecycle rules: `pending` and `failed` runs may have no `started_at`; `running` and `completed` runs require it; a failed run may also have one if execution began before the failure.

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

Vehicles are counted only if they enter the delay zone during the analysis period. The clearance period lets those vehicles finish their passage; traffic keeps arriving during it, but new arrivals are not counted. Both durations are **required** (zero is allowed, but must be written on purpose), and when the total duration is set, warm-up + clearance must leave a non-empty analysis period.

## 3.4 `ReplicationPair` and `ReplicationSet`

A replicated experiment comparing an intervention scenario with its baseline using **matched random seeds** (common random numbers): each pair is a baseline run and an intervention run that used the same seed, so differences between them come from the intervention rather than from random variation.

- `ReplicationPair`: `baseline_run_id`, `intervention_run_id` (must differ). It does **not** store the seed; `SimulationRun` owns it.
- `ReplicationSet`: `replication_set_id`, `baseline_scenario_id`, `intervention_scenario_id` (must differ), `pairs` (at least 2, because a standard deviation needs two values; no run may appear twice). Properties `replication_count`, `baseline_run_ids`, `intervention_run_ids` (in pair order).

The replication runner, which has the `SimulationRun` and `Scenario` objects, confirms that both runs of each pair used the same seed, that each pair used a different seed, and that each run belongs to the stated scenario. Replicating a single scenario without a comparison needs no `ReplicationSet`: a `KpiResult` with several `run_ids` already holds the mean and standard deviation.

## 3.5 Scenario Validation

The scenario models enforce structural relationships such as:

- historical and forecast scenarios require an `end_time`;
- intervention scenarios require a `reference_scenario_id`; baseline scenarios cannot reference another scenario; a scenario cannot reference itself;
- scenario data-time timestamps must use Riyadh time;
- `running` and `completed` runs require `started_at`, which must include timezone information;
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

## 4.3 `ApproachTrafficState`

Aggregate queue and time-loss measurements for one approach.

Fields: `run_id`, `approach_id`, `queue_detection_lane_ids` (at least one, no duplicates), `interval_start`, `interval_end`, `max_queue_length_m`, `mean_max_queue_vehicles`, `started_halts`, `vehicles_seen`, optional `mean_time_loss_s`.

**Not used by the KPI engine:** queue length is measured per lane in `CycleQueueRecord`, and time loss and time stopped per vehicle in `VehicleDelayRecord`. It is kept until the team decides whether any component needs it (tracked in a GitHub issue).

## 4.4 `VehicleDelayRecord`

One vehicle's complete passage through the **delay zone** of one movement. The zone runs from 250 m before the stop line to the point after the intersection where the vehicle is back to speed. Records are produced from SUMO vehicle position output (FCD, recorded every 0.4 s).

Fields: `run_id`, `vehicle_id`, `movement_id`, `zone_entry_time`, `stop_line_time`, `zone_exit_time`, `zone_distance_m`, `free_flow_travel_time_s`, `halted_time_s`.

- `zone_entry_time` is when the vehicle arrived: its delay counts in the 15-minute interval it arrived in.
- `stop_line_time` is when it got through the signal: it counts as served (throughput) in the interval it crossed the stop line.
- `free_flow_travel_time_s` is how long it would have needed through the same zone with no traffic and no signal. How it is obtained (one free-flow speed, or one per lane along the path) is decided by the simulation pipeline.
- `halted_time_s` is how long it stood still in the zone. The queue-duration KPI is measured per vehicle from it, so it splits cleanly by movement.

Checks: entry ≤ stop line ≤ exit; entry before exit; free-flow time and halted time each no longer than the time in the zone.

Properties (calculated, not stored): `zone_travel_time_s` = exit − entry, and `time_loss_s` = zone travel time − free-flow travel time.

## 4.5 `IncompletePassage`

A vehicle that entered the delay zone but had not left it when the run ended. Recorded so that unfinished vehicles are **never silently dropped**: they are usually the most delayed (still queued), so leaving them out would make delay look better than it was.

Fields: `run_id`, `vehicle_id`, `movement_id`, `zone_entry_time`, optional `stop_line_time`, `last_seen_time`.

Its delay is unknown, so it has no time loss. A vehicle that crossed the stop line before the run ended was served and still counts for throughput (property `crossed_stop_line`). How the KPI engine reports an interval with incomplete passages is decided in the engine.

## 4.6 `CycleQueueRecord`

Queue length for one lane over one signal cycle, from a lane-area (E2) detector whose output period is one cycle, aligned with the cycle start.

Fields: `run_id`, `lane_id`, `cycle_start`, `cycle_end`, `max_queue_length_m`, `max_queue_vehicles`.

The lane's approach, position and served movements come from its `ApproachLane`. The queue in metres and in vehicles must both be zero or both be above zero. The cycle length is not fixed in the model; it belongs to `SignalProgram` and may change in an intervention.

## 4.7 Vehicle Type Enum

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

`KpiResult` is one KPI value for one element, one interval, and one run or set of runs. The KPI engine produces these; they are stored and sent to the dashboard.

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

## 6.8 Computed fields and storage

`value_computation`, `replication_count` and `is_shared_value` are Pydantic computed fields: they appear in `model_dump()` and JSON output but cannot be passed in. **For storage, dump without them**, otherwise reloading fails, because unknown fields are forbidden:

```python
# for the dashboard / API
result.model_dump()

# for storage
result.model_dump(exclude={"value_computation", "replication_count", "is_shared_value"})
```

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

Values that can always be calculated from a model's own fields are properties or computed fields, so they cannot disagree with the fields they come from: `time_loss_s`, `zone_travel_time_s`, `crossed_stop_line`, `replication_count`, `value_computation`, `is_shared_value`.

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
SUMO mapping. The checks catch inconsistent references and ownership; creating
canonical objects from the same records does not independently confirm their
geographic correctness. See [Network mapping](network_mapping.md) for the full
rules, M7 usage, and test commands.

## 9.2 Demand transformation is separate

The models do not decide how observed detector counts become movement demand (e.g. splitting 100 detector vehicles 70/30 between two movements). That rule belongs to the Traffic Demand Transformation component, so traffic-domain assumptions are not hidden inside structural validation.

## 9.3 SUMO input generation is separate

`SimulationDemand` expresses movement + interval + vehicle count. The SUMO adapter converts it into SUMO's representation. **SUMO adapts to Jaadah.**

## 9.4 Output reduction is separate

The simulation pipeline turns SUMO output files into canonical records: vehicle position output (FCD) into `VehicleDelayRecord` and `IncompletePassage`; lane-area detector output into `CycleQueueRecord`; the network's signal program into `SignalProgram`.

## 9.5 KPI calculation is separate

The output records are simulation measurements. The KPI engine (`backend/services/kpi/`) turns them into `KpiResult`s: it derives lane groups, applies the HCM method, aggregates to 15-minute intervals and rolls movements up to approaches and the intersection. Anomaly detection, forecasting and recommendations are also separate application components.

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
             KpiResult
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

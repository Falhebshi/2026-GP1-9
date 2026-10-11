# Jaadah Canonical Data Models

## Overview

Jaadah uses a canonical data model to standardize the information exchanged between traffic-data sources, the simulation pipeline, SUMO, visualization, analytics, and backend components.

The models are implemented in Python using **Pydantic**, which provides validation, serialization, and a consistent structure across the system.

The main architectural rule is:

> **External traffic data and SUMO-specific representations are adapted to Jaadah's canonical model. Downstream components consume Jaadah structures rather than depending directly on source-specific or SUMO-specific formats.**

This separation allows external datasets and SUMO network identifiers to evolve without forcing corresponding changes throughout the rest of the application.

---

## Package Structure

The canonical models are implemented under:

```text
jaadah/
├── __init__.py
└── models/
    ├── __init__.py
    ├── traffic.py
    ├── network.py
    ├── scenario.py
    ├── outputs.py
    └── signals.py
```

Their tests are located under:

```text
tests/
├── test_traffic_observation.py
├── test_simulation_demand.py
├── test_network_models.py
├── test_scenario_models.py
├── test_output_models.py
└── test_signal_models.py
```

The current implementation contains **16 canonical models** grouped into five areas:

1. traffic input and simulation demand;
2. canonical network entities;
3. scenario and simulation execution;
4. standardized simulation outputs;
5. traffic-signal state.

---

# 1. Traffic Input and Simulation Demand

Implemented in:

```text
jaadah/models/traffic.py
```

The traffic models deliberately separate **what a source reports** from **what Jaadah derives for simulation**.

This distinction prevents source measurements from being rewritten in a way that makes inferred information appear externally observed.

---

## 1.1 `TrafficObservation`

`TrafficObservation` represents one standardized traffic observation received through Jaadah's ingestion boundary.

It describes what the external source actually supplied.

Core fields include:

- `observation_id`
- `source`
- `site_id`
- `detector_id`
- `interval_start`
- `interval_end`
- `vehicle_count`
- optional `description`
- optional `average_speed_kmh`
- optional `travel_time_s`

A `TrafficObservation` intentionally does **not** contain:

- Jaadah movement IDs;
- Jaadah intersection IDs;
- SUMO edge IDs;
- SUMO lane IDs;
- SUMO route IDs.

Those relationships are established separately through mapping and demand-transformation logic.

This preserves the distinction between **source truth** and **Jaadah interpretation**.

---

## 1.2 `SimulationDemand`

`SimulationDemand` represents the movement-level traffic demand that Jaadah intends SUMO to simulate.

Core fields include:

- `demand_id`
- `interval_start`
- `interval_end`
- `intersection_id`
- `movement_id`
- `vehicle_count`
- `source`
- `source_observation_ids`

Unlike `TrafficObservation`, `SimulationDemand` is **derived simulation input**.

The relationship is:

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
SUMO
```

A `TrafficObservation` answers:

> What did the source report?

A `SimulationDemand` answers:

> What traffic demand should Jaadah ask SUMO to simulate?

These structures are therefore intentionally separate.

---

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

Implemented in:

```text
jaadah/models/network.py
```

The canonical network model gives Jaadah its own stable application-level identities.

It does not use SUMO-generated edge or lane IDs as the primary identities of the system.

The implemented structures are:

- `Intersection`
- `Approach`
- `Movement`
- `Segment`

---

## 2.1 `Intersection`

`Intersection` represents a Jaadah study intersection or controlled study location.

Core fields include:

- `intersection_id`
- optional `name_en`
- optional `name_ar`
- optional `center_longitude`
- optional `center_latitude`
- optional `area_label`

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

---

## 2.2 `Approach`

`Approach` represents a stable Jaadah identity for an incoming intersection approach.

Core fields:

- `approach_id`
- `intersection_id`

SUMO-specific edges and lanes are intentionally not stored in the canonical entity itself.

---

## 2.3 `Movement`

`Movement` represents a traffic movement that Jaadah needs to model independently.

Core fields:

- `movement_id`
- `intersection_id`
- optional `approach_id`

For example:

```text
MOV_E_W
```

may represent the canonical East-to-West movement.

That movement can later map to a sequence of SUMO edges and lanes, but those SUMO identifiers do not define the movement itself.

This means the SUMO network can change without changing the meaning of `MOV_E_W` throughout Jaadah.

---

## 2.4 `Segment`

`Segment` represents a stable road-segment identity used when Jaadah requires segment-level references.

Core field:

- `segment_id`

SUMO edge relationships are handled separately by the mapping layer.

---

## 2.5 Canonical Identity vs. SUMO Identity

The canonical model represents **Jaadah concepts**.

SUMO-specific identifiers belong to the mapping layer.

The intended relationship is:

```text
Jaadah Movement
MOV_E_W
      ↓
Movement Mapping
      ↓
SUMO route edges
```

rather than:

```text
Jaadah Movement = SUMO edge ID
```

The same principle applies to approaches, road segments, detectors, lanes, routes, and traffic-light controlled links.

---

# 3. Scenario and Simulation Execution

Implemented in:

```text
jaadah/models/scenario.py
```

These models distinguish the **traffic/control scenario being represented** from an **individual execution of that scenario**.

The implemented structures are:

- `Scenario`
- `SimulationRun`
- `SimulationConfig`

---

## 3.1 `Scenario`

`Scenario` describes the traffic and control context being represented.

Core fields include:

- `scenario_id`
- `intersection_id`
- `time_context`
- `control_mode`
- `start_time`
- optional `end_time`
- optional `reference_scenario_id`

Supported time contexts are:

```text
historical
current
forecast
```

Supported control modes are:

```text
baseline
intervention
```

A scenario describes **what should be simulated**, not a specific execution of it.

---

## 3.2 `SimulationRun`

`SimulationRun` represents one concrete execution of a scenario.

It records execution provenance including:

- `run_id`
- `scenario_id`
- `random_seed`
- `network_version`
- `sumo_version`
- `step_length_s`
- `started_at`
- `status`

A single scenario may have multiple simulation runs.

For example:

```text
Historical baseline scenario
        ↓
SimulationRun A → seed 42
SimulationRun B → seed 73
SimulationRun C → seed 105
```

The traffic/control context remains the same, while each stochastic execution remains distinguishable.

This is why the random seed belongs to `SimulationRun`.

---

## 3.3 `SimulationConfig`

`SimulationConfig` represents configurable simulation settings.

Current fields include:

- `simulation_duration_s`
- `warmup_duration_s`

The warm-up duration is configurable rather than treated as a permanently fixed constant.

Its operational behavior is handled by the simulation pipeline rather than by the data model itself.

---

## 3.4 Scenario Validation

The scenario models enforce structural relationships such as:

- historical scenarios require an `end_time`;
- forecast scenarios require an `end_time`;
- intervention scenarios require a `reference_scenario_id`;
- baseline scenarios cannot reference another scenario;
- a scenario cannot reference itself;
- scenario data-time timestamps must use Riyadh time;
- execution timestamps such as `started_at` must include explicit timezone information.

These are structural integrity rules rather than traffic-simulation business logic.

---

# 4. Standardized Simulation Outputs

Implemented in:

```text
jaadah/models/outputs.py
```

SUMO and TraCI expose simulation state using SUMO-specific representations.

Jaadah standardizes that state before it reaches downstream components.

The implemented structures are:

- `VehicleState`
- `EdgeTrafficState`
- `ApproachTrafficState`

---

## 4.1 `VehicleState`

`VehicleState` represents one simulated vehicle at a specific simulation time.

Core information includes:

- `vehicle_id`
- `scenario_id`
- `run_id`
- `simulation_time_s`
- `timestamp`
- `longitude`
- `latitude`
- `speed_mps`
- `heading_deg`
- `vehicle_type`
- `sumo_edge_id`

Optional simulation and visualization metadata may include:

- elevation;
- SUMO lane ID;
- lane position;
- SUMO vehicle-type ID;
- vehicle length;
- vehicle width;
- SUMO signal bitset;
- mapped Jaadah movement ID.

The standardized geographic representation uses WGS84 longitude and latitude.

The heading convention is:

```text
0°   = North
90°  = East
180° = South
270° = West
```

with heading increasing clockwise.

This provides visualization with a stable structure without requiring it to depend directly on raw TraCI calls.

---

## 4.2 `EdgeTrafficState`

`EdgeTrafficState` represents aggregated traffic conditions for a SUMO edge over an interval.

It includes information such as:

- scenario ID;
- run ID;
- optional Jaadah segment ID;
- SUMO edge ID;
- interval start and end;
- vehicles entered;
- vehicles left;
- optional average speed;
- optional travel time;
- density;
- optional time loss;
- sampled duration.

These values represent standardized simulation measurements rather than final application KPIs.

---

## 4.3 `ApproachTrafficState`

`ApproachTrafficState` represents traffic conditions for a canonical intersection approach.

It includes information such as:

- scenario ID;
- run ID;
- intersection ID;
- approach ID;
- queue-detection lane IDs;
- interval start and end;
- maximum queue length;
- mean maximum queued vehicles;
- started halts;
- vehicles observed;
- optional mean time loss.

Queue detection may require multiple consecutive SUMO lanes upstream from the stop line.

The model therefore stores:

```text
queue_detection_lane_ids
```

as an ordered list rather than assuming queue measurement occurs on one short lane.

The list must contain at least one valid lane ID and cannot contain duplicate IDs.

---

## 4.4 Vehicle Type Enum

The current standardized vehicle category is:

```text
car
```

This application-level category allows downstream components to work with a stable vehicle classification rather than depending directly on arbitrary SUMO vehicle-type identifiers.

---

# 5. Traffic Signal Model

Implemented in:

```text
jaadah/models/signals.py
```

Jaadah represents traffic-signal logic using canonical movement-level structures rather than exposing raw positional SUMO TLS strings as the application-level interface.

The implemented structures are:

- `SignalPhase`
- `SignalProgram`
- `MovementSignalState`
- `CurrentSignalState`

---

## 5.1 `SignalPhase`

`SignalPhase` represents one phase in a traffic-signal program.

It includes:

- `phase_id`
- `sequence_order`
- `served_movement_ids`
- green duration;
- yellow duration;
- all-red duration.

Every phase must serve at least one canonical movement.

Duplicate served movement IDs are rejected.

---

## 5.2 `SignalProgram`

`SignalProgram` represents a complete traffic-signal program associated with a scenario.

It contains information such as:

- signal-program ID;
- scenario ID;
- intersection ID;
- control type;
- cycle length;
- ordered phases;
- signal-program source;
- SUMO TLS ID.

The model verifies several structural rules:

- at least one phase must exist;
- phase IDs must be unique;
- phase sequence orders must be unique;
- the declared cycle length must match the sum of all phase durations.

Conceptually:

```text
cycle length
    =
Σ(green + yellow + all-red)
```

across the complete phase sequence.

This prevents internally inconsistent signal programs from reaching the simulation pipeline.

---

## 5.3 `MovementSignalState`

`MovementSignalState` represents the current signal indication for one canonical movement.

Supported indications are:

```text
green
yellow
red
```

For example:

```text
MOV_E_W → green
MOV_S_W → red
```

---

## 5.4 `CurrentSignalState`

`CurrentSignalState` represents the traffic-signal controller at a specific simulation time.

It includes information such as:

- scenario ID;
- run ID;
- intersection ID;
- signal-program ID;
- simulation time;
- timestamp;
- active phase ID;
- phase elapsed time;
- optional phase remaining time;
- movement-level signal states.

The model requires at least one movement state and rejects duplicate movement IDs.

Raw positional SUMO TLS strings remain an internal simulation and adapter concern.

---

# 6. Validation Strategy

Pydantic is used as a validation boundary throughout Jaadah.

Its purpose is to prevent structurally invalid data from silently moving between components.

Validation remains focused on **structural correctness**.

Traffic-domain logic such as detector allocation, traffic-demand estimation, KPI calculations, or intervention selection belongs to the appropriate application service rather than inside generic Pydantic validators.

---

## 6.1 Identifier Validation

Required identifiers must:

- be present;
- be strings;
- not be empty;
- not consist only of whitespace.

Examples include:

```text
observation_id
demand_id
intersection_id
movement_id
scenario_id
run_id
vehicle_id
```

---

## 6.2 Time Validation

Traffic and demand timestamps must be timezone-aware.

Historical and source-facing data times use:

```text
Asia/Riyadh
UTC+03:00
```

Intervals must satisfy:

```text
interval_end > interval_start
```

Jaadah uses half-open interval semantics:

```text
[start, end)
```

For example:

```text
08:00 → 08:15
```

includes the start of the interval but excludes the exact `08:15` boundary.

This prevents overlap between consecutive intervals.

---

## 6.3 Numeric Validation

Examples of numeric validation include:

- vehicle counts cannot be negative;
- physical durations cannot be negative;
- speeds cannot be negative;
- latitude must be within valid geographic bounds;
- longitude must be within valid geographic bounds;
- NaN and infinity are rejected where physical values are expected.

Python booleans are explicitly rejected where integer vehicle counts are expected, even though Python normally treats:

```python
True == 1
False == 0
```

as integer-compatible values.

---

## 6.4 Collection Validation

ID collections are validated where required.

Examples include:

- no duplicate `source_observation_ids`;
- no duplicate queue-detection lane IDs;
- no duplicate served movement IDs within a signal phase;
- no duplicate movement IDs within a current signal state.

---

## 6.5 Cross-Field Validation

Some structural rules depend on relationships between multiple fields.

For example:

```text
center_longitude + center_latitude
```

must either both be present or both be absent.

Other examples include:

```text
intervention scenario
        ↓
requires reference scenario
```

and:

```text
SignalProgram cycle_length_s
        ↓
must equal total phase durations
```

Pydantic model validators enforce these relationships when objects are created.

---

# 7. Why Pydantic Is Used

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

# 8. Architectural Boundaries

The canonical model defines shared meanings and structures.

It intentionally does not contain all project logic.

---

## 8.1 Network Mapping Is Separate

Canonical network entities do not contain complete SUMO topology mappings.

For example:

```text
MOV_E_W
```

defines a stable Jaadah movement.

A separate mapping layer determines which SUMO route implements that movement:

```text
MOV_E_W
     ↓
MovementMapping
     ↓
ordered SUMO route edges
```

The same approach is used for:

- intersections;
- approaches;
- detector relationships;
- queue-detection lanes;
- road segments;
- traffic-light controlled links.

Keeping mapping separate prevents generated SUMO identifiers from becoming application-level identities.

---

## 8.2 Demand Transformation Is Separate

Pydantic models do not decide how observed detector counts become movement demand.

For example:

```text
Detector observation = 100 vehicles
              ↓
      allocation method
          ↙        ↘
      MOV_A        MOV_B
        70           30
```

The rule producing the 70/30 allocation belongs to the Traffic Demand Transformation component.

It does not belong inside the generic data model.

This prevents traffic-domain assumptions from being hidden inside structural validation.

---

## 8.3 SUMO Input Generation Is Separate

`SimulationDemand` expresses:

```text
movement
+
time interval
+
vehicle count
```

It does not directly create SUMO XML or TraCI commands.

The SUMO adapter is responsible for converting canonical demand into the selected SUMO representation.

This preserves the rule:

> **SUMO adapts to Jaadah.**

---

## 8.4 Analytics and KPIs Are Separate

`EdgeTrafficState` and `ApproachTrafficState` represent standardized simulation measurements.

They do not define:

- final congestion KPIs;
- anomaly-detection results;
- forecasting outputs;
- recommendations;
- intervention decisions.

Those belong to analytics and application components that consume the canonical output structures.

---

# 9. Testing

The canonical model implementation is covered by unit tests using `pytest`.

Run the complete suite from the repository root with:

```bash
python -m pytest -v
```

Current result:

```text
284 passed
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
- invalid queue-detection lane lists;
- duplicate queue lanes;
- empty signal phases;
- duplicate served movements;
- duplicate signal phase IDs;
- duplicate signal phase sequence numbers;
- inconsistent signal cycle lengths;
- empty current signal states;
- duplicate movement signal states.

The test suite verifies the shared model before other components rely on it.

---

# 10. Data Flow

The canonical models sit at the center of the Jaadah simulation pipeline:

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
             SUMO + TraCI
                 ↓
       Output Standardization
                 ↓
      ┌──────────┼──────────┐
      ↓          ↓          ↓
 VehicleState  Traffic    Signal
               States     States
      ↓          ↓          ↓
Visualization Analytics Application
```

The resulting model provides:

- stable Jaadah identities;
- explicit separation between observed and derived data;
- scenario and execution separation;
- standardized simulation output structures;
- movement-oriented traffic-signal representation;
- explicit units and time semantics;
- validated structural constraints;
- shared serialization boundaries for backend integration;
- independence from source-specific and SUMO-specific formats.

Together, these structures form the common data language used across the Jaadah system.
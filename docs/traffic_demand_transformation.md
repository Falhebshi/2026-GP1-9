# Traffic Demand Transformation

## Overview

Jaadah's traffic-demand transformation turns standardized detector observations into the movement-level demand that SUMO is asked to simulate.

It receives canonical `TrafficObservation` objects from the ingestion layer and a `NetworkMappingConfig` from the mapping layer, and produces canonical `SimulationDemand` objects.

The transformation is the boundary between what a traffic source measured and what Jaadah asks SUMO to simulate. Its purpose is to make that step explicit and traceable, so that every demand value can be traced back to the observations it came from and no value is invented along the way.

The transformation flow is:

```text
TrafficObservation (one detector, one interval)
        |
        v
Detector-to-movement mapper
        |
        v
Movement ID
        |
        v
Batch transformation service
        |
        v
SimulationDemand (one movement, one interval)
```

The transformation does not retrieve traffic data, read or write SUMO files, generate routes, or run simulations.

---

## Package Structure

The implementation is located under:

```text
backend/
└── demand/
    ├── __init__.py
    ├── mapper.py
    └── service.py
```

Tests are located under:

```text
tests/
├── test_demand_mapper.py
├── test_demand_service.py
└── test_demand_integration.py
```

Each module has a separate responsibility:

| Module | Responsibility |
|---|---|
| `mapper.py` | Finds the detector mapping of one observation and returns its movement ID, or rejects it |
| `service.py` | Groups mapped observations by movement and interval, builds `SimulationDemand`, and reports everything that could not become demand. Also loads the network mappings for a batch |

This separation keeps the decision for a single observation independent of the batch-level checks.

---

## Role in the Jaadah Data Pipeline

The transformation sits between traffic ingestion and SUMO demand generation.

```text
Traffic-data source
        |
        v
Traffic ingestion
        |
        v
TrafficObservation
        |
        v
Traffic demand transformation   <-- this layer
        |
        v
SimulationDemand
        |
        v
SUMO demand generation
```

It depends on two inputs:

| Input | Provided by | Used for |
|---|---|---|
| `TrafficObservation` list | Traffic ingestion | The measured vehicle counts |
| `NetworkMappingConfig` | Network mapping layer | Which detector belongs to which movement, and how reliably |

A `SimulationDemand` contains Jaadah movement IDs but intentionally contains no SUMO identifiers. Resolving a movement to a SUMO route belongs to the next stage.

---

## Detector-to-Movement Mapper

The mapper is implemented in:

```text
backend/demand/mapper.py
```

### Finding the Detector Mapping

`find_detector_mapping()` looks up the mapping of one observation using three fields:

```text
source
site_id
detector_id
```

All three must match exactly.

This is the same key used by `NetworkMappingConfig` to reject duplicate detector mappings.

The site is part of the key because detector numbers repeat between sites. Detector `4` at site `9` is not detector `4` at site `1028`.

Every detector mapping must have a `site_id`; the mapping model rejects one without it.

### Mapping an Observation to a Movement

`map_observation_to_movement()` returns the movement ID of one observation.

For example:

```python
movement_id = map_observation_to_movement(
    observation,
    config,
)
```

might return:

```text
MOV_N_E
```

The result depends on the detector's mapping status:

| Mapping status | Meaning | Mapper behavior |
|---|---|---|
| no mapping | The detector is not in the configuration | Raises `ValueError("detector has no mapping")` |
| `unresolved` | The detector cannot be linked to any movement | Raises `ValueError("detector mapping is unresolved")` |
| `requires_allocation` | The detector serves two or more movements, for example a shared left-through lane | Raises `ValueError` naming the candidate movements |
| `usable` | The detector serves exactly one movement | Returns that movement ID |

A `usable` mapping always has exactly one movement. This is enforced by the `DetectorMapping` model.

Shared-lane detectors are not split. Their observations are reported until the team adopts a documented allocation method. The movements they serve are also held back; see [Shared-Lane Detector](#shared-lane-detector).

---

## Stable Demand IDs

Each `SimulationDemand` receives a readable demand ID.

The format is:

```text
DEM_<SOURCE>_<MOVEMENT_ID>_<YYYYMMDDTHHMM>
```

For example:

```text
DEM_SYN_MOV_N_E_20261014T0815
```

The source codes are:

| Source | Code |
|---|---|
| `synthetic` | `SYN` |
| `rcrc` | `RCRC` |

Like observation IDs, the timestamp in the demand ID uses the interval end.

The same source, movement and interval always produce the same demand ID.

The source is part of the ID so that synthetic and RCRC demand for the same movement and interval can never share an ID. Without it, storing one would overwrite the other.

---

## Batch Transformation Service

The transformation service is implemented in:

```text
backend/demand/service.py
```

Its workflow is:

```text
1. Map each observation to its movement
2. Record observations that cannot be mapped
3. Group mapped observations by source, movement and interval
4. Check each group for conflicting, shared-lane or missing detectors
5. Sum the vehicle counts of each complete group
6. Return demands and transformation errors
```

For example, if the north left turn `MOV_N_E` is counted by detectors `4`, `5` and `6`:

```text
Detector 4   08:00-08:15   10 vehicles
Detector 5   08:00-08:15   12 vehicles
Detector 6   08:00-08:15    7 vehicles
```

the service produces one demand:

```text
demand_id              = DEM_SYN_MOV_N_E_20261014T0815
movement_id            = MOV_N_E
interval               = 08:00-08:15
vehicle_count          = 29
source_observation_ids = OBS_SYN_9_4_20261014T0815
                         OBS_SYN_9_5_20261014T0815
                         OBS_SYN_9_6_20261014T0815
```

Every demand keeps the IDs of all observations it was built from.

The service returns a `DemandTransformationResult` containing:

```text
demands
errors
```

It also provides the following derived counts:

```text
demand_count
error_count
```

Demands are returned in interval order.

---

## Missing and Duplicate Observations

### Missing Detector

The service knows which usable detectors belong to each movement.

A movement total is only produced when every one of those detectors reported for the interval.

For example, if detector `6` sends nothing for `08:00-08:15`:

```text
Detector 4   10 vehicles
Detector 5   12 vehicles
Detector 6   no observation
```

the result is:

```text
No demand for MOV_N_E at 08:00-08:15
Error: no observation from detector(s) 6
```

Summing only detectors `4` and `5` would give `22`, which looks like a valid total but understates the real traffic. A missing detector is therefore reported rather than treated as zero.

This means SUMO receives no demand for that movement and interval. Filling such gaps with a documented estimation method is an open team decision.

### Shared-Lane Detector

Some movements are also counted by a shared-lane detector. For example, the west left turn `MOV_W_N` uses lane 1 (detector `1`, left only) and lane 2 (detector `2`, shared with the west through movement):

```text
Detector 1   left only           30 vehicles
Detector 2   left and through    40 vehicles, split unknown
```

Summing detector `1` alone would give `30`, which looks like a valid total but leaves out the left-turning part of lane 2. The result is therefore:

```text
No demand for MOV_W_N at 08:00-08:15
Error: movement also uses shared detector(s) 2; no allocation rule adopted
```

With the current mapping this holds back four movements:

| Shared detector | Movements held back |
|---|---|
| `2` (west, lane 2) | `MOV_W_N`, `MOV_W_E` |
| `10` (east, lane 2) | `MOV_E_S`, `MOV_E_W` |

Other movements are not affected. When an allocation rule is adopted, this check is where its result is added.

### Repeated Observation

The same detector may report the same interval more than once, for example after a source re-sends data.

If both reports carry the same vehicle count:

```text
Use the observation once
Report: duplicate observation ignored
```

If the reports carry different vehicle counts:

```text
No demand for that movement and interval
Report: detector sent different counts: 10 and 14
```

Different counts cannot both be correct, and choosing one would be a hidden guess. Adding them would count the same vehicles twice.

---

## Transformation Errors

Every observation or movement interval that does not become demand produces a `DemandTransformationError`.

Where available, the error records:

- the error message;
- the related observation IDs;
- the source site ID;
- the source detector ID;
- the movement ID;
- the interval end.

For example:

```text
message         = no observation from detector(s) 6
observation_ids = OBS_SYN_9_4_20261014T0815, OBS_SYN_9_5_20261014T0815
movement_id     = MOV_N_E
interval_end    = 2026-10-14T08:15:00+03:00
```

The possible messages are:

| Message | Cause |
|---|---|
| `detector has no mapping` | No mapping for the observation's source, site and detector |
| `detector mapping is unresolved` | The detector cannot be linked to a movement |
| `detector serves ...; no allocation rule adopted` | Shared-lane detector |
| `movement also uses shared detector(s) ...; no allocation rule adopted` | The movement's total needs a shared-lane detector's split |
| `no observation from detector(s) ...` | A detector of the movement did not report |
| `duplicate observation ignored` | The same count was reported twice |
| `detector sent different counts: ...` | Two different counts for the same detector and interval |

Errors about a single observation carry its site and detector. Errors about a movement interval carry the movement ID and all related observation IDs.

Observations that can be transformed are kept even when other observations in the same batch fail.

---

## Using the Transformation

`build_simulation_demand()` loads the network mappings and transforms one batch of observations:

```python
from backend.demand.service import build_simulation_demand

result = build_simulation_demand(
    observations=ingestion_result.observations,
)
```

By default it reads:

```text
data/processed/road_network/network_mappings.json
```

The path is found from the location of `service.py`, so the call works from any working directory. Another mapping file can be given with `mapping_path`.

The mappings are loaded with the one-argument `load_network_mappings()`, which checks the JSON structure and relationships but not the SUMO network.

The function takes a list of `TrafficObservation` rather than an `IngestionResult`, so the transformation does not depend on the ingestion package. Records that ingestion rejected never reach it; they stay in the ingestion errors.

---

## Separation from SUMO

The transformation package has no dependency on SUMO files.

It does not know:

```text
SUMO edge IDs
SUMO lane IDs
SUMO route IDs
traffic-light link indices
vehicle insertion logic
```

The mapping configuration contains SUMO route information, but the transformation only reads detector and movement relationships from it.

The intended relationship is:

```text
TrafficObservation
        |
        v
SimulationDemand
        |
        v
SUMO demand generation
        |
        v
SUMO routes and flows
```

---

## Testing

The transformation has dedicated tests for each module.

Run all transformation tests with:

```bash
python -m pytest -v \
  tests/test_demand_mapper.py \
  tests/test_demand_service.py \
  tests/test_demand_integration.py
```

The mapper and service tests use small mapping configurations built inside the test files. The integration tests use the real mapping file with one observation from each of the 16 synthetic detectors. No test needs the SUMO network.

The tests cover:

- usable detectors mapped to their movement;
- exact matching on source, site and detector;
- unmapped, unresolved and shared-lane detectors;
- movements held back because they use a shared-lane detector;
- stable demand IDs for synthetic and RCRC sources;
- summing usable detectors into one demand;
- preserving every source observation ID;
- separate demand for each interval;
- conservation of vehicle counts;
- missing detectors;
- identical and conflicting repeated observations;
- valid observations processed alongside rejected ones;
- empty batches;
- rejection of detector mappings that reference unknown movements;
- the real mappings: demand for the five movements without shared lanes, and the four shared-lane movements held back;
- every observation either used in demand or reported.

The transformation tests are also included in the full Jaadah project test suite.

---

## Current Scope and Open Decisions

The transformation currently produces demand only from `usable` detectors.

The following decisions are open and are not implemented:

| Decision | Current behavior |
|---|---|
| Allocation method for shared left-through lanes | Reported, not split; the four movements that use them get no demand |
| East and west through detectors also counting ramp and U-turn traffic | Depends on how these detectors are mapped |
| Movements with no detector (U-turns, tunnel, tunnel on-ramp) | No demand produced |
| Filling missing detector intervals, and marking estimated demand | Reported, not filled |

When a decision is adopted, it should be added as a separate documented rule with its own tests, without changing how usable detectors are handled.

---

## Design Summary

The traffic-demand transformation provides a traceable boundary between observed traffic and simulated demand.

Its main design principles are:

- detectors are matched exactly on source, site and detector;
- only detectors that serve exactly one movement produce demand;
- shared lanes are not split without a documented method, and movements that need them get no demand;
- missing data is reported, never treated as zero;
- repeated observations are never counted twice;
- every demand keeps the IDs of the observations it came from;
- demand IDs are stable and readable;
- valid observations are kept when others fail;
- the transformation remains independent of SUMO files.

This gives SUMO demand generation a consistent movement-level input whose every value can be traced back to measured traffic.

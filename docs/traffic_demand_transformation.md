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
| `requires_allocation` | The detector serves two or more movements, for example a shared left-through lane | Raises `ValueError` naming the candidate movements; the service splits these counts instead (see [Shared-Lane Allocation](#shared-lane-allocation)) |
| `usable` | The detector serves exactly one movement | Returns that movement ID |

A `usable` mapping always has exactly one movement. This is enforced by the `DetectorMapping` model.

The mapper handles one observation and one movement. Shared-lane detectors are not passed to it; the batch service splits their counts between movements.

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
1. Map each observation to its movement, or set it aside if it comes from a shared-lane detector
2. Record observations that cannot be mapped
3. Group mapped observations by source, movement and interval
4. Split each shared-lane count between its movements
5. Check each group for conflicting or missing detectors
6. Sum the vehicle counts of each complete group, including its parts of shared-lane counts
7. Return demands and transformation errors
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

## Shared-Lane Allocation

### Why the Split Is an Assumption

A shared-lane detector counts every vehicle in its lane, without knowing which movement each one takes. With the current mapping there are two such detectors:

| Shared detector | Lane | Movements |
|---|---|---|
| `2` | west, lane 2 | `MOV_W_N` (left), `MOV_W_E` (through) |
| `10` | east, lane 2 | `MOV_E_S` (left), `MOV_E_W` (through) |

The split between the movements cannot be measured from detector counts, whether synthetic or RCRC. Turning movement counts in shared lanes cannot be obtained from loop-based data unless additional detectors are installed (Noyce et al., 2019, Section 1.1.1), and no automated method exists without downstream detectors (Gholami and Tian, 2016, Section 2). The methods of Gholami and Tian need downstream counts, per-vehicle headways or calibration counts, none of which are available here.

The split is therefore a **modelled assumption**. It was agreed with the KPI engine owner on 20 October 2026.

### Proportional Split

The shared lane is assumed to carry the same mix as the exclusive lanes next to it in the same interval:

```text
volume per lane (movement) = count of the movement's exclusive lanes / number of those lanes
share (movement)           = volume per lane (movement) / sum over the lane's movements
```

The exclusive lanes are found from the mapping: the `usable` detectors on the same approach that count one of the shared lane's movements alone.

West example, detectors `1`, `2` and `3`:

```text
Detector 1   left only           10 vehicles
Detector 2   left and through    20 vehicles
Detector 3   through only        30 vehicles

left share   = 10 / (10 + 30) = 0.25
detector 2   = 5 left + 15 through
MOV_W_N      = 10 + 5  = 15
MOV_W_E      = 30 + 15 = 45
```

East example, where the through movement has two exclusive lanes (detectors `11` and `12`):

```text
Detector 9        left only           90 vehicles
Detector 10       left and through   100 vehicles
Detectors 11, 12  through only       110 + 120 vehicles

through per lane = 230 / 2 = 115
left share       = 90 / (90 + 115) = 0.439
detector 10      = 44 left + 56 through
MOV_E_S          = 90 + 44        = 134
MOV_E_W          = 110 + 120 + 56 = 286
```

In a quiet interval the split follows the actual mix. With 1 vehicle in the left lane and 30 in the through lane, a shared count of 20 gives 1 left and 19 through.

When the exclusive lanes counted no vehicles at all, there is no mix to follow and the lane is split equally.

The proportional split was chosen over two alternatives:

| Alternative | Reason not used |
|---|---|
| A fixed split such as 50/50 | Does not follow the interval's actual mix |
| The KPI engine's HCM lane-choice model in reverse | The lane counts barely change with the split, so small count differences give very different splits |

### Whole Vehicles

Demand is a whole number of vehicles. Each part is rounded down and the remaining vehicles go to the parts with the largest remainders; ties go to the movement ID that comes first. The parts always add up to the shared count:

```text
Detector 2 = 45, shares 0.5 / 0.5
MOV_W_E    = 23
MOV_W_N    = 22
```

### Marking Allocated Demand

Every demand that contains part of a shared-lane count lists that observation in `allocated_observation_ids`, and its computed `is_allocated` is true (see [Data models](data_models.md), section 1.2). The observation is also in `source_observation_ids`. The KPI engine uses `is_allocated` to label its results *modelled assumption*, even when the source is RCRC.

### Missing or Conflicting Data

The split needs the shared detector and all of its exclusive-lane detectors in the same interval. Otherwise both movements of the lane get no demand:

| Situation | Message |
|---|---|
| The shared detector did not report | `no observation from detector(s) 2` |
| An exclusive-lane detector did not report, or sent different counts | `split of shared detector 2 needs detector(s) 3` |
| The shared detector sent different counts | `shared detector 2 sent different counts` |
| A movement of the shared lane has no exclusive lane in the mapping | `shared detector 2 has no exclusive lane for every movement to split by` |

### Sensitivity Runs

Because the split is assumed, its effect on the results should be shown. `share_adjustments` moves the share of one movement of a shared lane by a number of percentage points, and the other movement receives the rest:

```python
result = build_simulation_demand(
    observations=observations,
    share_adjustments={
        "MOV_W_N": -0.2,
        "MOV_E_S": -0.2,
    },
)
```

The agreed runs use −0.2 and +0.2 on the left movements (for example, a share of 50 % becomes 30 % and 70 %). Shares stay between 0 and 1, and the lane totals do not change. An adjustment for a movement that no shared lane serves is rejected.

### References

- Noyce, D. A., Bill, A. R., Chitturi, M. V., and Santiago-Chaparro, K. R. (2019). *Turning Movement Counts on Shared Lanes: Prototype Development and Analysis Procedures*. NCHRP IDEA Project 198 Final Report, Transportation Research Board.
- Gholami, A., and Tian, Z. (2016). Using stop bar detector information to determine turning movement proportions in shared lanes. *Journal of Advanced Transportation*, 50, 802–817. https://doi.org/10.1002/atr.1376

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

A movement that uses a shared lane also needs that lane's detector. When it is missing, the movement gets no demand and the error names it, as for any other detector:

```text
Error: no observation from detector(s) 2
```

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
| `split of shared detector ... needs detector(s) ...` | An exclusive-lane detector needed for the split did not report or sent different counts |
| `shared detector ... sent different counts` | Two different counts from a shared-lane detector |
| `shared detector ... has no exclusive lane for every movement to split by` | The mapping gives a shared-lane movement no exclusive lane |
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

For sensitivity runs, `share_adjustments` is passed on to the split (see [Sensitivity Runs](#sensitivity-runs)).

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
- unmapped and unresolved detectors;
- proportional splitting of shared-lane counts, in whole vehicles, with the equal-split fallback;
- marking split demand as allocated;
- missing and conflicting shared-lane and exclusive-lane detectors;
- sensitivity adjustments and their limits;
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
- the real mappings: demand for all nine movements with detectors, the four shared-lane movements marked as allocated, and sensitivity runs that keep the approach totals;
- every observation either used in demand or reported.

The transformation tests are also included in the full Jaadah project test suite.

---

## Current Scope and Open Decisions

The transformation produces demand from `usable` detectors and from split shared-lane detectors.

The following decisions are open and are not implemented:

| Decision | Current behavior |
|---|---|
| Observed turning proportions for the shared lanes (Gholami and Tian, 2016, Section 3.4) | Not available; the proportional split is used |
| East and west through detectors also counting ramp and U-turn traffic | Depends on how these detectors are mapped |
| Movements with no detector (U-turns, tunnel, tunnel on-ramp) | No demand produced |
| Filling missing detector intervals, and marking estimated demand | Reported, not filled |

When a decision is adopted, it should be added as a separate documented rule with its own tests, without changing how usable detectors are handled.

---

## Design Summary

The traffic-demand transformation provides a traceable boundary between observed traffic and simulated demand.

Its main design principles are:

- detectors are matched exactly on source, site and detector;
- detectors that serve exactly one movement are summed directly;
- shared-lane counts are split by a documented modelled assumption, and the split demand is marked;
- missing data is reported, never treated as zero;
- repeated observations are never counted twice;
- every demand keeps the IDs of the observations it came from;
- demand IDs are stable and readable;
- valid observations are kept when others fail;
- the transformation remains independent of SUMO files.

This gives SUMO demand generation a consistent movement-level input whose every value can be traced back to measured traffic, with the assumed part of shared-lane demand marked.

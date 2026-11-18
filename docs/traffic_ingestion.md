# Traffic Ingestion

## Overview

Jaadah's traffic-ingestion layer retrieves traffic observations from an external traffic-data source and converts them into Jaadah's canonical `TrafficObservation` model.

The ingestion layer forms the boundary between source-specific data formats and the rest of the Jaadah application. Its purpose is to ensure that downstream components do not depend directly on the field names, response structure, or implementation details of a particular traffic-data provider.

The implementation supports two sources:

- Jaadah's standalone synthetic traffic source, read over HTTP, which acts as a development substitute for an external provider;
- the RCRC replay source, which plays back RCRC reports for the study intersection (site 1444) as a live feed (see [RCRC Source](#rcrc-source)).

The ingestion flow is:

```text
Traffic-data source
        |
        v
HTTP client
        |
        v
Raw source records
        |
        v
Source adapter
        |
        v
Canonical TrafficObservation
        |
        v
Downstream mapping and simulation pipeline
```

The ingestion layer does not perform detector-to-movement mapping, SUMO route mapping, simulation-demand generation, or traffic simulation.

---

## Package Structure

The implementation is located under:

```text
backend/
└── ingestion/
    ├── __init__.py
    ├── adapter.py
    ├── client.py
    └── service.py
```

Tests are located under:

```text
tests/
├── test_ingestion_adapter.py
├── test_ingestion_client.py
├── test_ingestion_service.py
├── test_ingestion_integration.py
└── test_rcrc_ingestion.py          RCRC client, adapter, and replay source to ingestion
```

Each module has a separate responsibility:

| Module | Responsibility |
|---|---|
| `client.py` | Communicates with the traffic-data source over HTTP |
| `adapter.py` | Converts one source-specific record into a canonical `TrafficObservation` |
| `service.py` | Coordinates batch retrieval and adaptation and reports rejected records |

This separation keeps HTTP communication, source-format interpretation, and batch-processing logic independent.

---

## Role in the Jaadah Data Pipeline

The ingestion layer sits between the external traffic source and Jaadah's canonical data model.

```text
Synthetic traffic source
        |
        | HTTP
        v
Traffic ingestion
        |
        v
TrafficObservation
        |
        v
Detector and movement mapping
        |
        v
SimulationDemand
        |
        v
SUMO demand generation
```

A `TrafficObservation` represents what the traffic-data source actually supplied.

It intentionally does not contain:

- Jaadah movement IDs;
- Jaadah-derived intersection mappings;
- SUMO edge IDs;
- SUMO lane IDs;
- SUMO route IDs.

Those relationships belong to later mapping and demand-transformation stages.

This preserves the distinction between source observations and information later derived by Jaadah.

---

## Synthetic Traffic Client

The HTTP client is implemented in:

```text
backend/ingestion/client.py
```

`SyntheticTrafficClient` communicates with the standalone synthetic traffic source through its HTTP API.

The client accepts a source base URL and an optional request timeout.

For example:

```python
client = SyntheticTrafficClient(
    base_url="http://127.0.0.1:8000",
    timeout_s=5.0,
)
```

The client retrieves traffic observations through:

```text
GET /observations
```

using `start` and `end` query parameters.

For example:

```text
/observations
    ?start=2026-10-15T20:00:00+03:00
    &end=2026-10-15T20:30:00+03:00
```

The supplied Python datetimes are serialized using ISO 8601.

The client is intentionally limited to HTTP communication and response-envelope validation. It does not convert individual source records into Jaadah models.

---

## Source Response Validation

The synthetic source response must contain an `observations` list.

A valid response has the general structure:

```json
{
  "source": "synthetic",
  "observations": [
    {
      "Site ID": 9,
      "detector_id": 1,
      "Date  & Time": "2026-10-15T20:15:00+03:00",
      "volume": 50,
      "description": "SYN-EB-L1-L-STB"
    }
  ]
}
```

The client verifies that the `observations` field exists and contains a list.

It does not validate every record inside that list. Record-level validation belongs to the adapter and ingestion service.

HTTP failures are not hidden. If the source returns an unsuccessful HTTP status, the corresponding HTTP exception is raised.

Similarly, connection failures propagate to the caller rather than being interpreted as a successful request containing no traffic observations.

---

## Synthetic Record Adapter

The source adapter is implemented in:

```text
backend/ingestion/adapter.py
```

The adapter converts one synthetic-source record into a canonical Jaadah `TrafficObservation`.

The current synthetic source provides the following required fields:

| Source field | Canonical representation |
|---|---|
| `Site ID` | `site_id` |
| `detector_id` | `detector_id` |
| `Date  & Time` | `interval_end` |
| `volume` | `vehicle_count` |
| `description` | `description` |

The adapter removes source-specific field naming from downstream processing.

For example:

```text
"Site ID"
```

becomes:

```text
site_id
```

and:

```text
"volume"
```

becomes:

```text
vehicle_count
```

Once adaptation is complete, downstream Jaadah components consume the canonical model rather than the original source representation.

---

## Observation Intervals

The synthetic traffic source currently represents traffic using 15-minute intervals.

Its `Date  & Time` field represents the end of the physical traffic interval.

For example:

```text
Source timestamp:
2026-10-15T20:15:00+03:00
```

is standardized as:

```text
interval_start = 2026-10-15T20:00:00+03:00
interval_end   = 2026-10-15T20:15:00+03:00
```

The adapter reconstructs the interval start by subtracting 15 minutes from the source timestamp.

Synthetic timestamps must also fall exactly on a 15-minute boundary.

Valid examples include:

```text
20:00
20:15
20:30
20:45
```

A timestamp such as:

```text
20:17
```

is rejected.

The canonical `TrafficObservation` model separately enforces timezone requirements and requires standardized traffic timestamps to use Riyadh time (`UTC+03:00`).

---

## Stable Observation IDs

Each accepted source record receives a deterministic observation identifier.

The current format is:

```text
OBS_<SOURCE>_<SITE>_<DETECTOR>_<INTERVAL_END>
```

For example:

```text
OBS_SYN_9_1_20261015T2015
```

This identifies:

```text
OBS             Jaadah traffic observation
SYN             synthetic source
9               external site identifier
1               external detector identifier
20261015T2015   interval-end timestamp
```

The identifier is deterministic rather than randomly generated.

Ingesting the same source observation again therefore produces the same observation ID, which supports traceability and reproducibility.

---

## Canonical TrafficObservation

After adaptation, a source record is represented using Jaadah's canonical `TrafficObservation`.

An example observation is:

```text
observation_id      = OBS_SYN_9_1_20261015T2015
source              = synthetic
site_id             = 9
detector_id         = 1
interval_start      = 2026-10-15T20:00:00+03:00
interval_end        = 2026-10-15T20:15:00+03:00
vehicle_count       = 50
description         = SYN-EB-L1-L-STB
average_speed_kmh   = null
travel_time_s       = null
```

`average_speed_kmh` and `travel_time_s` remain `None` because the current synthetic traffic source does not provide these measurements.

The ingestion layer does not invent unavailable traffic measurements.

---

## Validation Responsibilities

Validation is intentionally divided between the source adapter and the canonical model.

The adapter validates source-specific requirements, including:

- the source record must be an object;
- required synthetic-source fields must exist;
- required source identifiers must not be null;
- the source description must not be null or empty;
- the source timestamp must be a valid ISO datetime;
- the timestamp must align with a 15-minute boundary.

The canonical `TrafficObservation` model validates Jaadah-wide requirements, including:

- required identifiers must not be empty;
- timestamps must contain timezone information;
- timestamps must use Riyadh time;
- `interval_end` must be later than `interval_start`;
- `vehicle_count` must be a non-negative integer;
- boolean values must not be interpreted as vehicle counts.

Keeping these responsibilities separate avoids duplicating generic Jaadah validation logic inside each source adapter.

---

## Batch Ingestion Service

The ingestion service is implemented in:

```text
backend/ingestion/service.py
```

The service coordinates the HTTP client and source adapter.

Its workflow is:

```text
1. Fetch source observations
2. Process each source record independently
3. Adapt valid records into TrafficObservation objects
4. Record information about invalid records
5. Return accepted observations and rejected-record details
```

The service returns an `IngestionResult` containing:

```text
observations
errors
```

It also provides the following derived counts:

```text
received_count
accepted_count
rejected_count
```

The received count is the total number of records returned by the traffic source.

Accepted records become canonical `TrafficObservation` objects.

Rejected records are represented by `IngestionError` objects.

---

## Partial Rejection

Jaadah uses partial rejection for malformed individual source records.

For example, if the source returns:

```text
Record 1   valid
Record 2   invalid vehicle count
Record 3   valid
```

the ingestion result becomes:

```text
received = 3
accepted = 2
rejected = 1
```

The two valid observations are retained.

The invalid record is reported separately rather than causing the entire batch to be discarded.

This prevents one malformed source record from making all otherwise valid traffic observations unavailable.

---

## Ingestion Errors

Each rejected record produces an `IngestionError`.

Where available, the error records:

- the record number within the fetched batch;
- the validation error message;
- the source site ID;
- the source detector ID;
- the source timestamp.

For example:

```text
record_number    = 2
site_id          = 9
detector_id      = 2
source_timestamp = 2026-10-15T20:15:00+03:00
message          = validation error ...
```

If the source item is not a valid object, unavailable identifying fields remain `None`.

This allows malformed records to be reported without requiring the malformed record itself to satisfy the expected source structure.

---

## Record Failure vs. Source Failure

Jaadah distinguishes between an invalid individual record and failure of the traffic-data source itself.

### Individual Record Failure

Examples include:

```text
negative vehicle count
missing required source field
invalid timestamp
blank description
```

The behavior is:

```text
Reject the invalid record
Continue processing the remaining records
Report the error in IngestionResult
```

### Source-Level Failure

Examples include:

```text
connection failure
HTTP server error
invalid response envelope
```

The behavior is:

```text
Fail the ingestion operation
Propagate the source/client error
```

A traffic-data provider failure is therefore not silently converted into an empty successful ingestion result.

This prevents an outage from being interpreted as a valid period containing zero observed traffic.

---

## Separation from SUMO

The ingestion package has no dependency on the SUMO network model.

It does not know:

```text
SUMO edge IDs
SUMO lane IDs
SUMO route IDs
traffic-light link indices
vehicle insertion logic
```

Likewise, the synthetic traffic source does not need to know how its external detectors map onto the SUMO network.

The intended relationship is:

```text
External detector
        |
        v
TrafficObservation
        |
        v
Jaadah detector/movement mapping
        |
        v
SimulationDemand
        |
        v
SUMO-specific demand representation
```

This separation allows the external traffic-data representation and the SUMO simulation model to evolve independently.

---

## Dependencies

HTTP communication uses:

```text
httpx2
```

The ingestion implementation is currently synchronous.

This is sufficient for the current proof-of-concept workflow, where traffic observations are retrieved in relatively small batches rather than through high-frequency concurrent polling.

The communication layer can later be extended if asynchronous or persistent HTTP communication becomes necessary.

---

## Testing

The ingestion implementation has dedicated tests for each layer.

Run all ingestion tests with:

```bash
python -m pytest -v \
  tests/test_ingestion_adapter.py \
  tests/test_ingestion_client.py \
  tests/test_ingestion_service.py \
  tests/test_ingestion_integration.py
```

The tests cover:

- valid source-record adaptation;
- deterministic observation IDs;
- required-field validation;
- timestamp-boundary validation;
- canonical vehicle-count validation;
- HTTP request construction;
- HTTP error propagation;
- source response-envelope validation;
- partial rejection of malformed source records;
- handling of non-object records;
- successful all-valid batches;
- propagation of source connectivity failures.

The ingestion tests are also included in the full Jaadah project test suite.

---

## End-to-End Validation

The integration tests exercise the synthetic generator, producer, SQLite
storage, FastAPI application, HTTP client, adapter, and ingestion service
together. They use artificial profiles and an isolated test database, with
HTTP requests routed through the application's in-process test client.
Private reference files and a running server are not required.

A request covering two 15-minute intervals across all 16 detector streams
must produce:

```text
Received: 32
Accepted: 32
Rejected: 0
```

The tests cross Thursday/Friday, Friday/Saturday, and Saturday/Sunday midnight
boundaries. Midnight-ending records retain the preceding traffic day's
expected level; the following `00:15` records use the new day type. Adaptation
preserves both timestamps, vehicle counts, and the `SLP` descriptions on
detectors 13/14 and `BYP` descriptions on detectors 15/16. Repeated ingestion
returns the same observation IDs without adding source database rows.

This branch includes the revised synthetic source from PR #12, which consumes
PR #11's methodology-version-2 profiles. Ingestion does not read or recompute
those profiles and does not interpret the description suffixes as movement
or SUMO mappings; it preserves the provider description for downstream use.

This validates the complete local development path:

```text
Synthetic generator
        |
        v
Synthetic SQLite storage
        |
        v
FastAPI /observations
        |
        v
SyntheticTrafficClient
        |
        v
Source adapter
        |
        v
TrafficObservation
        |
        v
IngestionResult
```

---

## RCRC Source

### A Live Feed, Replayed

Jaadah is a digital twin: traffic data arrives continuously and is simulated as it comes in. RCRC delivers reports as files, so the RCRC data is played back by the **RCRC replay source** (`traffic_source/rcrc_replay/`, see [RCRC replay source](rcrc_replay_source.md)), a separate service with the same kind of API as the synthetic source. It releases one 15-minute interval at a time as its clock advances. Jaadah pulls from it exactly as it would from a live RCRC feed:

```text
Private RCRC report (CSV)
        |
        v
RCRC replay source        releases intervals over time, serves rows as RCRC wrote them
        |
        | HTTP: /health, /observations
        v
RcrcReplayClient
        |
        v
RCRC adapter              RCRC row -> TrafficObservation
        |
        v
IngestionResult
```

A live RCRC feed would replace only the replay source. The client, adapter and everything after them stay the same.

### Client

`RcrcReplayClient` (`backend/ingestion/client.py`) has the same two calls as `SyntheticTrafficClient`:

- `fetch_observations(start, end)` returns an `RcrcBatch`: the rows as RCRC wrote them and the `site_id` of the response, because RCRC rows do not name their site;
- `fetch_latest_available_timestamp()` reads `/health`. An interval ending at or before this time that has no rows is **missing data**, not data still to come. The demand transformation uses this to fill the newest interval during an outage (see [Traffic demand transformation](traffic_demand_transformation.md#site-wide-outages)).

A response without an `observations` list or a `site_id`, an HTTP error or a connection failure is raised, never turned into an empty batch.

### Converting a Row

`ingest_rcrc_observations(client, start, end)` (`backend/ingestion/service.py`) adapts every row with `adapt_rcrc_record` (`backend/ingestion/adapter.py`) and returns the same `IngestionResult` as the synthetic ingestion.

| RCRC field | Canonical representation |
|---|---|
| `site_id` of the response | `site_id` |
| `Detector ID : Description` before the colon | `detector_id` |
| `Detector ID : Description` after the colon | `description` |
| `Time Stamp` | `interval_end` |
| `Volume (Vehicles)` | `vehicle_count` |
| `Occupancy (Seconds)` | `occupancy_s` |
| `Occupancy (Percent)` | `occupancy_percent` |

Detector IDs are kept exactly as RCRC sends them (`144409`, ...). A `TrafficObservation` records what the source supplied and is never rewritten; Jaadah's own names are the lanes and movements the mapping links each detector to. Observation IDs use the `RCRC` code: `OBS_RCRC_1444_144409_20260713T0015`.

The RCRC export format is **not** the format of the site 1028 sample that the synthetic source imitates (`Site ID`, `Date  & Time`, `volume`), so the two sources have separate adapters.

### Time Stamps

RCRC time stamps have no timezone. They are read as Riyadh time (UTC+03:00) and as the **end** of the 15-minute interval, the convention used in the [RCRC sample analysis](rcrc_sample_analysis.md). A `00:00` time stamp therefore closes the previous day's last interval.

This convention is not stated in the report, and the first site 1444 report has a record at both its start (`Jul 13 00:00`) and its end (`Oct 13 00:00`), one interval more than the period holds. **It should be confirmed with RCRC.** If RCRC uses interval starts, only `parse_rcrc_interval_end()` and the interval-start calculation in `adapt_rcrc_record()` change.

### Row Validation

A row is rejected, and reported in `IngestionResult.errors` without stopping the batch, when:

- a field is missing, or the row is not an object;
- the detector value is not `<numeric ID>: <description>`;
- the time stamp does not look like `Jul 13, 2026 00:15:00` or is not on a 15-minute boundary;
- the volume is not a non-negative whole number;
- an occupancy value is present but not a non-negative finite number, the occupied seconds are longer than the interval, or the percentage is above 100.

A row with a valid volume but invalid occupancy is rejected as a whole, because a damaged occupancy value suggests the row itself is damaged. Blank occupancy values are allowed and stored as `None`. A volume of zero is a valid count.

### Occupancy

A loop detector reports, for each interval, how many vehicles passed over it (volume) and how long a vehicle was over it (occupancy). An interval is 15 × 60 = 900 seconds, so occupancy is between 0 and 900 seconds, or 0–100 %. The percentage is the seconds divided by 900, rounded.

Occupancy is stored on `TrafficObservation` (optional, because the synthetic source has none) but is not used by the demand transformation, which uses volume only. It is kept for:

- calibration, by comparing it with occupancy from SUMO detectors placed at the same stop bars;
- recognising oversaturation, when volume levels off while occupancy keeps rising, so the counts understate demand;
- anomaly detection and detector fault checks.

These are stop-bar detectors, so occupancy also rises with red time and changes with the signal plan. It should be compared within the same timing plan and time of day, and is not a user-facing KPI.

### Detectors

All 12 site 1444 detectors are stop-bar (`STB`) detectors. Their descriptions read `<phase>-<travel direction>-<lane>-<turns>-STB-<ring/phase>`, for example `P4-EB-L2-TL-STB-RP4`: phase 4, eastbound, lane 2, left and through. Lanes are numbered from the median, as in Jaadah (confirmed with RCRC's numbering of the westbound approach). The report has no detectors on the right-turn slips or the south bypass. See [Network mapping](network_mapping.md#rcrc-site-1444-detectors).

### Missing-Data Policy

| Case | Handling | Marked as |
|---|---|---|
| Invalid row | Rejected at ingestion and reported | `IngestionError` |
| One detector silent while others report | Estimated from neighbouring detectors, or its time-slot average scaled by the hour before | `imputed_detectors` |
| Whole site silent, for up to 5 intervals | Estimated from time-slot averages scaled by the hour before, including shared lanes | `imputed_detectors` |
| Silent for longer | Left missing and reported; the run does not start | Demand transformation error |
| Movement with no detector (slips, bypass) | Ratio of the counted movements on the same approach | `share_estimate` |

The 5-interval limit was chosen by evaluation on the site 1444 report (`analysis/rcrc_site_1444/gap_limit_evaluation.py`). Every estimated value is labelled, and the KPI engine reports results that use one as a *modelled assumption*.

---

## Current Scope

The ingestion layer currently supports Jaadah's synthetic traffic source and RCRC sources (the replay source today).

Its architecture is intentionally source-oriented so that additional adapters and clients can be introduced later when other traffic-data providers are integrated.

Future source integrations should preserve the same principle:

```text
Source-specific representation
        |
        v
Source-specific ingestion adapter
        |
        v
Jaadah canonical TrafficObservation
```

Downstream components should continue consuming canonical Jaadah structures rather than depending on provider-specific payloads.

---

## Design Summary

The traffic-ingestion layer provides a clean boundary between traffic-data providers and the rest of Jaadah.

Its main design principles are:

- source-specific formats stop at the ingestion boundary;
- HTTP communication is separated from record adaptation;
- canonical validation remains centralized in Jaadah's data models;
- valid records are retained when individual records are malformed;
- source-level failures are not hidden;
- external source identifiers are preserved for traceability;
- deterministic observation IDs support reproducibility;
- unavailable measurements are not invented;
- traffic observations remain independent of movement and SUMO mappings.

This provides downstream Jaadah components with a consistent traffic-observation representation regardless of how the external traffic data is originally delivered.

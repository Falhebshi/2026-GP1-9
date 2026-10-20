# Synthetic Traffic Source

## Overview

Jaadah includes a standalone synthetic traffic-data source that emulates the external traffic observations expected from a real traffic-data provider.

The purpose of this component is to let the rest of the system be developed and tested before continuous real-world traffic data is available. It produces realistic detector-level traffic volumes, stores them locally, and exposes them through an HTTP API.

The synthetic source is intentionally implemented outside the SUMO simulation package:

```text
traffic_source/
└── synthetic/
    ├── config.py
    ├── generator.py
    ├── producer.py
    ├── server.py
    └── storage.py
```

This separation is deliberate. The synthetic source represents an **external traffic-data provider**, while SUMO represents the **traffic simulation environment**. Keeping them independent allows Jaadah to replace the synthetic source with a real provider later without redesigning the simulation layer.

---

## Role in the Jaadah Architecture

The synthetic source sits at the beginning of the traffic-data pipeline.

```text
Synthetic Traffic Source
        │
        │ detector observations
        ▼
Traffic Ingestion
        │
        ▼
Canonical Jaadah Traffic Models
        │
        ▼
Demand Transformation
        │
        ▼
SUMO Simulation
        │
        ▼
Traffic State / Analytics / Visualization
```

The source is responsible only for producing and serving traffic observations.

It does **not**:

- generate SUMO routes,
- map detectors to SUMO lanes or edges,
- create simulation demand,
- calculate traffic KPIs,
- or run the SUMO simulation.

Those responsibilities belong to later layers of the system.

---

## Why a Synthetic Source Is Needed

The final Jaadah system is designed to ingest traffic observations from an external source. During development, however, continuous traffic data may not always be available.

Using hard-coded values directly inside the simulator would tightly couple traffic generation to SUMO and would not exercise the real ingestion path.

Instead, Jaadah uses a synthetic source that behaves like an independent traffic-data service:

1. Traffic observations are generated independently of SUMO.
2. Generated observations are persisted in a database.
3. An HTTP API exposes only the observations currently available.
4. Jaadah's ingestion layer consumes the API as it would consume an external source.

This makes the development pipeline closer to the intended final architecture.

---

## Package Responsibilities

### `config.py`

Defines the configuration used by the synthetic source.

This includes:

- source timezone,
- generation seed,
- traffic scenario,
- observation interval,
- paths to local traffic-profile artifacts,
- generated database location,
- and initial history duration.

The default source interval is **15 minutes**, and timestamps use the `Asia/Riyadh` timezone.

The default random seed allows generated data to remain reproducible across runs.

---

### `generator.py`

Contains the traffic-generation logic.

The generator creates detector-level traffic observations using traffic patterns derived from the available reference data.

It models several characteristics of traffic behavior, including:

- variation across the time of day,
- differences between day types,
- differences between detector streams,
- shared variation across detectors,
- temporal persistence between consecutive observations,
- and configurable traffic-volume scenarios.

The generator exposes **16 synthetic detector streams** for the target site.

Each generated observation is represented internally as a `SyntheticDetectorObservation` containing:

```text
site_id
detector_id
timestamp
volume
description
```

The generator does not contain SUMO lane IDs, edge IDs, or route IDs. Mapping a traffic detector to Jaadah movements and then to the SUMO network is handled separately by the demand/network mapping layer.

---

## Synthetic Detector Model

The synthetic source currently exposes one target site with 16 detector streams.

The detectors represent directional traffic streams around the case-study intersection and are assigned stable synthetic detector IDs.

The detector definitions are part of the synthetic source itself and do not depend on SUMO.

This is important because the source should describe traffic observations independently of how those observations are later represented inside the simulator.

---

## Traffic Profiles

Synthetic generation uses processed traffic-profile artifacts produced by the traffic-data analysis component.

These files are intentionally stored **outside the Git repository**.

The expected local structure is:

```text
GitHub/
├── 2026-GP1-9/
│   └── ...
│
└── jaadah-private-data/
    └── processed/
        └── rcrc_sample/
            └── ...
```

The synthetic source therefore expects the profile directory at:

```text
../jaadah-private-data/processed/rcrc_sample/
```

relative to the repository root.

The repository does not publish the original RCRC sample or its derived profile outputs.

This separation allows the source code and tests to remain public while keeping restricted traffic-data artifacts outside version control.

The revised analysis contract is methodology version 2 in
`rcrc_profile_summary.json`. Regenerate all analysis files together before
running this source. The loader rejects old versions, missing workday-noise
columns, and sample SDs without at least two observations.

The reference is one week from a different intersection: 18 reference
detectors, 672 intervals each, five Sunday–Thursday workdays, one Friday and
one Saturday. It does not measure Jaadah's target intersection. Boundary
timestamps can span partial calendar dates under interval-end semantics.

Expected detector-slot means and stochastic `std_volume` now come from
workdays only. The SD uses the ordinary sample denominator (`ddof=1`), with
no additional `5/4` correction. Friday and Saturday reuse this workday noise
model as an explicit development assumption.

Weekend expected profiles use the workday temporal reference multiplied by
smoothed weekend/workday slot ratios. A centered five-slot circular mean
(75 minutes) wraps within the daily template, and the resulting curve is
rescaled to preserve its observed weekend mean level. This preserves broad
weekend differences without copying one day's individual spikes as an expected
pattern. Detailed weekend shapes remain uncertain. `observed_mean_volume`
retains the raw reference; the generator uses the revised expected level and
normalized shape from `day_type_time_profile.csv`.

The existing shared-correlation JSON key is unchanged, but its value is
recomputed from residuals around these revised expected profiles. Shared daily
adjustment is the ratio of total observed to total expected traffic over the
same observed slots, rather than the mean of individual ratios. Adjusted
lag-1 persistence uses those same residuals. Full residual matrices and a
pooled workday residual-noise summary remain analysis outputs; this generator
continues using one shared-correlation parameter rather than a full matrix.
Exact one-week estimates are development references, not universal parameters.

---

## Reproducibility

Synthetic traffic generation is designed to be deterministic.

A fixed base seed is configured for the source. The producer derives a daily
seed from the **interval-start traffic-day date**:

```text
base seed + date of (record timestamp − configured interval)
```

The generator resets before the first interval-ending record of that traffic
day. With 15-minute intervals, Thursday's sequence runs from Thursday `00:15`
through Friday `00:00`. Thursday `23:45` and Friday `00:00` share the same seed
and continuous temporal state. The next reset is before Friday `00:15`.
All replay boundaries use `config.interval_minutes`.

This daily seed controls reproducibility. There is no separate random daily
traffic-level multiplier and no robust daily-level distribution estimated
from only five workdays. Updated profiles change generated values compared
with older methodology; identical profiles, settings and seeds remain
deterministic. Previously stored synthetic rows are not retroactively updated.

For a missing suffix, the producer reconstructs state from the traffic day's
first interval-ending timestamp and returns only the requested missing rows.
If only Friday `00:00` is missing, it replays Thursday `00:15` through Friday
`00:00`, then returns only the midnight batch. Storage still uses the physical
window `start < timestamp <= end`; no timestamp or API response fields change.

This reset correction changes generated values relative to the previous
methodology-v2 producer, which reset at calendar midnight and consumed a
different prefix. Previously stored history is not rewritten; use newly
generated history when validating the revised sequence.

This means that a particular detector and timestamp should receive the same synthetic value regardless of whether that interval was generated:

- during the initial source startup,
- during a later synchronization,
- or while recovering a gap after the source was restarted.

This behavior is important because generation should not depend on when the application happened to start.

---

## Time and Interval Semantics

Traffic observations use **15-minute intervals**.

An observation timestamp represents the **end of the traffic observation interval**.

Expected-profile day type is selected from `timestamp − interval_minutes`.
For example, a Friday `00:00` observation uses Thursday's workday profile.
The calendar-day helper remains a calendar classifier; the caller supplies
the interval-start date.

For example:

```text
Timestamp: 08:15
```

represents traffic observed during:

```text
08:00 <= traffic period < 08:15
```

For API queries, the requested `start` and `end` values describe a physical traffic window.

The storage query therefore follows:

```text
start < observation_timestamp <= end
```

For example:

```text
start = 08:00
end   = 09:00
```

returns observations timestamped:

```text
08:15
08:30
08:45
09:00
```

Both request boundaries must align with the configured interval.

---

## `storage.py`

The storage layer persists generated observations using SQLite.

The default generated database location is:

```text
data/synthetic_traffic/synthetic_traffic.db
```

The main observation table stores:

```text
site_id
detector_id
timestamp
volume
description
```

The combination of:

```text
site_id + detector_id + timestamp
```

acts as the observation's unique database key.

This prevents the same detector observation from being inserted more than once.

The database also stores source metadata such as the configured seed, scenario, interval, and timezone.

When an existing database is opened, the source checks that its stored configuration matches the active source configuration. This prevents observations generated under different configurations from being silently mixed together.

---

## Generated Database and Version Control

The SQLite database is a **generated runtime artifact**.

It is not committed to Git.

The repository `.gitignore` contains:

```gitignore
# Generated synthetic traffic database
/data/synthetic_traffic/*.db
/data/synthetic_traffic/*.db-*
```

The database can be recreated by the producer when the synthetic source starts.

Keeping it outside version control prevents binary database changes from appearing in commits and avoids treating generated data as source code.

---

## `producer.py`

The producer is responsible for keeping the stored synthetic source up to date.

It connects the generator and storage layers.

When the source starts, the producer checks the newest timestamp already stored in the database.

### Initial startup

If the database is empty, the producer generates an initial history of:

```text
7 days
```

ending at the latest completed 15-minute interval.

### Existing database

If observations already exist, the producer starts from the latest stored timestamp and generates only the missing intervals.

It does not regenerate observations that have already been stored.

### Continuous operation

After synchronization, the producer waits until the next 15-minute boundary.

At each boundary it generates any newly completed observation interval and stores the resulting detector observations.

Conceptually:

```text
08:00 ───── 08:15 ───── 08:30 ───── 08:45
               │            │            │
               ▼            ▼            ▼
            generate     generate     generate
             08:15        08:30        08:45
```

The producer uses a background thread when running with the API server.

---

## `server.py`

The server exposes the synthetic traffic source using FastAPI.

The API is intentionally a **retrieval interface**.

An HTTP GET request does not generate new traffic observations.

Generation happens independently through the background producer.

This preserves the behavior expected from a real external traffic-data provider:

```text
producer
    │
    ▼
SQLite database
    │
    ▼
HTTP API
    │
    ▼
Jaadah ingestion
```

rather than:

```text
HTTP request
    │
    ▼
generate traffic on demand
```

This distinction is important because clients should only receive traffic observations that the source currently has available.

---

## API Endpoints

### `GET /health`

Returns the current source status and the latest available observation timestamp.

Example response:

```json
{
  "status": "ok",
  "source": "synthetic",
  "latest_available_timestamp": "2026-10-14T08:30:00+03:00"
}
```

If the source contains no observations yet, `latest_available_timestamp` is `null`.

---

### `GET /detectors`

Returns the detector catalogue exposed by the synthetic source.

Example:

```json
{
  "site_id": 9,
  "count": 16,
  "detector_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
}
```

Detector discovery reads the static synthetic detector definitions and does not require the traffic generator to be constructed.

---

### `GET /observations`

Returns stored detector observations for a requested physical traffic window.

Required parameters:

```text
start
end
```

Optional parameter:

```text
detector_id
```

Multiple `detector_id` values may be supplied to filter the response.

Example request:

```text
/observations
    ?start=2026-10-14T08:00:00+03:00
    &end=2026-10-14T08:30:00+03:00
```

Example response structure:

```json
{
  "source": "synthetic",
  "scenario": "normal",
  "seed": 42,
  "interval_minutes": 15,
  "timezone": "Asia/Riyadh",
  "start": "2026-10-14T08:00:00+03:00",
  "end": "2026-10-14T08:30:00+03:00",
  "latest_available_timestamp": "2026-10-14T08:30:00+03:00",
  "observations": [
    {
      "Site ID": 9,
      "detector_id": 1,
      "Date  & Time": "2026-10-14T08:15:00+03:00",
      "volume": 51,
      "description": "SYN-EB-L1-L-STB"
    }
  ]
}
```

The API deliberately exposes an external-source-shaped representation instead of the internal Jaadah canonical traffic model.

Conversion into canonical Jaadah models is handled by the ingestion layer.

---

## Timestamp Handling

Incoming API timestamps are normalized to the configured source timezone.

The source currently uses:

```text
Asia/Riyadh
```

Timezone-aware timestamps are converted to Riyadh time.

For development convenience, timestamps supplied without timezone information are interpreted as Riyadh local time.

For example:

```text
2026-10-14T05:00:00+00:00
```

and:

```text
2026-10-14T08:00:00+03:00
```

represent the same request time after normalization.

---

## Traffic Scenarios

The synthetic generator supports configurable traffic scenarios such as lower, normal, and higher traffic conditions.

These scenario multipliers are **controlled synthetic-development settings**.

They should not be interpreted as measured Riyadh traffic classifications or official RCRC scenario definitions.

Their purpose is to make it possible to exercise the Jaadah pipeline under different demand levels during development and testing.

---

## Running the Synthetic Source

From the repository root, activate the project environment and install dependencies:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The synthetic API uses FastAPI and Uvicorn.

Start the source with:

```bash
uvicorn traffic_source.synthetic.server:app
```

For automatic reload during development:

```bash
uvicorn traffic_source.synthetic.server:app --reload
```

The FastAPI application also provides interactive API documentation at:

```text
/docs
```

once the server is running.

### Important

Normal source startup launches the background producer.

Therefore, local traffic-profile artifacts must be available under:

```text
../jaadah-private-data/processed/rcrc_sample/
```

for real synthetic generation to start successfully.

The repository intentionally does not contain those private-derived artifacts.

---

## Testing

The synthetic source has separate test suites for each major responsibility:

```text
tests/test_synthetic_traffic_generator.py
tests/test_synthetic_traffic_storage.py
tests/test_synthetic_traffic_producer.py
tests/test_synthetic_traffic_server.py
```

The tests use artificial in-memory traffic profiles and temporary SQLite databases where appropriate.

They therefore do not require the private RCRC-derived traffic profiles.

The full synthetic-source test suite can be run with:

```bash
python -m pytest -v \
  tests/test_synthetic_traffic_generator.py \
  tests/test_synthetic_traffic_storage.py \
  tests/test_synthetic_traffic_producer.py \
  tests/test_synthetic_traffic_server.py
```

The tests cover, among other behavior:

- deterministic traffic generation,
- detector generation and variation,
- database initialization,
- duplicate prevention and transaction behavior,
- retrieval-window semantics,
- seven-day initial history generation,
- recovery of missing intervals,
- reproducibility across producer restarts,
- midnight and interval-boundary behavior,
- source timezone normalization,
- API request validation,
- detector filtering,
- confirmation that API GET requests do not generate observations,
- and clean startup/shutdown of the background producer.

---

## Privacy and Repository Boundaries

The synthetic-source implementation is designed so that source code and public tests can remain in the repository without publishing restricted traffic-data artifacts.

The following are kept outside Git:

```text
Raw RCRC sample data
Derived RCRC traffic profiles
Generated synthetic SQLite databases
```

The synthetic generator consumes derived traffic characteristics locally but does not require those private files to be committed to the project repository.

This separation also means that replacing the current synthetic provider with a future authorized real-data provider can be done at the source/ingestion boundary rather than inside the SUMO simulation logic.

---

## Design Summary

The synthetic traffic source follows four main principles:

```text
Generation is independent of SUMO.
Generated observations are persisted before being served.
HTTP retrieval never generates traffic on demand.
Synthetic generation remains reproducible across runs and restarts.
```

Together, these choices provide Jaadah with a realistic stand-in for an external traffic-data provider while preserving clean boundaries between data acquisition, ingestion, demand generation, simulation, analytics, and presentation.

# Network mapping

`data/processed/road_network/network_mappings.json` is Jaadah's shared
configuration for the study area. It defines the intersection, approaches,
movements, and their links to source detectors and SUMO.

The file contains four approaches and 18 movement mappings. The canonical lane,
lane mapping, detector, and queue-detection lane collections are empty until
verified definitions are available. Traffic-count allocation belongs to demand
transformation.

## Canonical models

The classes in `jaadah/models/network.py` define the fields for Jaadah's
`Intersection`, `Approach`, `Movement`, and `ApproachLane`. The configuration
supplies the actual IDs and parent relationships.

`NetworkMappingConfig` provides three properties:

- `canonical_intersection`: an `Intersection` object.
- `canonical_approaches`: `Approach` objects keyed by approach ID.
- `canonical_movements`: `Movement` objects keyed by movement ID.

Each access creates fresh objects from the mapping records. Editing a returned
object does not edit the configuration. These objects are not saved as another
JSON section, and there is no separate canonical catalog. Canonical models do
not import mapping models or contain SUMO-specific fields.

Parent IDs belong to the declarations in this file. Validation checks that
related records agree, such as a lane and its served movements belonging to
the same approach. Creating canonical objects from these declarations does
not independently verify their geographic correctness.

## Schema and approach sides

`schema_version` identifies the JSON structure and must be `"2.0"`.
`mapping_version` is a nonempty data revision label; the current value is
`"2.0-review"`. It does not have to match the schema version.

| Field | Purpose |
| --- | --- |
| `approach_mappings` | Approach IDs, parent intersections, sides, and queue-detection lane references. |
| `movement_mappings` | Movement IDs, parent relationships, complete SUMO routes, and signal crossings. |
| `approach_lanes` | Canonical `ApproachLane` definitions. |
| `lane_mappings` | Canonical lane IDs and their SUMO lane segments. |
| `detector_mappings` | Source detector identities, optional approach/lane references, candidate movements, and mapping status. |

`approach_side` describes where the approach is located. Detector descriptions
use travel directions such as EB or WB, which have a different meaning:

| Approach | `approach_side` | Incoming travel | First signal entry edge |
| --- | --- | --- | --- |
| `APP_E` | east | WB | `713369663#2` |
| `APP_W` | west | EB | `133793906#2` |
| `APP_N` | north | SB | `569788806` |
| `APP_S` | south | NB | `569790079#0` |

Only `east`, `west`, `north`, and `south` are accepted as approach sides.
Schema 2.0 does not accept `direction` or `source_detectors` on approach records.
Detector associations belong in `detector_mappings`. Unknown fields and
unsupported schema versions are rejected.

## Lanes and detectors

`ApproachLane` describes a Jaadah lane through `lane_id`, `approach_id`,
median-based `lane_index`, `served_movement_ids`, `lane_width_m`, and optional
`storage_length_m`. Lane IDs are unique, and lane indexes are unique within
an approach. Physical attributes need reviewed values; unit-test fixtures do
not define real study-area lanes.

`LaneMapping` links a canonical `lane_id` to `sumo_lane_ids`. The SUMO IDs form
an upstream-to-downstream sequence along one lane. One segment is sufficient
when SUMO represents the lane as a single piece. Parallel lanes have separate
canonical definitions.

The actual lane-to-lane connections live in SUMO's `.net.xml`. The validator
reads them into temporary lookups and checks segment order, connectivity, and
support for the lane's served movements. The JSON does not repeat that topology.

A detector's `lane_id` is optional. A detector may instead have a movement-only,
approach-only, or unresolved association when its source layout does not identify
one canonical lane.

For a detector with `lane_id`:

- The canonical lane must exist. Its SUMO mapping may still be pending.
- A supplied approach must match the lane's owner. If omitted, ownership checks
  use the lane's approach without changing the detector record.
- Resolved candidate movements must match the lane's served movement set.

`usable` requires one candidate, `requires_allocation` requires at least two,
and `unresolved` requires none. A known lane may have an unresolved detector
association. An approach-tagged detector cannot claim an approachless movement,
such as a tunnel path.

Detector identity is `(source, site_id, detector_id)`. Multiple detectors on the
same lane do not automatically represent separate traffic contributions. Demand
transformation decides how observations are combined or allocated, including
ramp and U-turn counts. Candidate movements are not inferred from every route
that crosses a lane.

## Loading and validation

From the repository root:

```python
from jaadah.mapping.loader import load_network_mappings

config = load_network_mappings(
    "data/processed/road_network/network_mappings.json",
    network_path="data/processed/road_network/jaadah_study_area.net.xml",
)
movements = config.canonical_movements
```

The loader returns `NetworkMappingConfig`. Without `network_path`, it checks
only the JSON structure and relationships. Supplying the network path also
checks the checksum, route edges, lane connections, TLS IDs, and supplied
signal-link references. Network errors raise `ValueError`. Relative paths are
resolved from the caller's working directory.

M7 can use the one-argument loader and read detector `movement_ids` and
`mapping_status`. End-to-end M7 integration is not covered by this repository's
mapping tests.

`validate_network_mappings(config, network_path)` returns an empty list when
its checks pass, or a list of errors. It checks the mappings that are present;
it does not require every canonical lane to have a SUMO mapping.

Lane-based code can obtain a required mapping through
`require_lane_mapping(config, lane_id)` in `jaadah.mapping.validator`. It returns
the mapping or raises `ValueError` if it is missing. This checks availability;
network validation checks the referenced lanes. Operations using SUMO lanes
need both checks before processing.

Validation reads files without running SUMO or writing results. It does not
prove geographic assignments, check every upstream lane-changing possibility,
or establish that every signal crossing is listed. Queue detector placement
also requires its own review.

## Network checksums

LF (`\n`) and CRLF (`\r\n`) mark line endings. Git can change them between
Windows and Linux checkouts, giving the same network text a different raw
checksum. `network_checksum_matches` accepts the original bytes and their
LF/CRLF variants. All other bytes, including spaces and XML values, matter.

For this network, the CRLF checksum starts `08b1dc40` and the LF checksum starts
`b7fa6b5d`. Both identify the same content. Generate checksums from LF-normalized
bytes:

```python
import hashlib

checksum = hashlib.sha256(network_bytes.replace(b"\r\n", b"\n")).hexdigest()
```

A line-ending mismatch does not require editing the SUMO network or replacing
its recorded checksum.

## Tests

Run commands from the repository root with the project environment active.
In PowerShell, activate it once:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run all Python tests:

```powershell
python -m pytest
```

Run one test file:

```powershell
python -m pytest tests/test_mapping_validator.py
```

| Test file | Coverage |
| --- | --- |
| `tests/test_mappings.py` | Schema fields, canonical views, lane ownership, detector candidates/status, and pending SUMO mappings. |
| `tests/test_mapping_loader.py` | Loading, optional network checks, missing files, and invalid references. |
| `tests/test_mapping_validator.py` | Lane connections and ordering, route loops, required-mapping lookup, and checksum portability. |
| `tests/test_movement_smoke.py` | Runner preparation, mocked TraCI behavior, and direct CLI invocation. |
| `tests/test_network_mapping_integration.py` | The actual configuration/network and a reference fingerprint of all 18 movement records, including routes and signal crossings. |

The Python suite includes static network checks and mocked runner tests.
Live SUMO movement tests run separately; see
[Simulation integration](simulation_integration.md#2-movement-smoke-test)
for the command and output location.

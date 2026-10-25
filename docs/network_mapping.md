# Network mapping

`data/processed/road_network/network_mappings.json` is Jaadah's shared
configuration for the study area. It defines the intersection, approaches,
movements, and their links to source detectors and SUMO.

The file contains four approaches, 18 movement mappings, 16 canonical approach
lanes, 16 ordered SUMO lane mappings, 16 synthetic detector mappings at
site `"9"`, and movement attributes for the nine analysed movements. Queue-detection lane lists remain empty pending their separate
implementation decision.

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

## Mapping configuration structure

| Field | Purpose |
| --- | --- |
| `approach_mappings` | Approach IDs, parent intersections, sides, queue-detection lane references, and measurement-zone distances. |
| `movement_mappings` | Movement IDs, parent relationships, complete SUMO routes, and signal crossings. |
| `approach_lanes` | Canonical `ApproachLane` definitions. |
| `lane_mappings` | Canonical lane IDs and their SUMO lane segments. |
| `detector_mappings` | Source detector identities, optional approach/lane references, candidate movements, and mapping status. |
| `movement_attributes` | HCM classification (`movement_type`) and control of each movement in the KPI analysis. |

## Approach sides

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

Detector identity is `(source, site_id, detector_id)`. `DetectorMapping.site_id`
is required and must be a nonblank string, consistent with `TrafficObservation`.
Surrounding whitespace is trimmed before identity/uniqueness checks. Missing,
null, empty, and whitespace-only site IDs are rejected; there is no implicit
site default or wildcard. A configuration may still have an empty
`detector_mappings` collection.

### Exact detector locations

`DetectorMapping` optionally records `sumo_lane_id` and `sumo_position_m`.
Supply both values together or leave both absent/null. The SUMO lane ID is
trimmed and must not be blank. The position is a finite, nonnegative number
(not a boolean), measured in metres from the selected SUMO lane's start,
increasing along the direction of travel. There is no default lane or position.

The canonical `lane_id` identifies a Jaadah lane; `sumo_lane_id` selects the
specific simulator segment carrying the detector. With network validation,
the selected lane must exist, must not be an internal junction connector,
and must have a valid modeled length. Position bounds are inclusive:
`0 <= sumo_position_m <= lane_length`.

When a canonical lane mapping is available, the selected SUMO lane must belong
to its chain. It may be any segment, not necessarily the terminal segment.
When that mapping is pending, network validation still checks the explicit
SUMO lane and position, but cannot establish canonical chain membership.
Missing exact locations remain supported, including unresolved detector
mappings. Location availability does not change candidate/status rules.
These optional fields extend schema 2.0 without changing the current mapping
data revision; configurations without them remain valid.

For the 16 populated synthetic detectors, the approved modeled placement is
1 m upstream of each selected lane endpoint: `sumo_position_m = lane_length - 1`.
Detectors 1-12 use modeled signal-entry endpoints. Detectors 13-16 use selected
uncontrolled slip/bypass lane endpoints, which are not automatically physical
stop lines. These are synthetic assumptions, not surveyed RCRC locations.
This convention is specific to the synthetic baseline, not a universal
restriction or default. These records contain explicit lane IDs and positions.
Detectors 2 and 10 are shared left/through lanes with
`requires_allocation`; the other 14 are `usable`. No allocation algorithm or
split proportions are defined by these mappings.

Multiple detectors on the same lane do not automatically represent separate
traffic contributions. Demand
transformation decides how observations are combined or allocated, including
ramp and U-turn counts. Candidate movements are not inferred from every route
that crosses a lane.

## Canonical lane inventory

### Option A: local-maneuver attribution

For these 16 approach lanes, `served_movement_ids` identifies the canonical
movements representing the local maneuvers supported at this intersection.
It is not an exhaustive list of complete SUMO routes using the lane. The
assignments follow the verified lane connections, including the shared
left/straight lanes `LANE_W_2` and `LANE_E_2`.

For example, `LANE_W_3` serves `MOV_W_E`; it does not separately list
`MOV_W_E_OFFRAMP` simply because some through vehicles later exit. Likewise,
`LANE_E_3` and `LANE_E_4` serve `MOV_E_W` without adding `MOV_E_W_ONRAMP`.
An east-origin U-turn passing a west lane does not become a west-owned local
maneuver. Through-detector counts may include these route families.

This attribution does not redefine all canonical `Movement` records as local
maneuvers. All 18 established movement IDs, complete routes, and signal
crossings are preserved. M3 declares identities and associations; M7 handles
observation-to-demand transformation, and M8 handles simulation demand/route
generation. Option A does not settle allocation rules, route splits, or the
M7-M8 interpretation of `SimulationDemand.movement_id`. That contract remains
an explicit downstream decision outside the mapping component.

### Modeled width and storage provenance

All 16 lanes use the approved `lane_width_m = 3.2` as a simulation-model value,
not a surveyed physical measurement. The current `.net.xml` omits lane widths;
the inspected network/configurations contain no width override. SUMO's
[network loader](https://sumo.dlr.de/doxygen/d1/d34/_n_l_handler_8cpp_source.html#l00566)
uses the
[3.2 m default constant](https://sumo.dlr.de/doxygen/da/dbd/_std_defs_8h_source.html#l00052)
when a lane width is omitted. This provenance belongs to the approved current
network, not to all future network versions. `storage_length_m` is omitted
because verified storage values are unavailable; summed SUMO segment lengths
are not a substitute.

### Bounded lane chains and detector compatibility

The following chains run upstream to downstream. All adjacent segments have
actual SUMO connections; the terminal lane supports the listed local maneuver.
Internal connector lanes remain in the network topology, not in these lists.
Indices 1-4 count from the median, including the separate slip/bypass lanes.

The boundary rule is to begin each canonical lane where it becomes individually
identifiable as one continuous lane within the approach scope. At an upstream
merge or fan-out, the mapping starts downstream of that branching point rather
than combining incoming branches or assigning a shared feeder to multiple
independent lane identities. The chain then follows the lane toward the signal
entry or slip/bypass endpoint.

Mappings include upstream lane segments beyond the short stop-line segment so
that future queue analysis can reference the approach's upstream extent. This
does not establish a queue-measurement boundary, detector placement, or available
storage length; those require their own decisions. In particular, the east
approach's 2.27 m terminal segment alone would omit most of the approach where
queues could form. The exact bounded chains below are modeled scope choices
supported by network topology, not boundaries prescribed by the detector report.

The detector column is a compatibility reference to the previously reviewed
16 synthetic assignments at site `"9"`, supported by the Detector Mapping
Report, Sprint 1 (17 October 2026). The locally stored
`origin/feature/synthetic-traffic-source` branch at commit `8df8b3e` also
contains the 16-detector catalogue in
`traffic_source/synthetic/generator.py` (`TARGET_DETECTORS`). All 16 detector
IDs, travel directions, and median-based lane numbers agree with this
inventory. Detectors 2 and 10 use the source's `L` description for the shared
lanes; detectors 3, 11, and 12 use `T` for straight traffic.

That catalogue is not present in the current checkout and contains no SUMO
lane IDs or candidate movement sets. All 16 terminal lanes and local movement
sets match the previously reviewed report assignments, but a separate Hawra
updated table specifying those fields was not found in the inspected checkout
or locally stored branch tips. Its independent verification remains pending;
the catalogue comparison alone does not establish those fields. No branches
were fetched or switched. The populated detector records follow the approved
table, with lanes, local movements, and positions verified against the current
configuration and network. The catalogue establishes source identities
and lane numbering, not surveyed or simulator-specific positions.

| Canonical lane | Local movement IDs | Ordered SUMO lane IDs | Detector reference |
| --- | --- | --- | --- |
| `LANE_E_1` | `MOV_E_S` | `713369663#1.469_3` → `713369663#2-AddedOnRampEdge_3` → `713369663#2_3` | 9 |
| `LANE_E_2` | `MOV_E_S`, `MOV_E_W` | `713369663#1.469_2` → `713369663#2-AddedOnRampEdge_2` → `713369663#2_2` | 10 |
| `LANE_E_3` | `MOV_E_W` | `713369663#1.469_1` → `713369663#2-AddedOnRampEdge_1` → `713369663#2_1` | 11 |
| `LANE_E_4` | `MOV_E_W` | `713369663#1.469_0` → `713369663#2-AddedOnRampEdge_0` → `713369663#2_0` | 12 |
| `LANE_S_1` | `MOV_S_W` | `539502456#8_3` → `569790079#0_1` | 7 |
| `LANE_S_2` | `MOV_S_W` | `539502456#8_2` → `569790079#0_0` | 8 |
| `LANE_S_3` | `MOV_S_E_BYPASS` | `539502456#8_1` → `133973513_1` | 15 |
| `LANE_S_4` | `MOV_S_E_BYPASS` | `539502456#8_0` → `133973513_0` | 16 |
| `LANE_W_1` | `MOV_W_N` | `133793906#0-AddedOffRampEdge.26_3` → `133793906#2_2` | 1 |
| `LANE_W_2` | `MOV_W_N`, `MOV_W_E` | `133793906#0-AddedOffRampEdge.26_2` → `133793906#2_1` | 2 |
| `LANE_W_3` | `MOV_W_E` | `133793906#0-AddedOffRampEdge.26_1` → `133793906#2_0` | 3 |
| `LANE_W_4` | `MOV_W_S_SLIP` | `133793906#0-AddedOffRampEdge.26_0` → `133973488#0_0` | 13 |
| `LANE_N_1` | `MOV_N_E` | `133973525#1.51_3` → `569788806_2` | 4 |
| `LANE_N_2` | `MOV_N_E` | `133973525#1.51_2` → `569788806_1` | 5 |
| `LANE_N_3` | `MOV_N_E` | `133973525#1.51_1` → `569788806_0` | 6 |
| `LANE_N_4` | `MOV_N_W_SLIP` | `133973525#1.51_0` → `1311808806_0` | 14 |

The scope is 12 signal-entry lanes plus four slip/bypass lanes. Peripheral
ramps, U-turn paths, tunnels, and outgoing roads are not extra canonical
approach lanes. Boundaries deliberately avoid branching systems:

- East chains start downstream of the mainline/E2 merge at `J1`, rather than
  choosing one of its incoming branches. The terminal edge is only 2.27 m long;
  it alone does not describe the upstream approach or queue storage.
- W1 starts at `.26_3`, downstream of the E4 U-turn entry. Its continuation to
  `133793906#2_2` is valid, but it must not be extended backward through E4.
  Mainline vehicles can reach the lane through lateral changes on `.26`.
- North chains start at `133973525#1.51`, after the fan-out where one upstream
  lane feeds both the outer signal lane and slip feeder. South chains start
  at `539502456#8`, after the corresponding signal-lane fan-out.
- S4 begins at `539502456#8_0`, which has no incoming external connection but
  has geometry and a legal outgoing connection to `133973513_0`. It is an
  approved modeled lane beginning there, not evidence of a missing connection
  that this task should repair.
- West and north slips end at `133973488#0_0` and `1311808806_0`, respectively,
  before their receiving-road merge systems. The south bypass chains end at
  `133973513_0/1`, before the subsequent outgoing-road segments.

These are approved modeled boundaries, not independent verification of road
markings or surveyed lane formation. Queue-measurement policy and broader
lane completeness checks remain deferred. The required detector `site_id`
contract is finalized, and the 16 synthetic detector records are populated.
No model or validator redesign was needed for this population.

## Movement attributes

`movement_attributes` holds one `MovementAttributes` record (from
`jaadah/models/network.py`) for each movement in the KPI analysis. It is the
single authoritative source of movement type and control for the KPI engine,
which groups lanes and applies the HCM by these values.

### Scope

Only the nine movements served by the canonical approach lanes have
attributes. Ramps, U-turn paths, and tunnel paths stay plain movements with no
attributes and no KPIs.

| Movement | `movement_type` | `control` |
| --- | --- | --- |
| `MOV_E_W` | through | signalized |
| `MOV_E_S` | left | signalized |
| `MOV_S_W` | left | signalized |
| `MOV_W_E` | through | signalized |
| `MOV_W_N` | left | signalized |
| `MOV_N_E` | left | signalized |
| `MOV_S_E_BYPASS` | right | uncontrolled |
| `MOV_W_S_SLIP` | right | uncontrolled |
| `MOV_N_W_SLIP` | right | uncontrolled |

### Classification of `MOV_S_W`

`MOV_S_W` enters from the south and leaves to the west, a turn to the
driver's left, served by its own protected signal phase. It is therefore a
protected left turn. SUMO labels the connection `dir="s"`; that label
describes the network geometry, not the HCM classification, and the network
is not changed. The other movements have no such difference.

### Drafts and checks

The collection is optional and defaults to empty, so a file without it still
loads. A draft may give attributes to only some movements. For the attributes
present, structural validation checks that:

- no movement has attributes twice;
- each refers to a mapped movement that has an `approach_id`;
- `control` agrees with the movement's `signal_controlled` flag
  (`signalized` with `true`, `uncontrolled` with `false`);
- no approach lane serves both a signalized and an uncontrolled movement.
  Movements without attributes are left out of this check.

Completeness and the exact approved values are checked by the integration
tests, not at load time. The SUMO network validator does not compare
`movement_type` with SUMO connection directions, since these differ by design
for `MOV_S_W`; the integration tests pin the approved values instead.

## Measurement zones

Each approach mapping holds the distances of its KPI measurement zone:
`zone_upstream_m` before the stop line and `zone_downstream_m` after the
junction exit. The zone covers both parts and the path through the junction
between them. How the zones are used is described in
[KPI measurements](kpi_measurements.md).

| Approach | `zone_upstream_m` | `zone_downstream_m` |
| --- | --- | --- |
| `APP_E` | 388 | 155 |
| `APP_W` | 450 | 105 |
| `APP_N` | 500 | 65 |
| `APP_S` | 500 | 65 |

Both fields are optional, as in a draft, but are given together, and each is
a finite positive number of metres. The network validator checks every movement
served by an approach's mapped lanes:

- `zone_upstream_m` fits on the route up to the stop line, the end of the
  last SUMO lane of the movement's canonical lanes;
- `zone_downstream_m` fits on the route after the junction exit, the start of
  the next route edge.

Movements whose lanes have no SUMO mapping yet are not checked. The
integration tests pin the approved values.

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

General runtime validation checks consistency of the supplied mappings and
permits incomplete drafts. The existing integration tests enforce the approved
synthetic baseline: exactly 16 canonical lanes, 16 lane mappings, 18 movement
mappings, and 16 synthetic detectors, with the approved associations, allocation
statuses, and modeled lane-end minus 1 m detector placement. Baseline
completeness is enforced by these tests, not a mandatory runtime readiness check.

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

## Mapping versioning

### Version identifiers

`schema_version` identifies the mapping configuration's structure and validation
contract. The repository currently accepts only `"2.0"`. `mapping_version` is a
nonempty label identifying a specific revision of the study-area mapping data;
the current value is `"2.3-measurement-zones"`. The version labels do not need to match.

### Maintaining versions

These guidelines establish a new team convention, rather than describe
historical requirements. No formal semantic-versioning policy currently exists.

- Update `mapping_version` when mapping data, associations, classifications, or
  populated collections change.
- Review compatibility for optional schema additions; a `schema_version`
  increment is not automatically required.
- For breaking schema changes, coordinate a `schema_version` update with the
  affected models, loaders, validators, tests, and consumers.
- Documentation-only changes require no version update.

For each change, review its effect on the schema contract and mapping data
separately. Update the relevant version values in `network_mappings.json`,
adjust affected code and tests (including assertions of specific version labels),
and update this documentation to reflect the accepted schema and current data
revision. Run the relevant validation and tests together before accepting the
change.

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
| `tests/test_mappings.py` | Schema fields, canonical views, lane ownership, detector candidates/status, pending SUMO mappings, movement attribute checks, including drafts, and measurement-zone distances. |
| `tests/test_mapping_loader.py` | Loading, optional network checks, missing files, and invalid references. |
| `tests/test_mapping_validator.py` | Lane connections and ordering, route loops, required-mapping lookup, checksum portability, and measurement zones fitting their routes. |
| `tests/test_movement_smoke.py` | Runner preparation, mocked TraCI behavior, and direct CLI invocation. |
| `tests/test_network_mapping_integration.py` | Exact approved lane, lane-mapping, movement, and synthetic detector inventories; associations, allocation statuses, and modeled placement; actual network validation and a fingerprint of all 18 movement records, including routes and signal crossings; the exact approved movement attributes for the nine lane-served movements; the approved measurement zones. |

The Python suite includes static network checks and mocked runner tests.
Live SUMO movement tests run separately; see
[Simulation integration](simulation_integration.md#2-movement-smoke-test)
for the command and output location.

# Simulation integration

## SUMO Simulation Runner

`simulation/scripts/run_simulation.py` starts one SUMO child process, connects
through TraCI, steps continuously from second zero to a bounded deadline, and
closes/reaps its own process. It calls `sumo_config_validator.py` to validate
execution settings, inspect referenced files, protect existing outputs, and
check baseline conflicts before launch. It does not plan demand or calculate
measurements. Two short SUMO inspection commands export option metadata and the
effective configuration to stdout; neither runs a simulation.
The network, routes and baseline signal program are loaded from the supplied
SUMO configuration without editing them.

From the repository root, using the project Python environment:

```bash
python simulation/scripts/run_simulation.py
python simulation/scripts/run_simulation.py --config simulation/configs/tests/stress_test.sumocfg --seed 42 --step-length 0.4 --end-time 600
python simulation/scripts/run_simulation.py --verbose
```

| Parameter | Meaning |
| --- | --- |
| `--config` | Existing `.sumocfg`; default is `simulation/configs/tests/smoke_test.sumocfg`. Relative input paths remain relative to that config. |
| `--sumo-bin` | Executable name or path; default `sumo`. |
| `--end-time` | Absolute simulation end in seconds from warm-up start; otherwise the config's finite positive `time/end` is required. |
| `--seed` | Explicit seed; otherwise config seed, otherwise SUMO's deterministic default 23423. |
| `--step-length` | Simulation step in seconds; otherwise config step, otherwise SUMO's default 1 s. |
| `--verbose` | Print active vehicle IDs, speeds and XY positions each step. |
| `--allow-overwrite` | Explicitly permit replacement of existing output files. Input/config collisions remain forbidden. Default: off. |

Explicit end/seed/step values override configuration values. The runner forces
begin=0, deterministic random mode, and one TraCI client. Seeds must be integers
from 0 to 2147483647. End/step must be finite and positive; steps use whole
milliseconds, and end must be an exact multiple of step. Invalid values fail
before SUMO starts, rather than silently overshooting the deadline.

Preflight uses the installed SUMO's `--save-template stdout` metadata and
`--save-configuration stdout` to discover configured file options, aliases and
resolved paths with the runner's overrides applied. Output/log destinations and
referenced XML `file`/`dest`/`output` declarations are checked before launching
the simulation. Includes and gzip route/additional files are inspected too.
Inspection XML is parsed directly from bytes so its declared encoding is
respected, including UTF-8 filenames on Windows. Diagnostic stderr is decoded
as UTF-8 with replacement for invalid bytes.

Existing destinations are rejected unless `--allow-overwrite` is supplied;
collisions with the config or input files are always rejected, including aliases
to the same existing file. `${VARIABLE}` references in filenames, output prefixes
and suffixes are expanded before collision checks; undefined variables are
rejected. Output prefix/suffix placement follows SUMO's rules. `TIME` in prefixes
and suffixes, `${LOCALTIME}`, `${UTC}`, `${PID}`, and supported generated filename
families are checked conservatively against matching existing files.
Inspection failures stop startup. Export directives such as `save-schema` in an
execution config are rejected so inspection cannot write those files itself.

The baseline checks reject nonzero `lanechange.duration` and explicit
`lcSpeedGain` values other than 1 in referenced vehicle-type XML. The latter is
a vehicle-type attribute, not a SUMO command-line option. Default-valued settings
and unrelated vehicle attributes remain valid. This is a narrow baseline check,
not SUMO Demand Generation's demand/route validation. Files are read without
modifying them.

The no-argument/config/verbose commands are supported. The smoke config runs to
its 300 s deadline even if all vehicles finish sooner. Empty-network periods do
not stop the simulation.
Vehicles still present at the deadline do not extend the run. There are no
restarts at 15-minute boundaries. `completed` means the execution reached its
deadline and shut down successfully; it does not mean all vehicles finished or
that measurements passed validation.

Python callers use `run_simulation(config_path=DEFAULT_CONFIG, verbose=False, *,
sumo_bin="sumo", end_time_s=None, seed=None, step_length_s=None,
shutdown_timeout_s=5.0, allow_overwrite=False)`.
It returns a dictionary
with `status` (`completed`/`failed`), `final_time_s`, `steps`,
`remaining_expected_vehicles`, `error`, `cleanup_errors`, and observed SUMO/TraCI
API versions. Resolved end/seed/step settings are included after input validation.
Simulation time and remaining-vehicle count are the last successful observations
and are null until available; `steps` starts at zero. This is a local execution
result, not a canonical `SimulationRun` record.

Missing executables/configs, rejected SUMO input, connection errors, early process
exit, step failures and interruption produce failed summaries. CLI exit codes are
0 for success, 1 for failure, and 130 for interruption during execution. SUMO
stdout/stderr remain visible for diagnostics. Connection attempts are limited
to 21 attempts with 0.1 s retry spacing. Ordinary TraCI commands use the existing
library's blocking socket behavior; this is not a general runtime-hang watchdog.
Use the runner for supervised execution. A startup/runtime timeout
policy remains future work before unattended backend execution.

Cleanup closes TraCI without its unbounded process wait, then waits up to the
shutdown timeout for the owned child. A blocked close is interrupted by killing
that child. A child that remains alive is terminated, then killed if needed,
with bounded waits. Cleanup failures remain separate from the original error
and also mark the run failed. No process-name searches or unrelated-process
termination are used.
An interruption during the post-terminate wait is recorded and still triggers
the final kill/reap attempt. Errors from that last attempt are reported too.

## Scenario Execution with Generated Demand

The `jaadah/sumo_demand/` package owns `build_run_window`, departure
planning, route writing, manifests/fingerprints and
`check_generated_demand(..., window=..., seed=...)`. The Core Simulation Runner
does not duplicate them. `simulation/scripts/run_scenario.py` connects a
canonical scenario and pending run to demand files already produced by
`write_sumo_demand()`:

```python
from simulation.scripts.run_scenario import execute_scenario

result = execute_scenario(
    scenario, simulation_config, pending_run, generated_demand,
    mapping_path="data/processed/road_network/network_mappings.json",
    network_path="data/processed/road_network/jaadah_study_area.net.xml",
    run_dir="simulation/outputs/baseline_run",
)
```

`generated_demand` is the `GeneratedDemand` returned by the writer. The adapter
accepts baseline scenarios only; intervention scenarios require a future
signal-control configuration and are rejected before execution. It loads and
validates the mapping/network, derives the window, validates the
generated folder for that window and run seed, and verifies its files still match
the writer's fingerprints. Full network, route, and run-configuration paths
containing `${...}` or commas are rejected because SUMO could interpret them as
different inputs. It then creates a fresh run directory containing a
`scenario.sumocfg` with that network, route file and raw-output settings. It calls
`run_simulation()` once with `RunWindow.duration_s`, `SimulationRun.random_seed`,
and `SimulationRun.step_length_s`. Validation errors raise before SUMO starts;
runtime failures remain in the runner's execution summary. The adapter does not
reuse an existing run directory or edit generated demand files. The manifest's
vehicle ID to demand ID link supplies movement identity; vehicle IDs are not
parsed to infer movements.

To start from canonical `SimulationDemand` records, call
`generate_and_execute_scenario(scenario, simulation_config, pending_run, demands,
mapping_path=..., network_path=..., demand_dir=..., run_dir=...)`. Supply one
record per demand movement and 15-minute interval across the entire run window.
It plans departures, writes the three demand files into a new directory, and
passes the returned `GeneratedDemand` to `execute_scenario()`. The result has
`generated_demand` and `scenario_execution` entries. Keep the demand directory
and its returned artifact reference for another permitted run; call
`execute_scenario()` with that reference to reuse the same files without
regenerating them. Demand and run directories must be fresh and separate.
Generated files remain available if SUMO execution fails. Intervention execution
is still unsupported.

The agreed window is warm-up + scenario analysis + clearance. Second zero is
analysis start minus warm-up. With 900 s warm-up, 3600 s analysis and 900 s
clearance, the adapter passes 5400 s. These durations come from the scenario and
configuration. The result includes `window_epoch`, analysis boundaries, the
configuration and route paths, the execution summary, and provenance. Scenario
timestamps derive from the window epoch, separately from wall-clock execution
timestamps. Neither the adapter nor the runner persists a `SimulationRun`.

The result carries `mapping_version` from the mapping configuration and
`demand_sha256`/`route_file_sha256` from `GeneratedDemand`. The canonical
`SimulationRun` model requires these fields for running and completed records;
the adapter does not create or persist those records. Future baseline
and intervention comparisons must reuse the same generated demand and route
files. Intervention execution, comparison orchestration, and canonical run-state
persistence remain future work.

Use the authoritative study-area network and its existing 120 s baseline signal
cycle. The runner adds no lane-change tuning. Avoid using the visualization
`simulation/configs/tests/stress_test_v2.sumocfg` and
`simulation/scene_3d/build_all.py` settings as a demand-generation baseline: they
set a 2 s lane-change duration. Existing smoke/stress configs are validation
assets, not final generated demand.

## Baseline Run from the Synthetic Source

`simulation/scripts/run_baseline.py` runs one baseline scenario end to end:
synthetic source → ingestion → demand transformation →
`generate_and_execute_scenario()`. It stops at the raw SUMO outputs; KPIs are
calculated from them afterwards.

From the repository root, start the source in one terminal and run the
baseline in another:

```bash
uvicorn traffic_source.synthetic.server:app
python simulation/scripts/run_baseline.py --analysis-start 2026-10-27T08:00+03:00 --analysis-end 2026-10-27T09:00+03:00
```

| Parameter | Meaning |
| --- | --- |
| `--analysis-start`, `--analysis-end` | Required. Analysis period in Riyadh time (`+03:00`). |
| `--source-url` | Synthetic source; default `http://127.0.0.1:8000`. |
| `--seed`, `--step-length` | Default 42 and 0.4 s. |
| `--run-id` | Default `RUN_BASELINE_<date>T<start>-<end>_S<seed>`, e.g. `RUN_BASELINE_20261027T0800-0900_S42`. |
| `--out` | Fresh output folder; default `simulation/outputs/baseline_runs/<run-id>/`. |
| `--mapping`, `--net`, `--sumo-bin` | Default to the study-area mapping, network and `sumo`. |

The run window is the analysis period plus 900 s warm-up and 900 s clearance:
07:45–09:15 for an 08:00–09:00 analysis, one continuous 5400 s SUMO run. The
script first checks that SUMO can be run, then:

1. reads `latest_available_timestamp` from the source's `/health`, and stops
   unless it is at or after the end of the run window (records are labelled by
   interval end, so 09:15 means 09:00–09:15 is stored);
2. ingests the observations of the run window, and stops if any record is
   rejected;
3. builds `SimulationDemand` for the run window, and stops if any movement or
   interval cannot be built;
4. creates a historical baseline `Scenario` and a pending `SimulationRun`, then
   calls `generate_and_execute_scenario()`.

Every stop lists all the problems found. Nothing is written before step 4, so a
run that stops early leaves no route file. If step 4 stops before SUMO runs (for
example, the generated demand fails its check), the files already written are
kept for diagnosis and the message names their folder. Exit codes: 0 completed, 1 SUMO run
failed, 2 the run did not start (including an existing output folder or an
unreachable source).

The output folder contains `demand/` (route file, manifest and demand records),
`run/` (`scenario.sumocfg`, `tls_states.add.xml` and `raw/fcd.xml`,
`raw/tripinfo.xml`, `raw/tls_states.xml`) and
`summary.json`. The summary holds the run window, source timestamp, record
counts, demand file paths and fingerprints, raw outputs, the execution summary,
and the `SimulationRun` record after the run (`completed` or `failed`, with
`started_at`, `mapping_version`, `demand_sha256` and `route_file_sha256`). The
record is saved only in `summary.json`; it is not persisted elsewhere.
`started_at` is the start of step 4, so it includes demand generation as well as
the SUMO run.

Known limits:

- Step 1 shows that the source has reached the end of the window, not that it
  holds data that far back. On its first start the source fills only the 7 days
  before it; an older window is reported in step 3 as missing observations.
- The source needs the private profile files in
  `../jaadah-private-data/processed/rcrc_sample/` (see
  `synthetic_traffic_source.md`).
- `raw/fcd.xml` is large: about 1.1 GB for a 5400 s run with 100 vehicles per
  detector per interval. `simulation/outputs/baseline*/` is ignored by Git.

## Simulation Output Processing Integration

Each fresh run directory contains `raw/fcd.xml`, `raw/tripinfo.xml` and
`raw/tls_states.xml` beside `scenario.sumocfg` and `tls_states.add.xml`. All
outputs are written with 3 decimals (`--precision 3`).

FCD is written at every simulation step, so its spacing is
`SimulationRun.step_length_s`; there is no separate FCD sampling period. Each
row has `id`, `x`, `y`, `angle`, `type`, `speed`, `lane`, `pos`, `odometer` and
`signals`:

| Field | Meaning | Used by |
| --- | --- | --- |
| `x`, `y` | WGS84 longitude and latitude (`--fcd-output.geo true`) | 3D playback |
| `angle` | Heading, 0° = north, clockwise | 3D playback |
| `lane`, `pos` | SUMO lane and distance along it | KPI measurements |
| `odometer` | Distance driven since insertion | KPI measurements |
| `speed` | Speed in m/s | KPI measurements |
| `signals` | SUMO signal bitset (indicators, brake lights) | 3D playback |

FCD has no `edge` field; the edge is derived from the lane and network.

`tls_states.add.xml` declares one `SaveTLSSwitchStates` event, so SUMO writes a
`<tlsState>` line to `raw/tls_states.xml` each time a traffic light switches,
with the time, program, phase and signal state string. A 5400 s run with the
120 s cycle gives about 540 lines.
TripInfo records actual departures, arrivals and departure delays, including
vehicles unfinished or waiting to depart at the deadline. The retained demand
manifest supplies planned departures and vehicle identities for reconciliation.
Whole-trip waiting time and time loss are not measurement-zone delay records.

`execute_scenario()` returns a `raw_outputs` entry (`fcd`, `tripinfo`,
`tls_states`) for each file with its
configured absolute `path`, whether the file `exists`, and whether it is
`potentially_partial` because execution failed. Files are retained after a
failure. Even a present file from a completed execution has not yet been parsed
or validated as a canonical measurement.

Simulation Output Processing will parse/reduce these files into canonical states
and measurement records. E2 queue detectors, their geometry and output files are
deferred; their exact contract must be agreed with output processing.

The Core Simulation Runner has no observers/callbacks, FCD/E2 parsers, zone
geometry, canonical conversion or KPI calculations. Existing config output
directives still apply subject to preflight.
Preflight is a check, not an atomic reservation: do not run concurrent writers
to the same destinations or change input/config files between inspection and
execution. Device-generated filenames not explicitly declared in configuration
or XML require further output-contract work before unattended execution.

Real detector points, canonical lane chains, KPI zones and full network boundaries
are distinct. Their distances/identities do not belong in this runner.
With a 0.4 s simulation step, FCD is sampled every 0.4 s; other step lengths
produce their own spacing. A 1 s step cannot supply genuine 0.4 s samples.
Zone entry determines measurement eligibility; Simulation
Output Processing must account explicitly for eligible vehicles unfinished at
the clearance deadline.

## Verification

```bash
python -m pytest tests/test_simulation_runner.py tests/test_movement_smoke.py
```

Runner tests mock the process and TraCI connection. Live acceptance should use
the authoritative network and existing smoke/stress inputs, explicit seed/step/end,
and the intended installed TraCI package. Check the reported server/API version
and imported `traci.__file__`; `SUMO_HOME`/`PYTHONPATH` can select a different
client than the project's pinned package.

Run `python -m pytest tests/test_scenario_execution.py` for the adapter's
scenario, window, artifact, provenance, and no-launch-on-invalid-input checks.

Run `python -m pytest tests/test_baseline_run.py` for the baseline run from an
in-process synthetic source with artificial profiles: it stops when SUMO cannot
be run, the source is behind or a detector is missing, keeps the files of a
failed demand check, and a 15-minute analysis reaches the raw SUMO outputs
(skipped when SUMO is not installed).

Live acceptance should cover execution through empty periods to the deadline,
stopping with vehicles still expected, repeatability with a fixed seed, and
preservation of the 120 s baseline signal cycle. Check output protection using
temporary files, including non-ASCII filenames and environment-variable prefixes
and suffixes. These checks verify the runner; end-to-end demand generation and
output processing require separate integration tests.

The separate `simulation/scripts/tests/run_movement_smoke.py` remains a route
validation utility for all 18 movements. It checks departure, arrival, teleports
and deadlines in isolated simulations; its stop-on-clear behavior is intentional
for those tests. Use `--out` with a fresh directory to preserve previous results.

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

## SUMO Demand Generation Integration

The `jaadah/sumo_demand/` package owns `build_run_window`, departure
planning, route writing, manifests/fingerprints and
`check_generated_demand(..., window=..., seed=...)`. Those utilities are not
imported or duplicated by the Core Simulation Runner. Direct integration is
planned through a separate run adapter.

The adapter must validate generated demand files before starting SUMO, provide
the exact generated routes and authoritative network, and pass
`SimulationRun.random_seed` and `step_length_s`. It must prevent extra input files or conflicting settings
from an unrelated config. Manifest vehicle ID -> demand ID -> movement is the
identity lookup; generated vehicle IDs must not be parsed for movement identity.

The agreed window is warm-up + scenario analysis + clearance. Second zero is
analysis start minus warm-up. With 900 s warm-up, 3600 s analysis and 900 s
clearance, the adapter passes 5400 s. These durations belong to the existing
configuration/window utilities, not hardcoded runner logic. Scenario timestamps
derive from the window epoch, separately from wall-clock execution timestamps.
The generic runner does not yet load scenarios, update run models, validate
mapping/network provenance or persist fingerprints.

The planned run adapter must also carry `mapping_version` from the mapping
configuration and `demand_sha256`/`route_file_sha256` from the
`write_sumo_demand()` result. The provenance contract requires these on running
and completed `SimulationRun` records. A baseline and
intervention comparison must reuse the same generated demand and route files;
the KPI Engine is expected to verify their matching fingerprints. Persisting
these fields and enforcing the comparison checks remain planned model and
orchestration work; the runner does not implement them.

Use the authoritative study-area network and its existing 120 s baseline signal
cycle. The runner adds no lane-change tuning. Avoid using the visualization
`simulation/configs/tests/stress_test_v2.sumocfg` and
`simulation/scene_3d/build_all.py` settings as a demand-generation baseline: they
set a 2 s lane-change duration. Existing smoke/stress configs are validation
assets, not final generated demand.

## Simulation Output Processing Integration

SUMO Simulation Execution will configure raw output files; Simulation Output
Processing will parse/reduce them into canonical states and measurement records.
Expected sources include FCD trajectories, E2
queue output, and additional agreed outputs for insertion delay, arrivals and
unfinished vehicles. Exact filenames, fields, sampling, detector geometry,
failure handling and storage remain to be agreed between these components.

The Core Simulation Runner has no observers/callbacks, FCD/E2 parsers, final output
configuration, zone geometry, canonical conversion or KPI calculations. Existing
config output directives still apply subject to preflight. No permanent output
layout is added.
Preflight is a check, not an atomic reservation: do not run concurrent writers
to the same destinations or change input/config files between inspection and
execution. Device-generated filenames not explicitly declared in configuration
or XML require further output-contract work before unattended execution.

Real detector points, canonical lane chains, KPI zones and full network boundaries
are distinct. Their distances/identities do not belong in this runner. Later
0.4 s FCD sampling is separate from the simulation step: compatible examples are
0.4 s steps or 0.2 s steps with output every second step. A 1 s step cannot supply
genuine 0.4 s samples. Zone entry determines measurement eligibility; Simulation
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

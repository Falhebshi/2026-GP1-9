# Simulation Integration

This document describes the integration between Jaadah and the SUMO microscopic traffic simulation. It will be updated as the simulation pipeline is developed.

## 1. SUMO / TraCI Runner

The SUMO/TraCI runner is implemented in:

`simulation/scripts/run_simulation.py`

Its purpose is to allow Jaadah to launch and interact with SUMO programmatically through TraCI.

### Current Capabilities

The runner can:

- Start SUMO using a `.sumocfg` file.
- Establish a TraCI connection.
- Advance the simulation step by step.
- Read active vehicle IDs, speeds, and SUMO XY positions.
- Optionally print individual vehicle states using `--verbose`.
- Run different SUMO configurations using `--config`.
- Allow remaining vehicles and queues to clear before ending a finite validation run.
- Close the TraCI connection cleanly.

### Usage

Run the default smoke test:

```bash
python simulation/scripts/run_simulation.py
```

Run the stress test:

```bash
python simulation/scripts/run_simulation.py \
  --config simulation/configs/tests/stress_test.sumocfg
```

Print individual vehicle states:

```bash
python simulation/scripts/run_simulation.py --verbose
```

### Test Results

The runner was tested with both test scenarios provided with the finalized SUMO network.

| Scenario | Vehicles Processed | Maximum Active | Final Simulation Time |
|---|---:|---:|---:|
| Smoke test | 7 | 5 | 128 s |
| Stress test | 349 | 73 | 472 s |

Both simulations completed successfully with no vehicles remaining.

### Current Stopping Behavior

For the current finite test scenarios, the runner continues stepping while SUMO reports vehicles that are either active or still expected to enter.

This means the simulation does not stop as soon as the last vehicle enters. Vehicles already in the network are allowed to complete their routes, allowing remaining queues to clear before the simulation ends.

This behavior is specific to finite validation runs. Jaadah's continuous historical reconstruction will preserve the simulation state between consecutive traffic intervals so that vehicles and queues can persist across interval boundaries.

## 2. Movement Smoke Test

The movement smoke-test runner is implemented in:

`simulation/scripts/tests/run_movement_smoke.py`

Its purpose is to verify that a vehicle can complete each of the 18 mapped movement routes in SUMO.

### Current Capabilities

The runner can:

- Load and validate the mappings against the SUMO network.
- Test each movement with one vehicle in a separate simulation.
- Check departure, arrival, teleportation, and simulation errors.
- Save per-movement logs and an overall summary.

A movement passes when the vehicle departs and arrives within the time limit without teleportation or errors.

### Usage

Run the movement smoke test from the project root:

```bash
python simulation/scripts/tests/run_movement_smoke.py
```

Results are stored under `simulation/outputs/tests/movement_smoke/`. Use `--out` with a new directory to preserve earlier results. Run the script with `--help` to see its options.

### Test Results

Unit tests cover the runner using mocked TraCI. Live SUMO movement tests are run separately.

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import threading

from sumolib.miscutils import getFreeSocketPort
import traci

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.scripts.sumo_config_validator import (
    build_sumo_command,
    prepare_execution,
    preflight_configuration,
)


DEFAULT_CONFIG = PROJECT_ROOT / "simulation/configs/tests/smoke_test.sumocfg"


def print_vehicle_states(connection, simulation_time: float) -> None:
    """Print raw diagnostic state, without creating canonical output records."""
    for vehicle_id in connection.vehicle.getIDList():
        print(
            f"time={simulation_time:.1f}s | vehicle={vehicle_id} | "
            f"speed={connection.vehicle.getSpeed(vehicle_id):.2f} m/s | "
            f"position={connection.vehicle.getPosition(vehicle_id)}"
        )


def _close_traci(connection, process, timeout_s, errors):
    # Killing our child releases a TraCI close blocked on its socket.
    def abort_close():
        errors.append("TraCI shutdown timed out")
        try:
            if process.poll() is None:
                process.kill()
        except OSError as exc:
            errors.append(f"SUMO kill failed: {exc}")

    timer = threading.Timer(timeout_s, abort_close)
    timer.daemon = True
    timer.start()
    try:
        connection.close(wait=False)
    except (Exception, KeyboardInterrupt) as exc:
        errors.append(f"TraCI close failed: {type(exc).__name__}: {exc}")
    finally:
        timer.cancel()
        timer.join()


def _reap_owned_process(process, timeout_s, errors):
    try:
        process.wait(timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt) as exc:
        errors.append(f"SUMO wait failed: {type(exc).__name__}: {exc}")
    else:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        errors.append(f"SUMO termination wait failed: {type(exc).__name__}: {exc}")
    else:
        return
    try:
        process.kill()
        process.wait(timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        errors.append(f"SUMO final kill/reap failed: {type(exc).__name__}: {exc}")


def _shutdown(connection, process, timeout_s):
    """Close TraCI and reap only the SUMO process started by this runner."""
    errors = []
    if process is None:
        return errors
    if connection is not None:
        _close_traci(connection, process, timeout_s, errors)
    _reap_owned_process(process, timeout_s, errors)
    return errors


def run_simulation(
    config_path: Path = DEFAULT_CONFIG,
    verbose: bool = False,
    *,
    sumo_bin: str = "sumo",
    end_time_s: float | None = None,
    seed: int | None = None,
    step_length_s: float | None = None,
    shutdown_timeout_s: float = 5.0,
    allow_overwrite: bool = False,
) -> dict:
    """Return a summary; failures and interruption are reported as failed.

    Explicit parameters override the config. Time always starts at zero.
    No M8 generation/validation or M10 output processing occurs here.
    """
    summary = {
        "status": "failed", "final_time_s": None, "steps": 0,
        "remaining_expected_vehicles": None, "error": None,
        "cleanup_errors": [], "sumo_version": None, "traci_api_version": None,
    }
    process = connection = None
    try:
        if isinstance(shutdown_timeout_s, bool) or not math.isfinite(shutdown_timeout_s) or shutdown_timeout_s <= 0:
            raise ValueError("shutdown_timeout_s must be finite and positive")
        prepared = prepare_execution(
            config_path, sumo_bin=sumo_bin, end_time_s=end_time_s,
            seed=seed, step_length_s=step_length_s,
            allow_overwrite=allow_overwrite,
        )
        command = prepared["command"]
        simulation_step_s = prepared["step_length_s"]
        summary.update(
            end_time_s=prepared["end_time_s"],
            step_length_s=simulation_step_s,
            seed=prepared["seed"],
        )
        preflight_configuration(command, allow_overwrite=allow_overwrite)
        port = getFreeSocketPort()
        if not port:
            raise RuntimeError("No free local TraCI port available")
        process = subprocess.Popen(command + ["--remote-port", str(port)])
        connection = traci.connect(
            port=port, host="127.0.0.1", proc=process,
            numRetries=20, waitBetweenRetries=0.1,
        )
        api, version = connection.getVersion()
        summary.update(traci_api_version=api, sumo_version=version)
        summary["final_time_s"] = connection.simulation.getTime()
        summary["remaining_expected_vehicles"] = connection.simulation.getMinExpectedNumber()
        if summary["final_time_s"] != 0 or not math.isclose(connection.simulation.getDeltaT(), simulation_step_s, rel_tol=0, abs_tol=1e-9):
            raise RuntimeError("SUMO did not apply the requested begin/step settings")

        for index in range(1, prepared["total_steps"] + 1):
            if process.poll() is not None:
                raise RuntimeError(f"SUMO exited unexpectedly (code {process.returncode})")
            connection.simulationStep()
            summary["steps"] += 1
            summary["final_time_s"] = connection.simulation.getTime()
            summary["remaining_expected_vehicles"] = connection.simulation.getMinExpectedNumber()
            if not math.isclose(summary["final_time_s"], index * simulation_step_s, rel_tol=0, abs_tol=1e-7):
                raise RuntimeError("SUMO time differs from the requested step grid")
            if verbose:
                print_vehicle_states(connection, summary["final_time_s"])
        summary["status"] = "completed"
    except (Exception, KeyboardInterrupt) as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        summary["cleanup_errors"] = _shutdown(connection, process, shutdown_timeout_s)
        if process is not None and process.returncode not in (None, 0):
            summary["cleanup_errors"].append(f"SUMO exit code: {process.returncode}")
        if summary["cleanup_errors"]:
            summary["status"] = "failed"
            summary["error"] = summary["error"] or summary["cleanup_errors"][0]
    return summary


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one continuous, time-bounded SUMO simulation.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--verbose", action="store_true", help="Print raw vehicle states each step.")
    parser.add_argument("--sumo-bin", default="sumo", help="SUMO executable name or path.")
    parser.add_argument("--end-time", type=float, dest="end_time_s", help="End in seconds from warm-up start; otherwise config end.")
    parser.add_argument("--seed", type=int, help="Override config seed (SUMO default: 23423).")
    parser.add_argument("--step-length", type=float, dest="step_length_s", help="Override config step length (SUMO default: 1 s).")
    parser.add_argument("--allow-overwrite", action="store_true", help="Allow replacing existing outputs; input collisions remain forbidden.")
    return parser.parse_args(argv)


def main() -> int:
    arguments = vars(parse_args())
    arguments["config_path"] = arguments.pop("config")
    summary = run_simulation(**arguments)
    print(json.dumps(summary, indent=2))
    if summary["error"] and summary["error"].startswith("KeyboardInterrupt:"):
        return 130
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

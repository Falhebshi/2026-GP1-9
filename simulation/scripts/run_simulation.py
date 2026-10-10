import argparse
from pathlib import Path

import traci


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "simulation"
    / "configs"
    / "tests"
    / "smoke_test.sumocfg"
)


def print_vehicle_states(simulation_time: float) -> None:
    """Print the current state of every active vehicle."""

    for vehicle_id in traci.vehicle.getIDList():
        speed = traci.vehicle.getSpeed(vehicle_id)
        position = traci.vehicle.getPosition(vehicle_id)

        print(
            f"time={simulation_time:.1f}s | "
            f"vehicle={vehicle_id} | "
            f"speed={speed:.2f} m/s | "
            f"position={position}"
        )


def run_simulation(
    config_path: Path = DEFAULT_CONFIG,
    verbose: bool = False,
) -> None:
    """Run a finite SUMO simulation through TraCI until all traffic clears."""

    config_path = Path(config_path).expanduser().resolve()

    if not config_path.is_file():
        raise FileNotFoundError(
            f"SUMO configuration file not found: {config_path}"
        )

    sumo_command = [
        "sumo",
        "-c",
        str(config_path),
    ]

    print(f"Starting SUMO with: {config_path.name}")

    traci.start(sumo_command)

    steps = 0
    max_active_vehicles = 0

    try:
        # Continue until no vehicles are expected to enter or remain
        # in the simulation.
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            steps += 1

            simulation_time = traci.simulation.getTime()
            active_vehicle_count = len(traci.vehicle.getIDList())

            max_active_vehicles = max(
                max_active_vehicles,
                active_vehicle_count,
            )

            if verbose:
                print_vehicle_states(simulation_time)

        final_time = traci.simulation.getTime()
        vehicles_remaining = traci.simulation.getMinExpectedNumber()

        print("\nSimulation completed successfully.")
        print(f"Final simulation time: {final_time:.1f} s")
        print(f"Steps executed: {steps}")
        print(f"Maximum active vehicles: {max_active_vehicles}")
        print(f"Vehicles remaining: {vehicles_remaining}")

    finally:
        traci.close()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Run a finite SUMO simulation through TraCI."
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to the SUMO .sumocfg file.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Print the state of every active vehicle "
            "at every simulation step."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run the command-line simulation."""

    args = parse_args()

    run_simulation(
        config_path=args.config,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
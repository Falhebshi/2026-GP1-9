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


def print_vehicle_states(simulation_time):
    """Print basic live state for every vehicle currently in SUMO."""

    vehicle_ids = traci.vehicle.getIDList()

    for vehicle_id in vehicle_ids:
        speed = traci.vehicle.getSpeed(vehicle_id)
        position = traci.vehicle.getPosition(vehicle_id)

        print(
            f"time={simulation_time:.1f}s | "
            f"vehicle={vehicle_id} | "
            f"speed={speed:.2f} m/s | "
            f"position={position}"
        )


def run_simulation(config_path=DEFAULT_CONFIG, verbose=False):
    """Run a finite SUMO simulation through TraCI until all traffic clears."""

    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"SUMO config not found: {config_path}")

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
        # For finite validation scenarios, continue until:
        # 1. no more vehicles are scheduled to enter, and
        # 2. all vehicles already in the network have reached their destinations.
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            steps += 1

            simulation_time = traci.simulation.getTime()
            vehicle_ids = traci.vehicle.getIDList()

            max_active_vehicles = max(
                max_active_vehicles,
                len(vehicle_ids),
            )

            if verbose:
                print_vehicle_states(simulation_time)

        final_time = traci.simulation.getTime()

        print("\nSimulation completed successfully.")
        print(f"Final simulation time: {final_time:.1f} s")
        print(f"Steps executed: {steps}")
        print(f"Maximum active vehicles: {max_active_vehicles}")
        print(
            "Vehicles remaining: "
            f"{traci.simulation.getMinExpectedNumber()}"
        )

    finally:
        traci.close()


if __name__ == "__main__":
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
        help="Print live state for every active vehicle at every simulation step.",
    )

    args = parser.parse_args()

    run_simulation(
        config_path=args.config,
        verbose=args.verbose,
    )
import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from jaadah.models.outputs import (
    VehicleState,
    VehicleType,
)
from jaadah.models.traffic import SimulationDemand


def load_vehicle_movements(
    manifest_path: str | Path,
    demand_path: str | Path,
) -> dict[str, str]:
    """
    Return the movement of every planned vehicle, keyed by vehicle ID,
    from the manifest and demand file written by the SUMO demand
    generation.
    """

    with Path(demand_path).open(
        "r",
        encoding="utf-8",
    ) as file:
        demands = [
            SimulationDemand.model_validate(record)
            for record in json.load(file)
        ]

    with Path(manifest_path).open(
        "r",
        encoding="utf-8",
    ) as file:
        departures = json.load(file)["departures"]

    movement_of_demand = {
        demand.demand_id: demand.movement_id
        for demand in demands
    }
    vehicle_movements: dict[str, str] = {}

    for departure in departures:
        demand_id = departure["demand_id"]

        if demand_id not in movement_of_demand:
            raise ValueError(
                f"vehicle {departure['vehicle_id']} has unknown "
                f"demand_id {demand_id}"
            )

        vehicle_movements[departure["vehicle_id"]] = (
            movement_of_demand[demand_id]
        )

    return vehicle_movements


def edge_of_lane(
    lane_id: str,
) -> str:
    """Return the SUMO edge of a lane: the lane ID without its index."""

    return lane_id.rsplit("_", 1)[0]


def read_vehicle_states(
    fcd_path: str | Path,
    run_id: str,
    run_start: datetime,
    vehicle_movements: dict[str, str],
) -> Iterator[VehicleState]:
    """
    Read a SUMO FCD file written with --fcd-output.geo and
    --fcd-output.signals, and give back one VehicleState per vehicle
    and sample time. run_start is the real time of SUMO second 0.
    """

    for _, element in ET.iterparse(
        fcd_path,
        events=("end",),
    ):
        if element.tag != "timestep":
            continue

        simulation_time_s = float(element.get("time"))
        timestamp = run_start + timedelta(seconds=simulation_time_s)

        for vehicle in element.findall("vehicle"):
            vehicle_id = vehicle.get("id")

            if vehicle_id not in vehicle_movements:
                raise ValueError(
                    f"vehicle {vehicle_id} is not in the manifest"
                )

            lane_id = vehicle.get("lane")

            yield VehicleState(
                vehicle_id=vehicle_id,
                run_id=run_id,
                simulation_time_s=simulation_time_s,
                timestamp=timestamp,
                longitude=float(vehicle.get("x")),
                latitude=float(vehicle.get("y")),
                speed_mps=float(vehicle.get("speed")),
                heading_deg=float(vehicle.get("angle")) % 360,
                vehicle_type=VehicleType.CAR,
                sumo_edge_id=edge_of_lane(lane_id),
                sumo_lane_id=lane_id,
                lane_pos_m=float(vehicle.get("pos")),
                vtype_id=vehicle.get("type"),
                signals=int(vehicle.get("signals")),
                movement_id=vehicle_movements[vehicle_id],
            )

        element.clear()

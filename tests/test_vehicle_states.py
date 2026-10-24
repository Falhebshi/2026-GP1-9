import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.outputs.vehicles import (
    edge_of_lane,
    load_vehicle_movements,
    read_vehicle_states,
)


RUN_START = datetime.fromisoformat("2026-10-20T07:45:00+03:00")


def make_demand(
    movement_id: str,
) -> dict:
    """Create one demand record for vehicle tests."""

    return {
        "demand_id": f"DEM_TEST_{movement_id}_20261020T0800",
        "interval_start": "2026-10-20T07:45:00+03:00",
        "interval_end": "2026-10-20T08:00:00+03:00",
        "movement_id": movement_id,
        "vehicle_count": 1,
        "source": "synthetic",
        "source_observation_ids": [f"OBS_TEST_{movement_id}"],
    }


def make_departure(
    vehicle_id: str,
    movement_id: str,
) -> dict:
    """Create one planned departure for vehicle tests."""

    return {
        "vehicle_id": vehicle_id,
        "demand_id": f"DEM_TEST_{movement_id}_20261020T0800",
        "depart_s": 16.0,
    }


def write_demand_files(
    tmp_path,
    departures: list[dict],
    demands: list[dict],
):
    """Write a manifest and a demand file like the SUMO demand output."""

    manifest_path = tmp_path / "manifest.json"
    demand_path = tmp_path / "demand.json"

    manifest_path.write_text(
        json.dumps({"departures": departures}),
        encoding="utf-8",
    )
    demand_path.write_text(
        json.dumps(demands),
        encoding="utf-8",
    )

    return manifest_path, demand_path


def make_fcd_vehicle(
    vehicle_id: str,
    lane: str = "713369663#1_2",
    angle: str = "243.85",
) -> str:
    """Create one vehicle line of a SUMO FCD file."""

    return (
        f'<vehicle id="{vehicle_id}" x="46.641463" y="24.738699" '
        f'angle="{angle}" type="car" speed="23.66" pos="9.83" '
        f'lane="{lane}" slope="0.00" signals="8"/>'
    )


def write_fcd(
    tmp_path,
    vehicles: list[str],
):
    """Write a SUMO FCD file with one timestep at second 16.4."""

    path = tmp_path / "fcd.xml"
    path.write_text(
        '<fcd-export><timestep time="16.40">'
        + "".join(vehicles)
        + "</timestep></fcd-export>",
        encoding="utf-8",
    )

    return path


def read_one_state(
    fcd_path,
    run_start: datetime = RUN_START,
):
    """Read an FCD file that holds one sample of vehicle CAR_A."""

    [state] = read_vehicle_states(
        fcd_path=fcd_path,
        run_id="RUN_TEST",
        run_start=run_start,
        vehicle_movements={"CAR_A": "MOV_E_S"},
    )

    return state


def test_vehicle_movements_follow_the_demand_records(tmp_path) -> None:
    manifest_path, demand_path = write_demand_files(
        tmp_path=tmp_path,
        departures=[
            make_departure(
                vehicle_id="CAR_A",
                movement_id="MOV_E_S",
            ),
            make_departure(
                vehicle_id="CAR_B",
                movement_id="MOV_N_E",
            ),
        ],
        demands=[
            make_demand(movement_id="MOV_E_S"),
            make_demand(movement_id="MOV_N_E"),
        ],
    )

    assert load_vehicle_movements(
        manifest_path=manifest_path,
        demand_path=demand_path,
    ) == {
        "CAR_A": "MOV_E_S",
        "CAR_B": "MOV_N_E",
    }


def test_unknown_demand_id_is_refused(tmp_path) -> None:
    manifest_path, demand_path = write_demand_files(
        tmp_path=tmp_path,
        departures=[
            make_departure(
                vehicle_id="CAR_A",
                movement_id="MOV_E_S",
            ),
        ],
        demands=[
            make_demand(movement_id="MOV_N_E"),
        ],
    )

    with pytest.raises(
        ValueError,
        match="vehicle CAR_A has unknown demand_id",
    ):
        load_vehicle_movements(
            manifest_path=manifest_path,
            demand_path=demand_path,
        )


def test_fcd_sample_becomes_a_vehicle_state(tmp_path) -> None:
    state = read_one_state(
        write_fcd(
            tmp_path=tmp_path,
            vehicles=[make_fcd_vehicle(vehicle_id="CAR_A")],
        )
    )

    assert state.vehicle_id == "CAR_A"
    assert state.run_id == "RUN_TEST"
    assert state.simulation_time_s == 16.4
    assert (state.longitude, state.latitude) == (46.641463, 24.738699)
    assert state.speed_mps == 23.66
    assert state.heading_deg == 243.85
    assert state.sumo_edge_id == "713369663#1"
    assert state.sumo_lane_id == "713369663#1_2"
    assert state.lane_pos_m == 9.83
    assert state.vtype_id == "car"
    assert state.signals == 8
    assert state.movement_id == "MOV_E_S"
    assert state.z_m is None


def test_timestamp_is_run_start_plus_simulation_time(tmp_path) -> None:
    state = read_one_state(
        write_fcd(
            tmp_path=tmp_path,
            vehicles=[make_fcd_vehicle(vehicle_id="CAR_A")],
        )
    )

    assert state.timestamp == datetime.fromisoformat(
        "2026-10-20T07:45:16.400+03:00"
    )


def test_lane_index_is_removed_from_the_edge() -> None:
    assert edge_of_lane("713369663#1_2") == "713369663#1"
    assert edge_of_lane(":J15_0_2") == ":J15_0"


def test_heading_of_360_becomes_0(tmp_path) -> None:
    state = read_one_state(
        write_fcd(
            tmp_path=tmp_path,
            vehicles=[
                make_fcd_vehicle(
                    vehicle_id="CAR_A",
                    angle="360.00",
                ),
            ],
        )
    )

    assert state.heading_deg == 0


def test_vehicle_missing_from_the_manifest_is_refused(tmp_path) -> None:
    fcd_path = write_fcd(
        tmp_path=tmp_path,
        vehicles=[make_fcd_vehicle(vehicle_id="CAR_X")],
    )

    with pytest.raises(
        ValueError,
        match="vehicle CAR_X is not in the manifest",
    ):
        read_one_state(fcd_path)


def test_run_start_outside_riyadh_time_is_refused(tmp_path) -> None:
    fcd_path = write_fcd(
        tmp_path=tmp_path,
        vehicles=[make_fcd_vehicle(vehicle_id="CAR_A")],
    )

    with pytest.raises(ValidationError):
        read_one_state(
            fcd_path=fcd_path,
            run_start=datetime(
                2026,
                10,
                20,
                4,
                45,
                tzinfo=timezone.utc,
            ),
        )

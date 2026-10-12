from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import (
    ApproachTrafficState,
    EdgeTrafficState,
    VehicleState,
    VehicleType,
)


RIYADH = timezone(timedelta(hours=3))


# ============================================================
# VEHICLE STATE TESTS
# ============================================================

def test_valid_vehicle_state():
    state = VehicleState(
        vehicle_id="veh_001",
        scenario_id="SCN_001",
        run_id="RUN_001",
        simulation_time_s=10.5,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=46.63,
        latitude=24.74,
        speed_mps=12.5,
        heading_deg=90.0,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="edge_001",
        z_m=5.0,
        sumo_lane_id="lane_001",
        lane_pos_m=25.0,
        vtype_id="passenger",
        length_m=5.0,
        width_m=1.8,
        signals=0,
        movement_id="MOV_E_W",
    )

    assert state.vehicle_id == "veh_001"
    assert state.vehicle_type == VehicleType.CAR
    assert state.longitude == 46.63
    assert state.latitude == 24.74


def test_valid_minimal_vehicle_state():
    state = VehicleState(
        vehicle_id="veh_001",
        scenario_id="SCN_001",
        run_id="RUN_001",
        simulation_time_s=0,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=46.63,
        latitude=24.74,
        speed_mps=0,
        heading_deg=0,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="edge_001",
    )

    assert state.sumo_lane_id is None
    assert state.movement_id is None
    assert state.z_m is None


@pytest.mark.parametrize(
    "field",
    [
        "vehicle_id",
        "scenario_id",
        "run_id",
        "sumo_edge_id",
    ],
)
def test_blank_required_vehicle_ids_are_rejected(field):
    data = {
        "vehicle_id": "veh_001",
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "simulation_time_s": 10,
        "timestamp": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "longitude": 46.63,
        "latitude": 24.74,
        "speed_mps": 10,
        "heading_deg": 90,
        "vehicle_type": VehicleType.CAR,
        "sumo_edge_id": "edge_001",
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        VehicleState(**data)


def test_required_vehicle_ids_are_trimmed():
    state = VehicleState(
        vehicle_id="  veh_001  ",
        scenario_id="  SCN_001  ",
        run_id="  RUN_001  ",
        simulation_time_s=10,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=46.63,
        latitude=24.74,
        speed_mps=10,
        heading_deg=90,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="  edge_001  ",
    )

    assert state.vehicle_id == "veh_001"
    assert state.scenario_id == "SCN_001"
    assert state.run_id == "RUN_001"
    assert state.sumo_edge_id == "edge_001"


@pytest.mark.parametrize(
    "field",
    [
        "sumo_lane_id",
        "vtype_id",
        "movement_id",
    ],
)
def test_blank_optional_vehicle_ids_are_rejected(field):
    data = {
        "vehicle_id": "veh_001",
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "simulation_time_s": 10,
        "timestamp": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "longitude": 46.63,
        "latitude": 24.74,
        "speed_mps": 10,
        "heading_deg": 90,
        "vehicle_type": VehicleType.CAR,
        "sumo_edge_id": "edge_001",
        field: "   ",
    }

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        VehicleState(**data)


def test_optional_vehicle_ids_are_trimmed():
    state = VehicleState(
        vehicle_id="veh_001",
        scenario_id="SCN_001",
        run_id="RUN_001",
        simulation_time_s=10,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=46.63,
        latitude=24.74,
        speed_mps=10,
        heading_deg=90,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="edge_001",
        sumo_lane_id="  lane_001  ",
        vtype_id="  passenger  ",
        movement_id="  MOV_E_W  ",
    )

    assert state.sumo_lane_id == "lane_001"
    assert state.vtype_id == "passenger"
    assert state.movement_id == "MOV_E_W"


def test_naive_vehicle_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(2026, 10, 10, 8, 0),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


def test_non_riyadh_vehicle_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must use Riyadh time",
    ):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026,
                10,
                10,
                5,
                0,
                tzinfo=timezone.utc,
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (-180, -90),
        (180, 90),
        (0, 0),
    ],
)
def test_valid_coordinate_boundaries(longitude, latitude):
    state = VehicleState(
        vehicle_id="veh_001",
        scenario_id="SCN_001",
        run_id="RUN_001",
        simulation_time_s=10,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=longitude,
        latitude=latitude,
        speed_mps=10,
        heading_deg=90,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="edge_001",
    )

    assert state.longitude == longitude
    assert state.latitude == latitude


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (-180.1, 24.74),
        (180.1, 24.74),
        (46.63, -90.1),
        (46.63, 90.1),
    ],
)
def test_invalid_coordinates_are_rejected(
    longitude,
    latitude,
):
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=longitude,
            latitude=latitude,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_vehicle_values_are_rejected(value):
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=value,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


def test_negative_simulation_time_is_rejected():
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=-1,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


def test_negative_speed_is_rejected():
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=-0.1,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


@pytest.mark.parametrize(
    "heading",
    [
        -0.1,
        360,
        361,
    ],
)
def test_invalid_heading_is_rejected(heading):
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=heading,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
        )


def test_supported_vehicle_type():
    state = VehicleState(
        vehicle_id="veh_001",
        scenario_id="SCN_001",
        run_id="RUN_001",
        simulation_time_s=10,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        longitude=46.63,
        latitude=24.74,
        speed_mps=10,
        heading_deg=90,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="edge_001",
    )

    assert state.vehicle_type == VehicleType.CAR


@pytest.mark.parametrize(
    "vehicle_type",
    [
        "bus",
        "truck",
        "motorcycle",
    ],
)
def test_unsupported_vehicle_types_are_rejected(vehicle_type):
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=vehicle_type,
            sumo_edge_id="edge_001",
        )

@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lane_pos_m", -1),
        ("length_m", 0),
        ("length_m", -1),
        ("width_m", 0),
        ("width_m", -1),
        ("signals", -1),
    ],
)
def test_invalid_optional_vehicle_measurements_are_rejected(
    field,
    value,
):
    data = {
        "vehicle_id": "veh_001",
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "simulation_time_s": 10,
        "timestamp": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "longitude": 46.63,
        "latitude": 24.74,
        "speed_mps": 10,
        "heading_deg": 90,
        "vehicle_type": VehicleType.CAR,
        "sumo_edge_id": "edge_001",
        field: value,
    }

    with pytest.raises(ValidationError):
        VehicleState(**data)


def test_vehicle_state_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        VehicleState(
            vehicle_id="veh_001",
            scenario_id="SCN_001",
            run_id="RUN_001",
            simulation_time_s=10,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            longitude=46.63,
            latitude=24.74,
            speed_mps=10,
            heading_deg=90,
            vehicle_type=VehicleType.CAR,
            sumo_edge_id="edge_001",
            unknown_field="unexpected",
        )


# ============================================================
# EDGE TRAFFIC STATE TESTS
# ============================================================

def test_valid_edge_traffic_state():
    state = EdgeTrafficState(
        scenario_id="SCN_001",
        run_id="RUN_001",
        segment_id="SEG_001",
        sumo_edge_id="edge_001",
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        vehicles_entered=100,
        vehicles_left=95,
        average_speed_mps=12.5,
        travel_time_s=45,
        density_veh_per_km=20,
        time_loss_s=8.5,
        sampled_seconds=900,
    )

    assert state.segment_id == "SEG_001"
    assert state.vehicles_entered == 100
    assert state.sampled_seconds == 900


def test_valid_edge_state_without_segment_mapping():
    state = EdgeTrafficState(
        scenario_id="SCN_001",
        run_id="RUN_001",
        sumo_edge_id="edge_001",
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        vehicles_entered=100,
        vehicles_left=95,
        density_veh_per_km=20,
        sampled_seconds=900,
    )

    assert state.segment_id is None
    assert state.average_speed_mps is None
    assert state.travel_time_s is None
    assert state.time_loss_s is None


@pytest.mark.parametrize(
    "field",
    [
        "scenario_id",
        "run_id",
        "sumo_edge_id",
    ],
)
def test_blank_required_edge_ids_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "sumo_edge_id": "edge_001",
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        "vehicles_entered": 100,
        "vehicles_left": 95,
        "density_veh_per_km": 20,
        "sampled_seconds": 900,
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        EdgeTrafficState(**data)


def test_blank_segment_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            segment_id="   ",
            sumo_edge_id="edge_001",
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 15, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
        )


def test_edge_ids_are_trimmed():
    state = EdgeTrafficState(
        scenario_id="  SCN_001  ",
        run_id="  RUN_001  ",
        segment_id="  SEG_001  ",
        sumo_edge_id="  edge_001  ",
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        vehicles_entered=100,
        vehicles_left=95,
        density_veh_per_km=20,
        sampled_seconds=900,
    )

    assert state.scenario_id == "SCN_001"
    assert state.run_id == "RUN_001"
    assert state.segment_id == "SEG_001"
    assert state.sumo_edge_id == "edge_001"


def test_edge_interval_equal_times_are_rejected():
    timestamp = datetime(
        2026, 10, 10, 8, 0, tzinfo=RIYADH
    )

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=timestamp,
            interval_end=timestamp,
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
        )


def test_edge_interval_end_before_start_is_rejected():
    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=datetime(
                2026, 10, 10, 9, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
        )


def test_naive_edge_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=datetime(2026, 10, 10, 8, 0),
            interval_end=datetime(
                2026, 10, 10, 8, 15, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
        )


def test_non_riyadh_edge_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must use Riyadh time",
    ):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=datetime(
                2026, 10, 10, 5, 0, tzinfo=timezone.utc
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 15, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
        )


@pytest.mark.parametrize(
    "field",
    [
        "vehicles_entered",
        "vehicles_left",
    ],
)
def test_negative_edge_vehicle_counts_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "sumo_edge_id": "edge_001",
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        "vehicles_entered": 100,
        "vehicles_left": 95,
        "density_veh_per_km": 20,
        "sampled_seconds": 900,
    }

    data[field] = -1

    with pytest.raises(ValidationError):
        EdgeTrafficState(**data)


@pytest.mark.parametrize(
    "field",
    [
        "vehicles_entered",
        "vehicles_left",
    ],
)
def test_boolean_edge_vehicle_counts_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "sumo_edge_id": "edge_001",
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        "vehicles_entered": 100,
        "vehicles_left": 95,
        "density_veh_per_km": 20,
        "sampled_seconds": 900,
    }

    data[field] = True

    with pytest.raises(
        ValidationError,
        match="vehicle count must be an integer",
    ):
        EdgeTrafficState(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("average_speed_mps", -1),
        ("travel_time_s", -1),
        ("density_veh_per_km", -1),
        ("time_loss_s", -1),
        ("sampled_seconds", 0),
        ("sampled_seconds", -1),
    ],
)
def test_invalid_edge_measurements_are_rejected(
    field,
    value,
):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "sumo_edge_id": "edge_001",
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 15, tzinfo=RIYADH
        ),
        "vehicles_entered": 100,
        "vehicles_left": 95,
        "density_veh_per_km": 20,
        "sampled_seconds": 900,
    }

    data[field] = value

    with pytest.raises(ValidationError):
        EdgeTrafficState(**data)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_edge_measurements_are_rejected(value):
    with pytest.raises(ValidationError):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 15, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=value,
            sampled_seconds=900,
        )


def test_edge_state_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        EdgeTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            sumo_edge_id="edge_001",
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 15, tzinfo=RIYADH
            ),
            vehicles_entered=100,
            vehicles_left=95,
            density_veh_per_km=20,
            sampled_seconds=900,
            kpi_score=0.9,
        )


# ============================================================
# APPROACH TRAFFIC STATE TESTS
# ============================================================

def test_valid_approach_traffic_state():
    state = ApproachTrafficState(
        scenario_id="SCN_001",
        run_id="RUN_001",
        intersection_id="INT_001",
        approach_id="APP_EAST",
        queue_detection_lane_ids=[
            "lane_east_1",
            "lane_east_2",
        ],
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        max_queue_length_m=80.5,
        mean_max_queue_vehicles=7.5,
        started_halts=12,
        vehicles_seen=40,
        mean_time_loss_s=15.2,
    )

    assert state.approach_id == "APP_EAST"
    assert len(state.queue_detection_lane_ids) == 2
    assert state.max_queue_length_m == 80.5


def test_valid_approach_state_without_time_loss():
    state = ApproachTrafficState(
        scenario_id="SCN_001",
        run_id="RUN_001",
        intersection_id="INT_001",
        approach_id="APP_EAST",
        queue_detection_lane_ids=["lane_east_1"],
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        max_queue_length_m=0,
        mean_max_queue_vehicles=0,
        started_halts=0,
        vehicles_seen=0,
    )

    assert state.mean_time_loss_s is None


@pytest.mark.parametrize(
    "field",
    [
        "scenario_id",
        "run_id",
        "intersection_id",
        "approach_id",
    ],
)
def test_blank_required_approach_ids_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "intersection_id": "INT_001",
        "approach_id": "APP_EAST",
        "queue_detection_lane_ids": ["lane_east_1"],
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        "max_queue_length_m": 50,
        "mean_max_queue_vehicles": 5,
        "started_halts": 10,
        "vehicles_seen": 30,
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        ApproachTrafficState(**data)


def test_approach_ids_are_trimmed():
    state = ApproachTrafficState(
        scenario_id="  SCN_001  ",
        run_id="  RUN_001  ",
        intersection_id="  INT_001  ",
        approach_id="  APP_EAST  ",
        queue_detection_lane_ids=["lane_east_1"],
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        max_queue_length_m=50,
        mean_max_queue_vehicles=5,
        started_halts=10,
        vehicles_seen=30,
    )

    assert state.scenario_id == "SCN_001"
    assert state.run_id == "RUN_001"
    assert state.intersection_id == "INT_001"
    assert state.approach_id == "APP_EAST"


def test_queue_detection_lane_ids_are_trimmed():
    state = ApproachTrafficState(
        scenario_id="SCN_001",
        run_id="RUN_001",
        intersection_id="INT_001",
        approach_id="APP_EAST",
        queue_detection_lane_ids=[
            "  lane_east_1  ",
            "  lane_east_2  ",
        ],
        interval_start=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        interval_end=datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        max_queue_length_m=50,
        mean_max_queue_vehicles=5,
        started_halts=10,
        vehicles_seen=30,
    )

    assert state.queue_detection_lane_ids == [
        "lane_east_1",
        "lane_east_2",
    ]


def test_empty_queue_detection_lane_list_is_rejected():
    with pytest.raises(
        ValidationError,
        match="at least one queue detection lane ID is required",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=[],
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_blank_queue_detection_lane_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="queue detection lane ID must not be empty",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=[
                "lane_east_1",
                "   ",
            ],
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_duplicate_queue_detection_lane_ids_are_rejected():
    with pytest.raises(
        ValidationError,
        match="must not contain duplicates",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=[
                "lane_east_1",
                "lane_east_1",
            ],
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_approach_interval_equal_times_are_rejected():
    timestamp = datetime(
        2026, 10, 10, 8, 0, tzinfo=RIYADH
    )

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=timestamp,
            interval_end=timestamp,
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_approach_interval_end_before_start_is_rejected():
    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=datetime(
                2026, 10, 10, 9, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_naive_approach_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=datetime(
                2026, 10, 10, 8, 0
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_non_riyadh_approach_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must use Riyadh time",
    ):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=datetime(
                2026,
                10,
                10,
                5,
                0,
                tzinfo=timezone.utc,
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_queue_length_m", -1),
        ("mean_max_queue_vehicles", -1),
        ("started_halts", -1),
        ("vehicles_seen", -1),
        ("mean_time_loss_s", -1),
    ],
)
def test_invalid_approach_measurements_are_rejected(
    field,
    value,
):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "intersection_id": "INT_001",
        "approach_id": "APP_EAST",
        "queue_detection_lane_ids": ["lane_east_1"],
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        "max_queue_length_m": 50,
        "mean_max_queue_vehicles": 5,
        "started_halts": 10,
        "vehicles_seen": 30,
    }

    data[field] = value

    with pytest.raises(ValidationError):
        ApproachTrafficState(**data)


@pytest.mark.parametrize(
    "field",
    [
        "started_halts",
        "vehicles_seen",
    ],
)
def test_boolean_approach_vehicle_counts_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "run_id": "RUN_001",
        "intersection_id": "INT_001",
        "approach_id": "APP_EAST",
        "queue_detection_lane_ids": ["lane_east_1"],
        "interval_start": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "interval_end": datetime(
            2026, 10, 10, 8, 1, tzinfo=RIYADH
        ),
        "max_queue_length_m": 50,
        "mean_max_queue_vehicles": 5,
        "started_halts": 10,
        "vehicles_seen": 30,
    }

    data[field] = True

    with pytest.raises(
        ValidationError,
        match="vehicle count must be an integer",
    ):
        ApproachTrafficState(**data)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_approach_measurements_are_rejected(value):
    with pytest.raises(ValidationError):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=value,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
        )


def test_approach_state_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        ApproachTrafficState(
            scenario_id="SCN_001",
            run_id="RUN_001",
            intersection_id="INT_001",
            approach_id="APP_EAST",
            queue_detection_lane_ids=["lane_east_1"],
            interval_start=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            interval_end=datetime(
                2026, 10, 10, 8, 1, tzinfo=RIYADH
            ),
            max_queue_length_m=50,
            mean_max_queue_vehicles=5,
            started_halts=10,
            vehicles_seen=30,
            congestion_level="high",
        )
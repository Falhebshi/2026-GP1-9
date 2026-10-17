from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import VehicleDelayRecord


RIYADH = timezone(timedelta(hours=3))

ENTRY = datetime(2026, 10, 14, 8, 0, 0, tzinfo=RIYADH)


def valid_record_data(**overrides):
    """
    A valid passage: the vehicle enters the zone at 08:00:00, crosses
    the stop line at 08:00:40 and leaves at 08:00:55 (55 s in the
    zone). With no traffic it would have needed 25 s (330 m at
    13.2 m/s), so it lost 30 s. It stood still for 20 s.
    """

    data = {
        "run_id": "RUN_1",
        "vehicle_id": "veh_0042",
        "movement_id": "MOV_E_T",
        "zone_entry_time": ENTRY,
        "stop_line_time": ENTRY + timedelta(seconds=40),
        "zone_exit_time": ENTRY + timedelta(seconds=55),
        "zone_distance_m": 330.0,
        "free_flow_travel_time_s": 25.0,
        "halted_time_s": 20.0,
    }
    data.update(overrides)
    return data


# ============================================================
# VALID RECORDS
# ============================================================

def test_valid_record():
    record = VehicleDelayRecord(**valid_record_data())

    assert record.movement_id == "MOV_E_T"
    assert record.free_flow_travel_time_s == 25.0


def test_zone_travel_time_is_calculated():
    record = VehicleDelayRecord(**valid_record_data())

    assert record.zone_travel_time_s == 55.0


def test_time_loss_is_calculated():
    record = VehicleDelayRecord(**valid_record_data())

    assert record.time_loss_s == 30.0


def test_vehicle_with_no_delay():
    record = VehicleDelayRecord(
        **valid_record_data(free_flow_travel_time_s=55.0)
    )

    assert record.time_loss_s == 0


def test_time_loss_cannot_be_set():
    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(time_loss_s=30.0))


@pytest.mark.parametrize(
    "stop_line_seconds",
    [0, 55],
)
def test_stop_line_at_zone_boundary_is_allowed(stop_line_seconds):
    record = VehicleDelayRecord(
        **valid_record_data(
            stop_line_time=ENTRY + timedelta(seconds=stop_line_seconds)
        )
    )

    assert record.zone_entry_time <= record.stop_line_time


def test_ids_are_stripped():
    record = VehicleDelayRecord(
        **valid_record_data(vehicle_id="  veh_0042  ")
    )

    assert record.vehicle_id == "veh_0042"


# ============================================================
# IDENTIFIERS
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["run_id", "vehicle_id", "movement_id"],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(**{field: bad_value}))


@pytest.mark.parametrize(
    "field, value",
    [
        ("scenario_id", "SCN_BASE"),
        ("approach_id", "APP_E"),
        ("intersection_id", "INT_01"),
    ],
)
def test_parent_ids_are_not_fields(field, value):
    """Rule (a): parents are looked up through run_id and movement_id."""

    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(**{field: value}))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(sumo_lane_id="E12_0"))


# ============================================================
# TIME
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["zone_entry_time", "stop_line_time", "zone_exit_time"],
)
def test_naive_timestamp_rejected(field):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(
            **valid_record_data(**{field: datetime(2026, 10, 14, 8, 0, 20)})
        )


def test_non_riyadh_timestamps_rejected():
    utc_entry = datetime(2026, 10, 14, 5, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError):
        VehicleDelayRecord(
            **valid_record_data(
                zone_entry_time=utc_entry,
                stop_line_time=utc_entry + timedelta(seconds=40),
                zone_exit_time=utc_entry + timedelta(seconds=55),
            )
        )


@pytest.mark.parametrize("exit_seconds", [0, -10])
def test_exit_not_after_entry_rejected(exit_seconds):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(
            **valid_record_data(
                stop_line_time=ENTRY,
                zone_exit_time=ENTRY + timedelta(seconds=exit_seconds),
            )
        )


@pytest.mark.parametrize(
    "stop_line_seconds",
    [-1, 56],
)
def test_stop_line_outside_zone_rejected(stop_line_seconds):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(
            **valid_record_data(
                stop_line_time=ENTRY + timedelta(seconds=stop_line_seconds)
            )
        )


# ============================================================
# NUMBERS
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["zone_distance_m", "free_flow_travel_time_s"],
)
@pytest.mark.parametrize(
    "bad_value",
    [0, -5.0, float("nan"), float("inf")],
)
def test_invalid_distance_or_free_flow_time_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(**{field: bad_value}))


def test_faster_than_free_flow_rejected():
    with pytest.raises(ValidationError):
        VehicleDelayRecord(
            **valid_record_data(free_flow_travel_time_s=55.1)
        )


# ============================================================
# TIME STOPPED (queue duration per vehicle)
# ============================================================

@pytest.mark.parametrize("halted", [0, 55.0])
def test_halted_time_within_zone_time_is_allowed(halted):
    record = VehicleDelayRecord(**valid_record_data(halted_time_s=halted))

    assert record.halted_time_s == halted


def test_halted_longer_than_zone_time_rejected():
    with pytest.raises(ValidationError, match="halted_time_s cannot exceed"):
        VehicleDelayRecord(**valid_record_data(halted_time_s=55.1))


@pytest.mark.parametrize(
    "bad_value",
    [-1.0, float("nan"), float("inf")],
)
def test_invalid_halted_time_rejected(bad_value):
    with pytest.raises(ValidationError):
        VehicleDelayRecord(**valid_record_data(halted_time_s=bad_value))


def test_halted_time_is_required():
    data = valid_record_data()
    del data["halted_time_s"]

    with pytest.raises(ValidationError):
        VehicleDelayRecord(**data)
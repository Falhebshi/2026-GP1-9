from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import UninsertedVehicle


RIYADH = timezone(timedelta(hours=3))

PLANNED = datetime(2026, 10, 14, 8, 14, 30, tzinfo=RIYADH)


def valid_vehicle_data(**overrides):
    """A West-through vehicle planned to reach the stop line at 08:14:30."""

    data = {
        "run_id": "RUN_1",
        "vehicle_id": "MOV_W_T__0042",
        "movement_id": "MOV_W_T",
        "planned_stop_line_time": PLANNED,
    }
    data.update(overrides)
    return data


# ============================================================
# VALID RECORDS
# ============================================================

def test_valid_vehicle():
    vehicle = UninsertedVehicle(**valid_vehicle_data())

    assert vehicle.planned_stop_line_time == PLANNED


def test_ids_are_stripped():
    vehicle = UninsertedVehicle(**valid_vehicle_data(movement_id="  MOV_W_T  "))

    assert vehicle.movement_id == "MOV_W_T"


# ============================================================
# IDENTIFIERS
# ============================================================

@pytest.mark.parametrize("field", ["run_id", "vehicle_id", "movement_id"])
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError, match="identifier must not be empty"):
        UninsertedVehicle(**valid_vehicle_data(**{field: bad_value}))


@pytest.mark.parametrize("field", ["scenario_id", "approach_id", "intersection_id"])
def test_parent_ids_are_not_fields(field):
    with pytest.raises(ValidationError):
        UninsertedVehicle(**valid_vehicle_data(**{field: "X"}))


# ============================================================
# TIME
# ============================================================

def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError, match="timezone information"):
        UninsertedVehicle(**valid_vehicle_data(planned_stop_line_time=PLANNED.replace(tzinfo=None)))


def test_non_riyadh_timestamp_rejected():
    with pytest.raises(ValidationError, match="Riyadh time"):
        UninsertedVehicle(
            **valid_vehicle_data(planned_stop_line_time=PLANNED.astimezone(timezone.utc))
        )

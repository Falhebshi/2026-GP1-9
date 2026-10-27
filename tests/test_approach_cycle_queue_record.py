from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import ApproachCycleQueueRecord


RIYADH = timezone(timedelta(hours=3))

CYCLE_START = datetime(2026, 10, 14, 8, 0, 0, tzinfo=RIYADH)


def valid_queue_data(**overrides):
    """
    A valid 120 s cycle on approach APP_S: the queue reached 260 m back
    from the stop line (34 vehicles).
    """

    data = {
        "run_id": "RUN_1",
        "approach_id": "APP_S",
        "cycle_start": CYCLE_START,
        "cycle_end": CYCLE_START + timedelta(seconds=120),
        "max_queue_length_m": 260.0,
        "max_queue_vehicles": 34,
    }
    data.update(overrides)
    return data


# ============================================================
# VALID RECORDS
# ============================================================

def test_valid_record():
    record = ApproachCycleQueueRecord(**valid_queue_data())

    assert (record.approach_id, record.max_queue_vehicles) == ("APP_S", 34)
    assert record.reaches_zone_end is False


def test_cycle_without_queue():
    record = ApproachCycleQueueRecord(**valid_queue_data(max_queue_length_m=0, max_queue_vehicles=0))

    assert record.max_queue_length_m == 0


def test_queue_reaching_the_zone_end():
    record = ApproachCycleQueueRecord(**valid_queue_data(max_queue_length_m=500, reaches_zone_end=True))

    assert record.reaches_zone_end is True


def test_ids_are_stripped():
    record = ApproachCycleQueueRecord(**valid_queue_data(approach_id=" APP_S "))

    assert record.approach_id == "APP_S"


def test_json_round_trip():
    record = ApproachCycleQueueRecord(**valid_queue_data())

    assert ApproachCycleQueueRecord.model_validate_json(record.model_dump_json()) == record


# ============================================================
# REJECTED RECORDS
# ============================================================

@pytest.mark.parametrize("field", ["run_id", "approach_id"])
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        ApproachCycleQueueRecord(**valid_queue_data(**{field: bad_value}))


@pytest.mark.parametrize("field, value", [("scenario_id", "SCN_BASE"), ("intersection_id", "INT_01"),
                                          ("lane_id", "LANE_S_1")])
def test_parent_and_lane_ids_are_not_fields(field, value):
    """The intersection is looked up through approach_id; lanes have their own records."""
    with pytest.raises(ValidationError):
        ApproachCycleQueueRecord(**valid_queue_data(**{field: value}))


@pytest.mark.parametrize("field", ["cycle_start", "cycle_end"])
def test_naive_timestamp_rejected(field):
    with pytest.raises(ValidationError, match="timezone"):
        ApproachCycleQueueRecord(**valid_queue_data(**{field: datetime(2026, 10, 14, 8, 1)}))


def test_non_riyadh_timestamp_rejected():
    with pytest.raises(ValidationError, match="Riyadh"):
        ApproachCycleQueueRecord(**valid_queue_data(
            cycle_start=datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)))


def test_cycle_end_before_start_rejected():
    with pytest.raises(ValidationError, match="later than cycle_start"):
        ApproachCycleQueueRecord(**valid_queue_data(cycle_end=CYCLE_START))


@pytest.mark.parametrize("fields", [{"max_queue_length_m": -1}, {"max_queue_vehicles": -1},
                                    {"max_queue_length_m": float("inf")}, {"max_queue_vehicles": True}])
def test_invalid_queue_values_rejected(fields):
    with pytest.raises(ValidationError):
        ApproachCycleQueueRecord(**valid_queue_data(**fields))


@pytest.mark.parametrize("fields", [{"max_queue_length_m": 0}, {"max_queue_vehicles": 0}])
def test_units_must_agree(fields):
    with pytest.raises(ValidationError, match="both be zero"):
        ApproachCycleQueueRecord(**valid_queue_data(**fields))


def test_zone_end_without_a_queue_rejected():
    with pytest.raises(ValidationError, match="must have a length"):
        ApproachCycleQueueRecord(**valid_queue_data(
            max_queue_length_m=0, max_queue_vehicles=0, reaches_zone_end=True))

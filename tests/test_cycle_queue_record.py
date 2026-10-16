from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import CycleQueueRecord


RIYADH = timezone(timedelta(hours=3))

CYCLE_START = datetime(2026, 10, 14, 8, 0, 0, tzinfo=RIYADH)


def valid_queue_data(**overrides):
    """
    A valid 120 s cycle on East lane 2: the longest queue was 48 m
    (7 vehicles); halted vehicles stood still 35 s on average and
    62 s at most.
    """

    data = {
        "run_id": "RUN_1",
        "approach_id": "APP_E",
        "lane_index": 2,
        "cycle_start": CYCLE_START,
        "cycle_end": CYCLE_START + timedelta(seconds=120),
        "max_queue_length_m": 48.0,
        "max_queue_vehicles": 7,
        "mean_halting_duration_s": 35.0,
        "max_halting_duration_s": 62.0,
    }
    data.update(overrides)
    return data


# ============================================================
# VALID RECORDS
# ============================================================

def test_valid_record():
    record = CycleQueueRecord(**valid_queue_data())

    assert record.lane_index == 2
    assert record.max_queue_vehicles == 7


def test_cycle_without_queue():
    record = CycleQueueRecord(
        **valid_queue_data(
            max_queue_length_m=0,
            max_queue_vehicles=0,
            mean_halting_duration_s=0,
            max_halting_duration_s=0,
        )
    )

    assert record.max_queue_length_m == 0


def test_cycle_length_is_not_fixed():
    record = CycleQueueRecord(
        **valid_queue_data(
            cycle_end=CYCLE_START + timedelta(seconds=90)
        )
    )

    assert record.cycle_end > record.cycle_start


def test_equal_mean_and_max_halting_is_allowed():
    record = CycleQueueRecord(
        **valid_queue_data(
            mean_halting_duration_s=40.0,
            max_halting_duration_s=40.0,
        )
    )

    assert record.mean_halting_duration_s == 40.0


def test_ids_are_stripped():
    record = CycleQueueRecord(**valid_queue_data(approach_id=" APP_E "))

    assert record.approach_id == "APP_E"


# ============================================================
# IDENTIFIERS
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["run_id", "approach_id"],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_ids_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(**{field: bad_value}))


@pytest.mark.parametrize(
    "field, value",
    [("scenario_id", "SCN_BASE"), ("intersection_id", "INT_01")],
)
def test_parent_ids_are_not_fields(field, value):
    """Rule (a): parents are looked up through run_id and approach_id."""

    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(**{field: value}))


@pytest.mark.parametrize(
    "bad_value",
    [0, -1, True, 1.5],
)
def test_invalid_lane_index_rejected(bad_value):
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(lane_index=bad_value))


def test_movement_id_is_not_a_field():
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(movement_id="MOV_E_T"))


def test_sumo_detector_id_is_not_a_field():
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(sumo_detector_id="e2_E_1"))


# ============================================================
# TIME
# ============================================================

@pytest.mark.parametrize("field", ["cycle_start", "cycle_end"])
def test_naive_timestamp_rejected(field):
    with pytest.raises(ValidationError):
        CycleQueueRecord(
            **valid_queue_data(**{field: datetime(2026, 10, 14, 8, 1)})
        )


def test_non_riyadh_timestamps_rejected():
    utc_start = datetime(2026, 10, 14, 5, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError):
        CycleQueueRecord(
            **valid_queue_data(
                cycle_start=utc_start,
                cycle_end=utc_start + timedelta(seconds=120),
            )
        )


@pytest.mark.parametrize("seconds", [0, -120])
def test_cycle_end_not_after_start_rejected(seconds):
    with pytest.raises(ValidationError):
        CycleQueueRecord(
            **valid_queue_data(
                cycle_end=CYCLE_START + timedelta(seconds=seconds)
            )
        )


# ============================================================
# NUMBERS
# ============================================================

@pytest.mark.parametrize(
    "field",
    [
        "max_queue_length_m",
        "mean_halting_duration_s",
        "max_halting_duration_s",
    ],
)
@pytest.mark.parametrize(
    "bad_value",
    [-1.0, float("nan"), float("inf")],
)
def test_invalid_measurements_rejected(field, bad_value):
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(**{field: bad_value}))


@pytest.mark.parametrize(
    "bad_value",
    [-1, True, 7.5],
)
def test_invalid_queue_vehicles_rejected(bad_value):
    with pytest.raises(ValidationError):
        CycleQueueRecord(**valid_queue_data(max_queue_vehicles=bad_value))


def test_mean_halting_above_max_rejected():
    with pytest.raises(ValidationError):
        CycleQueueRecord(
            **valid_queue_data(
                mean_halting_duration_s=70.0,
                max_halting_duration_s=62.0,
            )
        )


@pytest.mark.parametrize(
    "length_m, vehicles",
    [(0, 7), (48.0, 0)],
)
def test_queue_units_must_agree(length_m, vehicles):
    with pytest.raises(ValidationError):
        CycleQueueRecord(
            **valid_queue_data(
                max_queue_length_m=length_m,
                max_queue_vehicles=vehicles,
            )
        )
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.outputs import IncompletePassage


RIYADH = timezone(timedelta(hours=3))

ENTRY = datetime(2026, 10, 14, 8, 58, 30, tzinfo=RIYADH)


def valid_passage_data(**overrides):
    """
    A vehicle that entered the zone at 08:58:30 and was still queued
    before the stop line when the run ended (last seen 09:00:00).
    """

    data = {
        "run_id": "RUN_1",
        "vehicle_id": "veh_0981",
        "movement_id": "MOV_E_T",
        "zone_entry_time": ENTRY,
        "last_seen_time": ENTRY + timedelta(seconds=90),
    }
    data.update(overrides)
    return data


# ============================================================
# VALID RECORDS
# ============================================================

def test_valid_passage_not_yet_served():
    passage = IncompletePassage(**valid_passage_data())

    assert passage.stop_line_time is None
    assert passage.crossed_stop_line is False


def test_valid_passage_already_served():
    passage = IncompletePassage(
        **valid_passage_data(
            stop_line_time=ENTRY + timedelta(seconds=80)
        )
    )

    assert passage.crossed_stop_line is True


def test_last_seen_at_entry_is_allowed():
    passage = IncompletePassage(
        **valid_passage_data(last_seen_time=ENTRY)
    )

    assert passage.last_seen_time == passage.zone_entry_time


@pytest.mark.parametrize("stop_line_seconds", [0, 90])
def test_stop_line_at_boundary_is_allowed(stop_line_seconds):
    passage = IncompletePassage(
        **valid_passage_data(
            stop_line_time=ENTRY + timedelta(seconds=stop_line_seconds)
        )
    )

    assert passage.crossed_stop_line is True


def test_ids_are_stripped():
    passage = IncompletePassage(
        **valid_passage_data(movement_id="  MOV_E_T  ")
    )

    assert passage.movement_id == "MOV_E_T"


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
        IncompletePassage(**valid_passage_data(**{field: bad_value}))


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
        IncompletePassage(**valid_passage_data(**{field: value}))


def test_time_loss_is_not_a_field():
    with pytest.raises(ValidationError):
        IncompletePassage(**valid_passage_data(time_loss_s=40.0))


# ============================================================
# TIME
# ============================================================

@pytest.mark.parametrize(
    "field",
    ["zone_entry_time", "stop_line_time", "last_seen_time"],
)
def test_naive_timestamp_rejected(field):
    with pytest.raises(ValidationError):
        IncompletePassage(
            **valid_passage_data(**{field: datetime(2026, 10, 14, 8, 59)})
        )


def test_non_riyadh_timestamps_rejected():
    utc_entry = datetime(2026, 10, 14, 5, 58, 30, tzinfo=timezone.utc)

    with pytest.raises(ValidationError):
        IncompletePassage(
            **valid_passage_data(
                zone_entry_time=utc_entry,
                last_seen_time=utc_entry + timedelta(seconds=90),
            )
        )


def test_last_seen_before_entry_rejected():
    with pytest.raises(ValidationError):
        IncompletePassage(
            **valid_passage_data(
                last_seen_time=ENTRY - timedelta(seconds=1)
            )
        )


@pytest.mark.parametrize("stop_line_seconds", [-1, 91])
def test_stop_line_outside_seen_period_rejected(stop_line_seconds):
    with pytest.raises(ValidationError):
        IncompletePassage(
            **valid_passage_data(
                stop_line_time=ENTRY + timedelta(seconds=stop_line_seconds)
            )
        )
from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.ingestion.adapter import adapt_synthetic_record
from jaadah.models.traffic import TrafficObservationSource


def make_valid_record() -> dict:
    """Return one valid synthetic source record for adapter tests."""

    return {
        "Site ID": 9,
        "detector_id": 3,
        "Date  & Time": "2026-10-14T22:45:00+03:00",
        "volume": 51,
        "description": "SYN-WB-L1",
    }


def test_valid_synthetic_record_is_adapted() -> None:
    record = make_valid_record()

    observation = adapt_synthetic_record(record)

    assert observation.observation_id == (
        "OBS_SYN_9_3_20261014T2245"
    )

    assert observation.source == TrafficObservationSource.SYNTHETIC

    assert observation.site_id == "9"
    assert observation.detector_id == "3"

    assert observation.interval_start == datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    assert observation.interval_end == datetime.fromisoformat(
        "2026-10-14T22:45:00+03:00"
    )

    assert observation.vehicle_count == 51
    assert observation.description == "SYN-WB-L1"

    assert observation.average_speed_kmh is None
    assert observation.travel_time_s is None


def test_same_record_gets_same_observation_id() -> None:
    record = make_valid_record()

    first = adapt_synthetic_record(record)
    second = adapt_synthetic_record(record)

    assert first.observation_id == second.observation_id


def test_missing_description_is_rejected() -> None:
    record = make_valid_record()
    del record["description"]

    with pytest.raises(
        ValueError,
        match="missing required field",
    ):
        adapt_synthetic_record(record)


def test_blank_description_is_rejected() -> None:
    record = make_valid_record()
    record["description"] = "   "

    with pytest.raises(
        ValueError,
        match="description must not be empty",
    ):
        adapt_synthetic_record(record)


def test_timestamp_must_be_on_15_minute_boundary() -> None:
    record = make_valid_record()
    record["Date  & Time"] = "2026-10-14T22:47:00+03:00"

    with pytest.raises(
        ValueError,
        match="15-minute boundary",
    ):
        adapt_synthetic_record(record)


def test_negative_vehicle_count_is_rejected() -> None:
    record = make_valid_record()
    record["volume"] = -4

    with pytest.raises(ValidationError):
        adapt_synthetic_record(record)


def test_null_description_is_rejected() -> None:
    record = make_valid_record()
    record["description"] = None

    with pytest.raises(
        ValueError,
        match="description must not be null",
    ):
        adapt_synthetic_record(record)
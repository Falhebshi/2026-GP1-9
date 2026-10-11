import pytest
from pydantic import ValidationError

from jaadah.models.traffic import TrafficObservation


# ============================================================
# TRAFFIC OBSERVATION TESTS
# ============================================================

def valid_observation_data():
    """Return valid TrafficObservation input for testing."""

    return {
        "observation_id": "OBS_001",
        "source": "rcrc",
        "site_id": "1028",
        "detector_id": "102809",
        "interval_start": "2026-10-10T08:00:00+03:00",
        "interval_end": "2026-10-10T08:15:00+03:00",
        "vehicle_count": 32,
        "description": "P2-WB-L1-L-STB",
    }


def test_valid_observation():
    observation = TrafficObservation(**valid_observation_data())

    assert observation.observation_id == "OBS_001"
    assert observation.vehicle_count == 32
    assert observation.source.value == "rcrc"


def test_optional_fields_can_be_missing():
    data = valid_observation_data()
    data.pop("description")

    observation = TrafficObservation(**data)

    assert observation.description is None
    assert observation.average_speed_kmh is None
    assert observation.travel_time_s is None


def test_zero_vehicle_count_is_allowed():
    data = valid_observation_data()
    data["vehicle_count"] = 0

    observation = TrafficObservation(**data)

    assert observation.vehicle_count == 0


def test_negative_vehicle_count_is_rejected():
    data = valid_observation_data()
    data["vehicle_count"] = -5

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


@pytest.mark.parametrize(
    "value",
    [True, False],
)
def test_boolean_vehicle_count_is_rejected(value):
    data = valid_observation_data()
    data["vehicle_count"] = value

    with pytest.raises(
        ValidationError,
        match="vehicle_count must be an integer, not a boolean",
    ):
        TrafficObservation(**data)


def test_string_vehicle_count_is_converted_to_integer():
    data = valid_observation_data()
    data["vehicle_count"] = "32"

    observation = TrafficObservation(**data)

    assert observation.vehicle_count == 32
    assert isinstance(observation.vehicle_count, int)


def test_fractional_vehicle_count_is_rejected():
    data = valid_observation_data()
    data["vehicle_count"] = 32.5

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


def test_invalid_source_is_rejected():
    data = valid_observation_data()
    data["source"] = "unknown"

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


@pytest.mark.parametrize(
    "field",
    [
        "observation_id",
        "site_id",
        "detector_id",
    ],
)
def test_empty_required_id_is_rejected(field):
    data = valid_observation_data()
    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        TrafficObservation(**data)


def test_id_whitespace_is_removed():
    data = valid_observation_data()
    data["observation_id"] = "  OBS_001  "

    observation = TrafficObservation(**data)

    assert observation.observation_id == "OBS_001"


def test_missing_required_field_is_rejected():
    data = valid_observation_data()
    data.pop("detector_id")

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


def test_invalid_interval_is_rejected():
    data = valid_observation_data()
    data["interval_end"] = "2026-10-10T07:45:00+03:00"

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        TrafficObservation(**data)


def test_equal_interval_times_are_rejected():
    data = valid_observation_data()
    data["interval_end"] = data["interval_start"]

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        TrafficObservation(**data)


def test_timezone_naive_timestamp_is_rejected():
    data = valid_observation_data()
    data["interval_start"] = "2026-10-10T08:00:00"
    data["interval_end"] = "2026-10-10T08:15:00"

    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        TrafficObservation(**data)


def test_non_riyadh_timezone_is_rejected():
    data = valid_observation_data()
    data["interval_start"] = "2026-10-10T06:00:00+01:00"
    data["interval_end"] = "2026-10-10T06:15:00+01:00"

    with pytest.raises(
        ValidationError,
        match=r"timestamp must use Riyadh time \(UTC\+03:00\)",
    ):
        TrafficObservation(**data)


def test_malformed_timestamp_is_rejected():
    data = valid_observation_data()
    data["interval_start"] = "not-a-date"

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("average_speed_kmh", -10),
        ("travel_time_s", -5),
    ],
)
def test_negative_optional_measurements_are_rejected(
    field,
    value,
):
    data = valid_observation_data()
    data[field] = value

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


@pytest.mark.parametrize(
    "invalid_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_measurements_are_rejected(
    invalid_value,
):
    data = valid_observation_data()
    data["average_speed_kmh"] = invalid_value

    with pytest.raises(ValidationError):
        TrafficObservation(**data)


def test_description_is_preserved_exactly():
    data = valid_observation_data()
    data["description"] = "  P2-WB-L1-L-STB  "

    observation = TrafficObservation(**data)

    assert observation.description == "  P2-WB-L1-L-STB  "


def test_extra_field_is_rejected():
    data = valid_observation_data()
    data["movement_id"] = "MOV_E_W"

    with pytest.raises(ValidationError):
        TrafficObservation(**data)
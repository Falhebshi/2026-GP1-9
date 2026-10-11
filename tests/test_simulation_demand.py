import pytest
from pydantic import ValidationError

from jaadah.models.traffic import SimulationDemand

# ============================================================
# SIMULATION DEMAND TESTS
# ============================================================


def valid_demand_data():
    """Return valid RCRC-based SimulationDemand input for testing."""

    return {
        "demand_id": "DEM_001",
        "interval_start": "2026-10-10T08:00:00+03:00",
        "interval_end": "2026-10-10T08:15:00+03:00",
        "intersection_id": "INT_001",
        "movement_id": "MOV_E_W",
        "vehicle_count": 32,
        "source": "rcrc",
        "source_observation_ids": ["OBS_001"],
    }


def test_valid_rcrc_demand():
    demand = SimulationDemand(**valid_demand_data())

    assert demand.demand_id == "DEM_001"
    assert demand.intersection_id == "INT_001"
    assert demand.movement_id == "MOV_E_W"
    assert demand.vehicle_count == 32
    assert demand.source.value == "rcrc"
    assert demand.source_observation_ids == ["OBS_001"]


def test_valid_synthetic_demand():
    data = valid_demand_data()
    data["source"] = "synthetic"
    data["source_observation_ids"] = ["OBS_SYN_001"]

    demand = SimulationDemand(**data)

    assert demand.source.value == "synthetic"
    assert demand.source_observation_ids == ["OBS_SYN_001"]


def test_forecast_demand_can_have_no_observation_references():
    data = valid_demand_data()
    data["source"] = "forecast"
    data["source_observation_ids"] = []

    demand = SimulationDemand(**data)

    assert demand.source.value == "forecast"
    assert demand.source_observation_ids == []


def test_forecast_demand_can_reference_observations():
    data = valid_demand_data()
    data["source"] = "forecast"
    data["source_observation_ids"] = [
        "OBS_001",
        "OBS_002",
    ]

    demand = SimulationDemand(**data)

    assert demand.source_observation_ids == [
        "OBS_001",
        "OBS_002",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "rcrc",
        "synthetic",
    ],
)
def test_non_forecast_demand_requires_observation_reference(
    source,
):
    data = valid_demand_data()
    data["source"] = source
    data["source_observation_ids"] = []

    with pytest.raises(
        ValidationError,
        match="must reference at least one source observation",
    ):
        SimulationDemand(**data)


def test_source_observation_ids_field_is_required():
    data = valid_demand_data()
    data.pop("source_observation_ids")

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


def test_zero_vehicle_count_is_allowed():
    data = valid_demand_data()
    data["vehicle_count"] = 0

    demand = SimulationDemand(**data)

    assert demand.vehicle_count == 0


def test_negative_vehicle_count_is_rejected():
    data = valid_demand_data()
    data["vehicle_count"] = -1

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


@pytest.mark.parametrize(
    "value",
    [True, False],
)
def test_boolean_vehicle_count_is_rejected(value):
    data = valid_demand_data()
    data["vehicle_count"] = value

    with pytest.raises(
        ValidationError,
        match="vehicle_count must be an integer, not a boolean",
    ):
        SimulationDemand(**data)


def test_string_vehicle_count_is_converted_to_integer():
    data = valid_demand_data()
    data["vehicle_count"] = "32"

    demand = SimulationDemand(**data)

    assert demand.vehicle_count == 32
    assert isinstance(demand.vehicle_count, int)


def test_fractional_vehicle_count_is_rejected():
    data = valid_demand_data()
    data["vehicle_count"] = 32.5

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


def test_invalid_source_is_rejected():
    data = valid_demand_data()
    data["source"] = "manual"

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


@pytest.mark.parametrize(
    "field",
    [
        "demand_id",
        "intersection_id",
        "movement_id",
    ],
)
def test_empty_required_id_is_rejected(field):
    data = valid_demand_data()
    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        SimulationDemand(**data)


def test_required_id_whitespace_is_removed():
    data = valid_demand_data()
    data["movement_id"] = "  MOV_E_W  "

    demand = SimulationDemand(**data)

    assert demand.movement_id == "MOV_E_W"


def test_empty_source_observation_id_is_rejected():
    data = valid_demand_data()
    data["source_observation_ids"] = [
        "OBS_001",
        "   ",
    ]

    with pytest.raises(
        ValidationError,
        match="source observation ID must not be empty",
    ):
        SimulationDemand(**data)


def test_source_observation_id_whitespace_is_removed():
    data = valid_demand_data()
    data["source_observation_ids"] = [
        "  OBS_001  ",
    ]

    demand = SimulationDemand(**data)

    assert demand.source_observation_ids == [
        "OBS_001",
    ]


def test_duplicate_source_observation_ids_are_rejected():
    data = valid_demand_data()
    data["source_observation_ids"] = [
        "OBS_001",
        "OBS_001",
    ]

    with pytest.raises(
        ValidationError,
        match="must not contain duplicates",
    ):
        SimulationDemand(**data)


def test_duplicates_after_whitespace_cleanup_are_rejected():
    data = valid_demand_data()
    data["source_observation_ids"] = [
        "OBS_001",
        "  OBS_001  ",
    ]

    with pytest.raises(
        ValidationError,
        match="must not contain duplicates",
    ):
        SimulationDemand(**data)


def test_invalid_interval_is_rejected():
    data = valid_demand_data()
    data["interval_end"] = "2026-10-10T07:45:00+03:00"

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        SimulationDemand(**data)


def test_equal_interval_times_are_rejected():
    data = valid_demand_data()
    data["interval_end"] = data["interval_start"]

    with pytest.raises(
        ValidationError,
        match="interval_end must be later than interval_start",
    ):
        SimulationDemand(**data)


def test_timezone_naive_timestamp_is_rejected():
    data = valid_demand_data()
    data["interval_start"] = "2026-10-10T08:00:00"
    data["interval_end"] = "2026-10-10T08:15:00"

    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        SimulationDemand(**data)


def test_non_riyadh_timezone_is_rejected():
    data = valid_demand_data()
    data["interval_start"] = "2026-10-10T06:00:00+01:00"
    data["interval_end"] = "2026-10-10T06:15:00+01:00"

    with pytest.raises(
        ValidationError,
        match=r"timestamp must use Riyadh time \(UTC\+03:00\)",
    ):
        SimulationDemand(**data)


def test_malformed_timestamp_is_rejected():
    data = valid_demand_data()
    data["interval_start"] = "not-a-date"

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


def test_missing_required_field_is_rejected():
    data = valid_demand_data()
    data.pop("movement_id")

    with pytest.raises(ValidationError):
        SimulationDemand(**data)


def test_extra_field_is_rejected():
    data = valid_demand_data()
    data["sumo_route_id"] = "route_001"

    with pytest.raises(ValidationError):
        SimulationDemand(**data)
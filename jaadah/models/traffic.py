from datetime import datetime, timedelta
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ============================================================
# ENUMS
# ============================================================

class TrafficObservationSource(str, Enum):
    """Allowed sources for standardized traffic observations."""

    SYNTHETIC = "synthetic"
    RCRC = "rcrc"


class SimulationDemandSource(str, Enum):
    """Allowed sources for movement-level simulation demand."""

    SYNTHETIC = "synthetic"
    RCRC = "rcrc"
    FORECAST = "forecast"


# ============================================================
# TRAFFIC OBSERVATION
# ============================================================

class TrafficObservation(BaseModel):
    """
    One standardized traffic observation received through Jaadah's
    ingestion boundary.

    Represents what the source actually supplied. It does not contain
    Jaadah movement IDs or SUMO-specific IDs.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    observation_id: str
    source: TrafficObservationSource

    site_id: str
    detector_id: str

    interval_start: datetime
    interval_end: datetime

    vehicle_count: int = Field(ge=0)

    description: str | None = None
    average_speed_kmh: float | None = Field(
        default=None,
        ge=0,
    )
    travel_time_s: float | None = Field(
        default=None,
        ge=0,
    )

    @field_validator(
        "observation_id",
        "site_id",
        "detector_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "interval_start",
        "interval_end",
    )
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        """Require timestamps standardized to Riyadh time."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value

    @field_validator("vehicle_count", mode="before")
    @classmethod
    def validate_vehicle_count(cls, value):
        """Reject booleans being interpreted as vehicle counts."""

        if isinstance(value, bool):
            raise ValueError(
                "vehicle_count must be an integer, not a boolean"
            )

        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "TrafficObservation":
        """Require a positive observation interval."""

        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        return self


# ============================================================
# SIMULATION DEMAND
# ============================================================

class SimulationDemand(BaseModel):
    """
    Movement-level traffic demand that Jaadah asks SUMO to simulate.

    Represents demand after source data has been standardized,
    transformed, and mapped to Jaadah's network model. It intentionally
    contains no SUMO-specific identifiers.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    demand_id: str

    interval_start: datetime
    interval_end: datetime

    intersection_id: str
    movement_id: str

    vehicle_count: int = Field(ge=0)

    source: SimulationDemandSource
    source_observation_ids: list[str]

    @field_validator(
        "demand_id",
        "intersection_id",
        "movement_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only Jaadah identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "interval_start",
        "interval_end",
    )
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        """Require timestamps standardized to Riyadh time."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value

    @field_validator("vehicle_count", mode="before")
    @classmethod
    def validate_vehicle_count(cls, value):
        """Reject booleans being interpreted as vehicle counts."""

        if isinstance(value, bool):
            raise ValueError(
                "vehicle_count must be an integer, not a boolean"
            )

        return value

    @field_validator("source_observation_ids")
    @classmethod
    def validate_source_observation_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        """
        Normalize source observation IDs and reject empty or duplicate
        references.
        """

        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError(
                    "source observation ID must not be empty"
                )

            cleaned_values.append(value)

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError(
                "source_observation_ids must not contain duplicates"
            )

        return cleaned_values

    @model_validator(mode="after")
    def validate_demand(self) -> "SimulationDemand":
        """Validate the demand interval and provenance requirements."""

        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        if (
            self.source
            in {
                SimulationDemandSource.RCRC,
                SimulationDemandSource.SYNTHETIC,
            }
            and not self.source_observation_ids
        ):
            raise ValueError(
                f"{self.source.value} demand must reference "
                "at least one source observation"
            )

        return self
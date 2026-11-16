from datetime import datetime, timedelta
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
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


class ImputationMethod(str, Enum):
    """How the count of a detector that did not report was estimated."""

    NEIGHBOUR_REGRESSION = "neighbour_regression"
    HISTORICAL_AVERAGE = "historical_average"
    LEVEL_ADJUSTED_AVERAGE = "level_adjusted_average"


class ShareOrigin(str, Enum):
    """
    Where the ratio used to estimate an undetected movement came from.
    Only assumed ratios exist today; add a value (for example
    turning_count) when measured ratios become available.
    """

    ASSUMED = "assumed"


class ShareScenario(str, Enum):
    """Which value of an estimated ratio's range was used."""

    LOW = "low"
    CENTRAL = "central"
    HIGH = "high"


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
    occupancy_s: float | None = Field(
        default=None,
        ge=0,
    )
    occupancy_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
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
        """
        Require a positive observation interval, and occupied time no
        longer than the interval.
        """

        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        if (
            self.occupancy_s is not None
            and self.occupancy_s
            > (self.interval_end - self.interval_start).total_seconds()
        ):
            raise ValueError(
                "occupancy_s must not be longer than the interval"
            )

        return self


# ============================================================
# SIMULATION DEMAND
# ============================================================

class ImputedDetector(BaseModel):
    """A detector whose missing count was estimated for a demand."""

    model_config = ConfigDict(
        extra="forbid",
    )

    site_id: str
    detector_id: str
    method: ImputationMethod

    @field_validator(
        "site_id",
        "detector_id",
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value


class ShareEstimate(BaseModel):
    """
    How the demand of a movement without a detector was estimated: a
    ratio applied to the demand of observed movements of the same
    approach in the same interval (basis movements).

    share_origin says where the ratio came from; today every ratio is
    an assumption. basis_demand_ids are the demands it was applied to.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    ratio: float = Field(ge=0)
    scenario: ShareScenario
    share_origin: ShareOrigin
    basis_demand_ids: list[str] = Field(min_length=1)

    @field_validator("basis_demand_ids")
    @classmethod
    def validate_basis_ids(cls, values: list[str]) -> list[str]:
        """Reject empty or duplicate basis demand IDs."""

        cleaned = [value.strip() for value in values]

        if any(not value for value in cleaned):
            raise ValueError("basis demand ID must not be empty")

        if len(cleaned) != len(set(cleaned)):
            raise ValueError("basis_demand_ids must not contain duplicates")

        return cleaned


class SimulationDemand(BaseModel):
    """
    Movement-level traffic demand that Jaadah asks SUMO to simulate.

    Represents demand after source data has been standardized,
    transformed, and mapped to Jaadah's network model. It intentionally
    contains no SUMO-specific identifiers.

    The intersection is found through movement_id (Movement), not
    stored here.

    allocated_observation_ids lists the source observations whose count
    was split between movements (shared-lane detectors).
    imputed_detectors lists the detectors that did not report and whose
    count was estimated. Part of such a demand is a modelled
    assumption, not a measured count.
    share_estimate is set for a movement that no detector counts: its
    count was estimated from a ratio to other movements' demand.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    demand_id: str

    interval_start: datetime
    interval_end: datetime

    movement_id: str

    vehicle_count: int = Field(ge=0)

    source: SimulationDemandSource
    source_observation_ids: list[str]
    allocated_observation_ids: list[str] = Field(default_factory=list)
    imputed_detectors: list[ImputedDetector] = Field(default_factory=list)
    share_estimate: ShareEstimate | None = None

    @field_validator(
        "demand_id",
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

    @field_validator(
        "source_observation_ids",
        "allocated_observation_ids",
    )
    @classmethod
    def validate_observation_ids(
        cls,
        values: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        """
        Normalize observation IDs and reject empty or duplicate
        references.
        """

        label = info.field_name.removesuffix("_ids").replace("_", " ")
        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError(
                    f"{label} ID must not be empty"
                )

            cleaned_values.append(value)

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError(
                f"{info.field_name} must not contain duplicates"
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
            and not self.imputed_detectors
            and self.share_estimate is None
        ):
            raise ValueError(
                f"{self.source.value} demand must reference "
                "at least one source observation, imputed detector "
                "or share estimate"
            )

        if self.share_estimate is not None and self.source_observation_ids:
            raise ValueError(
                "a share-estimated demand has no source observations; "
                "its basis is recorded in share_estimate"
            )

        imputed_keys = [
            (detector.site_id, detector.detector_id)
            for detector in self.imputed_detectors
        ]

        if len(imputed_keys) != len(set(imputed_keys)):
            raise ValueError(
                "imputed_detectors must not contain the same detector twice"
            )

        unknown_ids = sorted(
            set(self.allocated_observation_ids)
            - set(self.source_observation_ids)
        )

        if unknown_ids:
            raise ValueError(
                "allocated observations must also be source "
                "observations: "
                + ", ".join(unknown_ids)
            )

        return self

    @computed_field
    @property
    def is_allocated(self) -> bool:
        """True when part of the count was split from a shared lane."""

        return bool(self.allocated_observation_ids)

    @computed_field
    @property
    def is_imputed(self) -> bool:
        """True when part of the count was estimated for a missing detector."""

        return bool(self.imputed_detectors)

    @computed_field
    @property
    def is_share_estimated(self) -> bool:
        """True when the movement has no detector and its count was estimated from a ratio."""

        return self.share_estimate is not None

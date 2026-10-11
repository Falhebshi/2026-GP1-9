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

class VehicleType(str, Enum):
    """Initial vehicle categories exposed by Jaadah."""

    CAR = "car"
    BUS = "bus"
    TRUCK = "truck"


# ============================================================
# VEHICLE STATE
# ============================================================

class VehicleState(BaseModel):
    """
    State of one simulated vehicle at a specific simulation time.

    Contains the application-facing geographic state used by Jaadah
    together with selected SUMO identifiers needed for traceability.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    vehicle_id: str
    scenario_id: str
    run_id: str

    simulation_time_s: float = Field(ge=0)
    timestamp: datetime

    longitude: float = Field(
        ge=-180,
        le=180,
    )
    latitude: float = Field(
        ge=-90,
        le=90,
    )

    speed_mps: float = Field(ge=0)
    heading_deg: float = Field(
        ge=0,
        lt=360,
    )

    vehicle_type: VehicleType

    sumo_edge_id: str

    z_m: float | None = None
    sumo_lane_id: str | None = None
    lane_pos_m: float | None = Field(
        default=None,
        ge=0,
    )

    vtype_id: str | None = None

    length_m: float | None = Field(
        default=None,
        gt=0,
    )
    width_m: float | None = Field(
        default=None,
        gt=0,
    )

    signals: int | None = Field(
        default=None,
        ge=0,
    )

    movement_id: str | None = None

    @field_validator(
        "vehicle_id",
        "scenario_id",
        "run_id",
        "sumo_edge_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "sumo_lane_id",
        "vtype_id",
        "movement_id",
    )
    @classmethod
    def validate_optional_ids(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value


# ============================================================
# EDGE TRAFFIC STATE
# ============================================================

class EdgeTrafficState(BaseModel):
    """
    Aggregate traffic measurements for one SUMO edge over an interval.

    These are simulation measurements, not final application KPIs.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    scenario_id: str
    run_id: str

    segment_id: str | None = None
    sumo_edge_id: str

    interval_start: datetime
    interval_end: datetime

    vehicles_entered: int = Field(ge=0)
    vehicles_left: int = Field(ge=0)

    average_speed_mps: float | None = Field(
        default=None,
        ge=0,
    )
    travel_time_s: float | None = Field(
        default=None,
        ge=0,
    )

    density: float = Field(ge=0)

    time_loss_s: float | None = Field(
        default=None,
        ge=0,
    )

    sampled_seconds: float = Field(gt=0)

    @field_validator(
        "scenario_id",
        "run_id",
        "sumo_edge_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("segment_id")
    @classmethod
    def validate_optional_segment_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "interval_start",
        "interval_end",
    )
    @classmethod
    def validate_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value

    @field_validator(
        "vehicles_entered",
        "vehicles_left",
        mode="before",
    )
    @classmethod
    def validate_vehicle_counts(cls, value):
        if isinstance(value, bool):
            raise ValueError(
                "vehicle count must be an integer, not a boolean"
            )

        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "EdgeTrafficState":
        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        return self


# ============================================================
# APPROACH TRAFFIC STATE
# ============================================================

class ApproachTrafficState(BaseModel):
    """
    Aggregate queue and delay measurements for one Jaadah approach.

    Queue measurements may use multiple SUMO lanes defined by the
    corresponding approach mapping.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    scenario_id: str
    run_id: str

    intersection_id: str
    approach_id: str

    queue_detection_lane_ids: list[str]

    interval_start: datetime
    interval_end: datetime

    max_queue_length_m: float = Field(ge=0)
    mean_max_queue_vehicles: float = Field(ge=0)

    started_halts: int = Field(ge=0)
    vehicles_seen: int = Field(ge=0)

    mean_time_loss_s: float | None = Field(
        default=None,
        ge=0,
    )

    @field_validator(
        "scenario_id",
        "run_id",
        "intersection_id",
        "approach_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("queue_detection_lane_ids")
    @classmethod
    def validate_queue_detection_lane_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError(
                    "queue detection lane ID must not be empty"
                )

            cleaned_values.append(value)

        if not cleaned_values:
            raise ValueError(
                "at least one queue detection lane ID is required"
            )

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError(
                "queue_detection_lane_ids must not contain duplicates"
            )

        return cleaned_values

    @field_validator(
        "interval_start",
        "interval_end",
    )
    @classmethod
    def validate_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value

    @field_validator(
        "started_halts",
        "vehicles_seen",
        mode="before",
    )
    @classmethod
    def validate_vehicle_counts(cls, value):
        if isinstance(value, bool):
            raise ValueError(
                "vehicle count must be an integer, not a boolean"
            )

        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "ApproachTrafficState":
        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        return self
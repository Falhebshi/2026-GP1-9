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

    Density is represented in vehicles per kilometre (veh/km),
    consistent with SUMO edgeData output.

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

    density_veh_per_km: float = Field(ge=0)
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

# ============================================================
# VEHICLE DELAY RECORD
# ============================================================

class VehicleDelayRecord(BaseModel):
    """
    One simulated vehicle's passage through the delay zone of one
    movement, in one simulation run.

    The delay zone runs from a fixed distance before the stop line to
    the point after the intersection where the vehicle is back to
    speed. Records are produced by the simulation pipeline from SUMO
    vehicle position output. Only complete passages are recorded
    here; vehicles that had not finished when the run ended are
    recorded as IncompletePassage instead, never dropped.

    zone_entry_time is when the vehicle arrived: its delay is counted
    in the interval it arrived in.
    stop_line_time is when the vehicle got through the signal: it is
    counted as served (throughput) in the interval it crossed the
    stop line.

    free_flow_travel_time_s is how long the vehicle would have taken
    through the same zone with no traffic and no signal. How it is
    obtained (one free-flow speed, or a free-flow speed per lane along
    the path) is decided by the simulation pipeline. Time loss is the
    difference between the actual and the free-flow travel time.

    Only the most specific identifiers are stored: the scenario is
    found through run_id (SimulationRun) and the approach and
    intersection through movement_id (Movement).

    These are simulation measurements, not final application KPIs.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    run_id: str
    vehicle_id: str
    movement_id: str

    zone_entry_time: datetime
    stop_line_time: datetime
    zone_exit_time: datetime

    zone_distance_m: float = Field(gt=0)
    free_flow_travel_time_s: float = Field(gt=0)

    @field_validator(
        "run_id",
        "vehicle_id",
        "movement_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "zone_entry_time",
        "stop_line_time",
        "zone_exit_time",
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

    @model_validator(mode="after")
    def validate_passage_times(self) -> "VehicleDelayRecord":
        if self.zone_exit_time <= self.zone_entry_time:
            raise ValueError(
                "zone_exit_time must be later than zone_entry_time"
            )

        if not (
            self.zone_entry_time
            <= self.stop_line_time
            <= self.zone_exit_time
        ):
            raise ValueError(
                "stop_line_time must be between "
                "zone_entry_time and zone_exit_time"
            )

        return self

    @model_validator(mode="after")
    def validate_free_flow_travel_time(self) -> "VehicleDelayRecord":
        if self.free_flow_travel_time_s > self.zone_travel_time_s:
            raise ValueError(
                "free_flow_travel_time_s cannot exceed the time "
                "spent in the zone (time loss would be negative)"
            )

        return self

    @property
    def zone_travel_time_s(self) -> float:
        """Seconds the vehicle spent inside the delay zone."""

        return (
            self.zone_exit_time - self.zone_entry_time
        ).total_seconds()

    @property
    def time_loss_s(self) -> float:
        """Seconds lost compared with free-flow travel through the zone."""

        return self.zone_travel_time_s - self.free_flow_travel_time_s


# ============================================================
# CYCLE QUEUE RECORD
# ============================================================

class CycleQueueRecord(BaseModel):
    """
    Queue measurements for one lane over one signal cycle, in one
    simulation run.

    Produced by the simulation pipeline from a lane-area detector
    whose output period is one signal cycle, aligned with the cycle
    start. The lane is identified by its Jaadah lane_id; its approach,
    position and the movements it serves come from the matching
    ApproachLane.

    Only the most specific identifiers are stored: the scenario is
    found through run_id (SimulationRun), and the approach and
    intersection through lane_id (ApproachLane, then Approach).

    These are simulation measurements, not final application KPIs.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    run_id: str
    lane_id: str

    cycle_start: datetime
    cycle_end: datetime

    max_queue_length_m: float = Field(ge=0)
    max_queue_vehicles: int = Field(ge=0)

    mean_halting_duration_s: float = Field(ge=0)
    max_halting_duration_s: float = Field(ge=0)

    @field_validator(
        "run_id",
        "lane_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "cycle_start",
        "cycle_end",
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
        "max_queue_vehicles",
        mode="before",
    )
    @classmethod
    def validate_integers(cls, value):
        if isinstance(value, bool):
            raise ValueError(
                "value must be an integer, not a boolean"
            )

        return value

    @model_validator(mode="after")
    def validate_cycle(self) -> "CycleQueueRecord":
        if self.cycle_end <= self.cycle_start:
            raise ValueError(
                "cycle_end must be later than cycle_start"
            )

        return self

    @model_validator(mode="after")
    def validate_halting_durations(self) -> "CycleQueueRecord":
        if self.mean_halting_duration_s > self.max_halting_duration_s:
            raise ValueError(
                "mean_halting_duration_s cannot exceed "
                "max_halting_duration_s"
            )

        return self

    @model_validator(mode="after")
    def validate_queue_units_agree(self) -> "CycleQueueRecord":
        has_queue_m = self.max_queue_length_m > 0
        has_queue_veh = self.max_queue_vehicles > 0

        if has_queue_m != has_queue_veh:
            raise ValueError(
                "max_queue_length_m and max_queue_vehicles must both "
                "be zero or both be greater than zero"
            )

        return self


# ============================================================
# INCOMPLETE PASSAGE
# ============================================================

class IncompletePassage(BaseModel):
    """
    A vehicle that entered the delay zone of a movement but had not
    left it when the simulation run ended.

    Recorded so that unfinished vehicles are never silently dropped:
    they are usually the most delayed ones (still queued), so leaving
    them out would make delay look better than it was. Their delay is
    unknown, so they have no time loss; the KPI engine decides how an
    interval with incomplete passages is reported.

    A vehicle that crossed the stop line before the run ended was
    served, so it still counts towards throughput.

    Only the most specific identifiers are stored: the scenario is
    found through run_id (SimulationRun) and the approach and
    intersection through movement_id (Movement).
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    run_id: str
    vehicle_id: str
    movement_id: str

    zone_entry_time: datetime
    stop_line_time: datetime | None = None
    last_seen_time: datetime

    @field_validator(
        "run_id",
        "vehicle_id",
        "movement_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "zone_entry_time",
        "stop_line_time",
        "last_seen_time",
    )
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError(
                "timestamp must use Riyadh time (UTC+03:00)"
            )

        return value

    @model_validator(mode="after")
    def validate_times(self) -> "IncompletePassage":
        if self.last_seen_time < self.zone_entry_time:
            raise ValueError(
                "last_seen_time cannot be before zone_entry_time"
            )

        if self.stop_line_time is not None and not (
            self.zone_entry_time
            <= self.stop_line_time
            <= self.last_seen_time
        ):
            raise ValueError(
                "stop_line_time must be between "
                "zone_entry_time and last_seen_time"
            )

        return self

    @property
    def crossed_stop_line(self) -> bool:
        """True if the vehicle was served before the run ended."""

        return self.stop_line_time is not None
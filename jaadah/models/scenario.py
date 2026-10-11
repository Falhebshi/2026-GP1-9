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

class TimeContext(str, Enum):
    """Traffic-time contexts supported by a Jaadah scenario."""

    HISTORICAL = "historical"
    CURRENT = "current"
    FORECAST = "forecast"


class ControlMode(str, Enum):
    """Traffic-control modes supported by a Jaadah scenario."""

    BASELINE = "baseline"
    INTERVENTION = "intervention"


class SimulationRunStatus(str, Enum):
    """Lifecycle states of a concrete simulation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================
# SCENARIO
# ============================================================

class Scenario(BaseModel):
    """
    Traffic and control context that Jaadah intends to represent.

    A Scenario defines what period and control condition are being
    represented. Concrete SUMO executions of the scenario are stored
    separately as SimulationRun objects.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    scenario_id: str
    intersection_id: str

    time_context: TimeContext
    control_mode: ControlMode

    start_time: datetime
    end_time: datetime | None = None

    reference_scenario_id: str | None = None

    @field_validator(
        "scenario_id",
        "intersection_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only required identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("reference_scenario_id")
    @classmethod
    def validate_reference_scenario_id(
        cls,
        value: str | None,
    ) -> str | None:
        """Reject a blank reference scenario ID when one is supplied."""

        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "start_time",
        "end_time",
    )
    @classmethod
    def validate_scenario_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require scenario data-time to use Riyadh time."""

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
    def validate_scenario(self) -> "Scenario":
        """Validate scenario timing and comparison requirements."""

        if (
            self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValueError(
                "end_time must be later than start_time"
            )

        if (
            self.time_context
            in {
                TimeContext.HISTORICAL,
                TimeContext.FORECAST,
            }
            and self.end_time is None
        ):
            raise ValueError(
                f"{self.time_context.value} scenario "
                "must have an end_time"
            )

        if (
            self.control_mode == ControlMode.INTERVENTION
            and self.reference_scenario_id is None
        ):
            raise ValueError(
                "intervention scenario must reference "
                "a baseline scenario"
            )

        if (
            self.control_mode == ControlMode.BASELINE
            and self.reference_scenario_id is not None
        ):
            raise ValueError(
                "baseline scenario must not reference "
                "another scenario"
            )

        if self.reference_scenario_id == self.scenario_id:
            raise ValueError(
                "scenario must not reference itself"
            )

        return self


# ============================================================
# SIMULATION RUN
# ============================================================

class SimulationRun(BaseModel):
    """
    One concrete execution of a Jaadah Scenario.

    Multiple runs may belong to the same Scenario so stochastic
    replications remain distinguishable.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    run_id: str
    scenario_id: str

    random_seed: int = Field(ge=0)

    network_version: str
    sumo_version: str

    step_length_s: float = Field(gt=0)

    started_at: datetime

    status: SimulationRunStatus

    @field_validator(
        "run_id",
        "scenario_id",
        "network_version",
        "sumo_version",
    )
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        """Reject empty or whitespace-only required strings."""

        value = value.strip()

        if not value:
            raise ValueError("value must not be empty")

        return value

    @field_validator(
        "random_seed",
        mode="before",
    )
    @classmethod
    def validate_random_seed(cls, value):
        """Reject booleans being interpreted as random seeds."""

        if isinstance(value, bool):
            raise ValueError(
                "random_seed must be an integer, not a boolean"
            )

        return value

    @field_validator(
        "step_length_s",
        mode="before",
    )
    @classmethod
    def validate_step_length(cls, value):
        """Reject booleans being interpreted as step lengths."""

        if isinstance(value, bool):
            raise ValueError(
                "step_length_s must be a number, not a boolean"
            )

        return value

    @field_validator("started_at")
    @classmethod
    def validate_started_at_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        """
        Require execution timestamps to include timezone information.

        Execution metadata may be represented in any explicit timezone;
        unlike scenario data-time, it is not restricted to UTC+03.
        """

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "started_at must include timezone information"
            )

        return value


# ============================================================
# SIMULATION CONFIGURATION
# ============================================================

class SimulationConfig(BaseModel):
    """
    Core execution configuration shared by Jaadah simulation runs.

    Values such as the initial warm-up duration remain configurable
    rather than being treated as validated traffic constants.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    simulation_duration_s: int | None = Field(
        default=None,
        gt=0,
    )

    warmup_duration_s: int = Field(
        ge=0,
    )

    @field_validator(
        "simulation_duration_s",
        "warmup_duration_s",
        mode="before",
    )
    @classmethod
    def validate_durations(cls, value):
        """Reject booleans being interpreted as durations."""

        if isinstance(value, bool):
            raise ValueError(
                "duration must be an integer, not a boolean"
            )

        return value
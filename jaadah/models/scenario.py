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

    The run records the inputs it used, so that compared runs can be
    shown to differ only in the intervention: mapping_version (the
    mapping_version of network_mappings.json), demand_sha256 (the
    fingerprint of the SimulationDemand file written by the SUMO demand
    writer) and route_file_sha256 (the fingerprint of the SUMO route
    file, which holds every planned departure). They may be missing
    while a run is pending and are required once it is running or
    completed, like started_at.
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

    mapping_version: str | None = None
    demand_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    route_file_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
    )

    started_at: datetime | None = None

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

    @field_validator("mapping_version")
    @classmethod
    def validate_mapping_version(cls, value: str | None) -> str | None:
        """Reject an empty or whitespace-only mapping version."""

        if value is None:
            return None

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
        value: datetime | None,
    ) -> datetime | None:
        """
        Require execution timestamps to include timezone information
        when a start timestamp exists.
        """
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "started_at must include timezone information"
            )

        return value

    @model_validator(mode="after")
    def validate_started_at(self) -> "SimulationRun":
        if self.status in {
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.COMPLETED,
        }:
            if self.started_at is None:
                raise ValueError(
                    "started_at is required for running and completed runs"
                )

        return self

    @model_validator(mode="after")
    def validate_recorded_inputs(self) -> "SimulationRun":
        """A run that has started must record the inputs it used."""

        if self.status in {
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.COMPLETED,
        }:
            missing = [
                name
                for name in ("mapping_version", "demand_sha256", "route_file_sha256")
                if getattr(self, name) is None
            ]

            if missing:
                raise ValueError(
                    ", ".join(missing)
                    + " required for running and completed runs"
                )

        return self


# ============================================================
# SIMULATION CONFIGURATION
# ============================================================

class SimulationConfig(BaseModel):
    """
    Core execution configuration shared by Jaadah simulation runs.

    A run is divided into three parts:

        | warm-up | analysis period | clearance |

    Vehicles are counted only if they enter the delay zone during the
    analysis period. The clearance period lets those vehicles finish
    their passage; traffic keeps arriving during it, but new arrivals
    are not counted. Vehicles that still have not finished when the
    run ends are recorded as IncompletePassage, never dropped.

    Values such as the warm-up and clearance durations remain
    configurable rather than being treated as validated traffic
    constants. Both are required so that every run states them.
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

    clearance_duration_s: int = Field(
        ge=0,
    )

    @field_validator(
        "simulation_duration_s",
        "warmup_duration_s",
        "clearance_duration_s",
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

    @model_validator(mode="after")
    def validate_analysis_period(self) -> "SimulationConfig":
        """
        Require warm-up and clearance to leave a non-empty analysis
        period when the total duration is known.
        """

        if self.simulation_duration_s is None:
            return self

        if (
            self.warmup_duration_s + self.clearance_duration_s
            >= self.simulation_duration_s
        ):
            raise ValueError(
                "warmup_duration_s + clearance_duration_s must be "
                "shorter than simulation_duration_s"
            )

        return self

# ============================================================
# REPLICATION PAIR
# ============================================================

class ReplicationPair(BaseModel):
    """
    One matched pair in a replicated experiment: a baseline run and
    an intervention run that must have used the same random seed.

    The seed itself is not stored here. SimulationRun owns the seed;
    the replication runner confirms that both runs of a pair used the
    same one.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    baseline_run_id: str
    intervention_run_id: str

    @field_validator(
        "baseline_run_id",
        "intervention_run_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only run IDs."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @model_validator(mode="after")
    def validate_distinct_runs(self) -> "ReplicationPair":
        """A pair compares two different runs."""

        if self.baseline_run_id == self.intervention_run_id:
            raise ValueError(
                "baseline_run_id and intervention_run_id "
                "must be different runs"
            )

        return self


# ============================================================
# REPLICATION SET
# ============================================================

class ReplicationSet(BaseModel):
    """
    A replicated experiment comparing an intervention scenario with
    its baseline using matched random seeds (common random numbers).

    Each pair references a baseline run and an intervention run that
    used the same seed, so differences between them come from the
    intervention rather than from random variation.

    Random seeds are owned by SimulationRun and are not repeated here.
    The replication runner, which has the SimulationRun and Scenario
    objects, confirms that both runs of each pair used the same seed,
    that each pair used a different seed, and that each run belongs
    to the stated scenario. This model checks only its own structure.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    replication_set_id: str

    baseline_scenario_id: str
    intervention_scenario_id: str

    pairs: list[ReplicationPair]

    @field_validator(
        "replication_set_id",
        "baseline_scenario_id",
        "intervention_scenario_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @model_validator(mode="after")
    def validate_replication_set(self) -> "ReplicationSet":
        """Validate the scenarios, pair count and run IDs."""

        if self.baseline_scenario_id == self.intervention_scenario_id:
            raise ValueError(
                "baseline and intervention scenarios must be different"
            )

        if len(self.pairs) < 2:
            raise ValueError(
                "a replication set needs at least two pairs "
                "(a standard deviation needs two values)"
            )

        run_ids = []

        for pair in self.pairs:
            run_ids.append(pair.baseline_run_id)
            run_ids.append(pair.intervention_run_id)

        if len(run_ids) != len(set(run_ids)):
            raise ValueError(
                "each run may appear only once in a replication set"
            )

        return self

    @property
    def replication_count(self) -> int:
        """Number of matched pairs in the experiment."""

        return len(self.pairs)

    @property
    def baseline_run_ids(self) -> list[str]:
        """Baseline run IDs, in pair order."""

        return [pair.baseline_run_id for pair in self.pairs]

    @property
    def intervention_run_ids(self) -> list[str]:
        """Intervention run IDs, in pair order."""

        return [pair.intervention_run_id for pair in self.pairs]
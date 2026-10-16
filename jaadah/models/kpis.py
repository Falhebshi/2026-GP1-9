from datetime import datetime, timedelta
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


# ============================================================
# ENUMS
# ============================================================

class KpiName(str, Enum):
    """The finalized KPIs calculated by the Jaadah KPI engine."""

    CONTROL_DELAY = "control_delay"
    LEVEL_OF_SERVICE = "level_of_service"
    VOLUME_TO_CAPACITY_RATIO = "volume_to_capacity_ratio"
    CAPACITY = "capacity"
    SATURATION_FLOW_RATE = "saturation_flow_rate"
    QUEUE_LENGTH = "queue_length"
    QUEUE_DURATION = "queue_duration"
    QUEUE_STORAGE_RATIO = "queue_storage_ratio"
    THROUGHPUT = "throughput"


class KpiLevel(str, Enum):
    """
    The network level a KPI result describes.

    LANE and LANE_GROUP hold KPIs that are measured per lane (queues)
    or calculated per lane group (HCM capacity measures), which cannot
    be split between the movements of a shared lane.
    """

    LANE = "lane"
    LANE_GROUP = "lane_group"
    MOVEMENT = "movement"
    APPROACH = "approach"
    INTERSECTION = "intersection"


class KpiUnit(str, Enum):
    """Units in which KPI results are reported."""

    SECONDS_PER_VEHICLE = "s/veh"
    VEHICLES_PER_HOUR = "veh/h"
    VEHICLES_PER_HOUR_PER_LANE = "veh/h/lane"
    RATIO = "ratio"
    METRES = "m"
    VEHICLES = "veh"
    SECONDS = "s"
    GRADE = "grade"


class KpiStatus(str, Enum):
    """
    Whether a KPI result holds a value.

    NOT_APPLICABLE: the KPI does not apply to this element
    (e.g. level of service for an uncontrolled right turn).
    UNAVAILABLE: the KPI applies but required data is missing.
    """

    OK = "ok"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class KpiMethod(str, Enum):
    """How a KPI value was obtained."""

    HCM = "hcm"
    SIMULATION = "simulation"


class ValueComputation(str, Enum):
    """
    How the final KPI value was computed from its inputs.

    DIRECT_SUMMARY: a direct summary of SUMO measurements (a mean,
    maximum, percentile or count) with no traffic formula applied.
    DERIVED: calculated by Jaadah with a formula or model
    (e.g. HCM capacity, v/c ratio, level of service).

    This is separate from KpiMethod: a simulation-method result can be
    DERIVED (e.g. simulation-based LOS is graded from simulated delay).
    """

    DIRECT_SUMMARY = "direct_summary"
    DERIVED = "derived"


class InputOrigin(str, Enum):
    """
    Where the inputs behind a KPI value come from, traced back to
    their source. A value may combine inputs of several origins.
    """

    OBSERVED = "observed"
    MODELLED_ASSUMPTION = "modelled_assumption"
    SIMULATED = "simulated"


class LevelOfServiceGrade(str, Enum):
    """HCM level-of-service grades."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


# Units each KPI may be reported in (backlog requirement 37).
ALLOWED_KPI_UNITS: dict[KpiName, set[KpiUnit]] = {
    KpiName.CONTROL_DELAY: {KpiUnit.SECONDS_PER_VEHICLE},
    KpiName.LEVEL_OF_SERVICE: {KpiUnit.GRADE},
    KpiName.VOLUME_TO_CAPACITY_RATIO: {KpiUnit.RATIO},
    KpiName.CAPACITY: {KpiUnit.VEHICLES_PER_HOUR},
    KpiName.SATURATION_FLOW_RATE: {
        KpiUnit.VEHICLES_PER_HOUR,
        KpiUnit.VEHICLES_PER_HOUR_PER_LANE,
    },
    KpiName.QUEUE_LENGTH: {KpiUnit.METRES, KpiUnit.VEHICLES},
    KpiName.QUEUE_DURATION: {KpiUnit.SECONDS},
    KpiName.QUEUE_STORAGE_RATIO: {KpiUnit.RATIO},
    KpiName.THROUGHPUT: {KpiUnit.VEHICLES_PER_HOUR},
}


# How each supported (KPI, method) pair computes its final value.
# A pair that is not listed here is not a supported KPI result.
VALUE_COMPUTATIONS: dict[tuple[KpiName, KpiMethod], ValueComputation] = {
    # Simulation-based results
    (KpiName.CONTROL_DELAY, KpiMethod.SIMULATION): ValueComputation.DIRECT_SUMMARY,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.SIMULATION): ValueComputation.DERIVED,
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.SIMULATION): ValueComputation.DIRECT_SUMMARY,
    (KpiName.QUEUE_LENGTH, KpiMethod.SIMULATION): ValueComputation.DIRECT_SUMMARY,
    (KpiName.QUEUE_DURATION, KpiMethod.SIMULATION): ValueComputation.DIRECT_SUMMARY,
    (KpiName.QUEUE_STORAGE_RATIO, KpiMethod.SIMULATION): ValueComputation.DERIVED,
    (KpiName.THROUGHPUT, KpiMethod.SIMULATION): ValueComputation.DIRECT_SUMMARY,
    # HCM results
    (KpiName.CONTROL_DELAY, KpiMethod.HCM): ValueComputation.DERIVED,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.HCM): ValueComputation.DERIVED,
    (KpiName.VOLUME_TO_CAPACITY_RATIO, KpiMethod.HCM): ValueComputation.DERIVED,
    (KpiName.CAPACITY, KpiMethod.HCM): ValueComputation.DERIVED,
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.HCM): ValueComputation.DERIVED,
}


_PER_ELEMENT = {KpiLevel.MOVEMENT, KpiLevel.APPROACH, KpiLevel.INTERSECTION}

# Levels at which each (KPI, method) pair may be reported. Per-vehicle
# KPIs split cleanly by movement; per-lane and per-lane-group KPIs are
# also reported on their lane or lane group (shared-lane decision,
# 17 Oct). Every key of VALUE_COMPUTATIONS appears here.
ALLOWED_KPI_LEVELS: dict[tuple[KpiName, KpiMethod], set[KpiLevel]] = {
    # Simulation-based results
    (KpiName.CONTROL_DELAY, KpiMethod.SIMULATION): _PER_ELEMENT,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.SIMULATION): _PER_ELEMENT,
    (KpiName.THROUGHPUT, KpiMethod.SIMULATION): _PER_ELEMENT,
    (KpiName.QUEUE_DURATION, KpiMethod.SIMULATION): _PER_ELEMENT,
    (KpiName.QUEUE_LENGTH, KpiMethod.SIMULATION): {KpiLevel.LANE} | _PER_ELEMENT,
    (KpiName.QUEUE_STORAGE_RATIO, KpiMethod.SIMULATION): {KpiLevel.LANE} | _PER_ELEMENT,
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.SIMULATION): {KpiLevel.LANE},
    # HCM results
    (KpiName.CONTROL_DELAY, KpiMethod.HCM): {KpiLevel.LANE_GROUP} | _PER_ELEMENT,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.HCM): {KpiLevel.LANE_GROUP} | _PER_ELEMENT,
    (KpiName.VOLUME_TO_CAPACITY_RATIO, KpiMethod.HCM): {KpiLevel.LANE_GROUP} | _PER_ELEMENT,
    (KpiName.CAPACITY, KpiMethod.HCM): {
        KpiLevel.LANE_GROUP,
        KpiLevel.MOVEMENT,
        KpiLevel.APPROACH,
    },
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.HCM): {
        KpiLevel.LANE_GROUP,
        KpiLevel.MOVEMENT,
    },
}


# ============================================================
# KPI RESULT
# ============================================================

class KpiResult(BaseModel):
    """
    One KPI value for one element (movement, approach or
    intersection), one interval, and one run or set of runs.

    A missing value is never represented as zero: results without
    a value carry status UNAVAILABLE or NOT_APPLICABLE and a reason.

    When run_ids holds more than one run (a replicated experiment),
    value is the mean across the runs and standard_deviation is
    the spread between them. HCM results may have no runs at all.

    A movement result taken from a shared lane or lane group names it
    in measured_on_lane_id or measured_on_lane_group_id; the dashboard
    shows such values with a "Shared lane" tag (is_shared_value).

    value_computation, replication_count and is_shared_value are
    computed fields: they appear in model_dump() and JSON output but
    cannot be passed in. For storage, dump with exclude= those three
    names; otherwise reloading the dump fails, because extra fields
    are forbidden.

    The element is identified by exactly one ID, matching the level:
    lane_id, lane_group_id, movement_id, approach_id or
    intersection_id. Lane-group IDs are stable names derived from the
    lane layout (e.g. east_LT). Its parents (e.g. the
    approach of a movement) are looked up in the network models, not
    repeated here. scenario_id is always stored: the result belongs
    to a scenario, while run_ids only lists the executions it
    summarizes.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    kpi: KpiName
    level: KpiLevel

    lane_id: str | None = None
    lane_group_id: str | None = None
    movement_id: str | None = None
    approach_id: str | None = None
    intersection_id: str | None = None

    measured_on_lane_id: str | None = None
    measured_on_lane_group_id: str | None = None

    interval_start: datetime
    interval_end: datetime

    value: float | None = Field(
        default=None,
        ge=0,
    )
    los_grade: LevelOfServiceGrade | None = None
    unit: KpiUnit

    status: KpiStatus
    reason: str | None = None

    method: KpiMethod
    input_origins: list[InputOrigin] = Field(default_factory=list)

    scenario_id: str
    run_ids: list[str] = Field(default_factory=list)

    standard_deviation: float | None = Field(
        default=None,
        ge=0,
    )

    @field_validator("scenario_id")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator(
        "lane_id",
        "lane_group_id",
        "movement_id",
        "approach_id",
        "intersection_id",
        "measured_on_lane_id",
        "measured_on_lane_group_id",
        "reason",
    )
    @classmethod
    def validate_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("value must not be empty")

        return value

    @field_validator("run_ids")
    @classmethod
    def validate_run_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError("run ID must not be empty")

            cleaned_values.append(value)

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError("run_ids must not contain duplicates")

        return cleaned_values

    @field_validator("input_origins")
    @classmethod
    def validate_input_origins(
        cls,
        values: list[InputOrigin],
    ) -> list[InputOrigin]:
        if len(values) != len(set(values)):
            raise ValueError(
                "input_origins must not contain duplicates"
            )

        return values

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

    @model_validator(mode="after")
    def validate_interval(self) -> "KpiResult":
        if self.interval_end <= self.interval_start:
            raise ValueError(
                "interval_end must be later than interval_start"
            )

        return self

    @model_validator(mode="after")
    def validate_level_ids(self) -> "KpiResult":
        ids = {
            KpiLevel.LANE: self.lane_id,
            KpiLevel.LANE_GROUP: self.lane_group_id,
            KpiLevel.MOVEMENT: self.movement_id,
            KpiLevel.APPROACH: self.approach_id,
            KpiLevel.INTERSECTION: self.intersection_id,
        }

        if ids[self.level] is None:
            raise ValueError(
                f"{self.level.value}-level results require "
                f"{self.level.value}_id"
            )

        for level, element_id in ids.items():
            if level != self.level and element_id is not None:
                raise ValueError(
                    f"{self.level.value}-level results must not have "
                    f"{level.value}_id (parents are looked up, "
                    "not repeated)"
                )

        return self

    @model_validator(mode="after")
    def validate_unit(self) -> "KpiResult":
        if self.unit not in ALLOWED_KPI_UNITS[self.kpi]:
            raise ValueError(
                f"unit '{self.unit.value}' is not allowed "
                f"for {self.kpi.value}"
            )

        return self

    @model_validator(mode="after")
    def validate_status_and_value(self) -> "KpiResult":
        is_grade = self.kpi == KpiName.LEVEL_OF_SERVICE

        if is_grade and self.value is not None:
            raise ValueError(
                "level_of_service uses los_grade, not value"
            )

        if not is_grade and self.los_grade is not None:
            raise ValueError(
                "los_grade is only allowed for level_of_service"
            )

        has_result = (
            self.los_grade is not None
            if is_grade
            else self.value is not None
        )

        if self.status == KpiStatus.OK:
            if not has_result:
                raise ValueError(
                    "a result with status 'ok' must have a value"
                )

        else:
            if has_result or self.standard_deviation is not None:
                raise ValueError(
                    f"a result with status '{self.status.value}' "
                    "must not have a value"
                )

            if self.reason is None:
                raise ValueError(
                    f"a result with status '{self.status.value}' "
                    "requires a reason"
                )

        return self

    @model_validator(mode="after")
    def validate_method(self) -> "KpiResult":
        if (self.kpi, self.method) not in VALUE_COMPUTATIONS:
            raise ValueError(
                f"{self.kpi.value} is not calculated "
                f"with the {self.method.value} method"
            )

        return self

    @model_validator(mode="after")
    def validate_level_allowed(self) -> "KpiResult":
        allowed = ALLOWED_KPI_LEVELS.get((self.kpi, self.method), set())

        if self.level not in allowed:
            raise ValueError(
                f"{self.kpi.value} ({self.method.value}) is not "
                f"reported at {self.level.value} level"
            )

        return self

    @model_validator(mode="after")
    def validate_shared_marker(self) -> "KpiResult":
        """
        A movement result whose value was measured on a shared lane or
        lane group records where. The lane, its position and the other
        movements using it are looked up from ApproachLane.
        """

        lane = self.measured_on_lane_id
        group = self.measured_on_lane_group_id

        if lane is None and group is None:
            return self

        if self.level != KpiLevel.MOVEMENT:
            raise ValueError(
                "measured_on_lane_id and measured_on_lane_group_id "
                "are only used on movement-level results"
            )

        if lane is not None and group is not None:
            raise ValueError(
                "a result is measured on a lane or a lane group, "
                "not both"
            )

        allowed = ALLOWED_KPI_LEVELS.get((self.kpi, self.method), set())
        needed = KpiLevel.LANE if lane is not None else KpiLevel.LANE_GROUP

        if needed not in allowed:
            raise ValueError(
                f"{self.kpi.value} ({self.method.value}) is not "
                f"measured on a {needed.value.replace('_', ' ')}"
            )

        return self

    @model_validator(mode="after")
    def validate_runs_for_method(self) -> "KpiResult":
        """
        Simulation results summarize at least one run. HCM results may
        be calculated without running SUMO, so they may have none.
        """

        if self.method == KpiMethod.SIMULATION and not self.run_ids:
            raise ValueError(
                "simulation-based results require at least one run ID"
            )

        return self

    @model_validator(mode="after")
    def validate_origins(self) -> "KpiResult":
        if self.status != KpiStatus.OK:
            if self.input_origins:
                raise ValueError(
                    "a result without a value must not have "
                    "input_origins"
                )

            return self

        if not self.input_origins:
            raise ValueError(
                "a result with status 'ok' requires "
                "at least one input origin"
            )

        if (
            self.method == KpiMethod.SIMULATION
            and InputOrigin.SIMULATED not in self.input_origins
        ):
            raise ValueError(
                "a simulation-based result must include "
                "'simulated' in input_origins"
            )

        return self

    @model_validator(mode="after")
    def validate_replication(self) -> "KpiResult":
        is_replicated = len(self.run_ids) > 1

        if not is_replicated and self.standard_deviation is not None:
            raise ValueError(
                "standard_deviation requires more than one run"
            )

        if self.kpi == KpiName.LEVEL_OF_SERVICE:
            if self.standard_deviation is not None:
                raise ValueError(
                    "level_of_service has no standard deviation"
                )

        elif (
            is_replicated
            and self.status == KpiStatus.OK
            and self.standard_deviation is None
        ):
            raise ValueError(
                "replicated results with status 'ok' "
                "require standard_deviation"
            )

        return self

    @computed_field
    @property
    def replication_count(self) -> int:
        """Number of simulation runs this result summarizes (0 for HCM)."""

        return len(self.run_ids)

    @computed_field
    @property
    def value_computation(self) -> ValueComputation | None:
        """
        How the value was computed, looked up from VALUE_COMPUTATIONS.
        None when the result has no value.
        """

        if self.status != KpiStatus.OK:
            return None

        return VALUE_COMPUTATIONS[(self.kpi, self.method)]

    @computed_field
    @property
    def is_shared_value(self) -> bool:
        """True for a movement value taken from a shared lane or lane group."""

        return (
            self.measured_on_lane_id is not None
            or self.measured_on_lane_group_id is not None
        )
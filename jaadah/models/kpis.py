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
    """The network level a KPI result describes."""

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


class ValueOrigin(str, Enum):
    """
    How a KPI value itself was produced.

    SIMULATED: a direct summary of SUMO measurements (a mean, maximum,
    percentile or count) with no traffic formula applied.
    DERIVED: calculated by Jaadah with a formula or model
    (e.g. HCM capacity, v/c ratio, level of service).
    """

    SIMULATED = "simulated"
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


# How each supported (KPI, method) pair produces its value.
# A pair that is not listed here is not a supported KPI result.
VALUE_ORIGINS: dict[tuple[KpiName, KpiMethod], ValueOrigin] = {
    # Simulation-based results
    (KpiName.CONTROL_DELAY, KpiMethod.SIMULATION): ValueOrigin.SIMULATED,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.SIMULATION): ValueOrigin.DERIVED,
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.SIMULATION): ValueOrigin.SIMULATED,
    (KpiName.QUEUE_LENGTH, KpiMethod.SIMULATION): ValueOrigin.SIMULATED,
    (KpiName.QUEUE_DURATION, KpiMethod.SIMULATION): ValueOrigin.SIMULATED,
    (KpiName.QUEUE_STORAGE_RATIO, KpiMethod.SIMULATION): ValueOrigin.DERIVED,
    (KpiName.THROUGHPUT, KpiMethod.SIMULATION): ValueOrigin.SIMULATED,
    # HCM results
    (KpiName.CONTROL_DELAY, KpiMethod.HCM): ValueOrigin.DERIVED,
    (KpiName.LEVEL_OF_SERVICE, KpiMethod.HCM): ValueOrigin.DERIVED,
    (KpiName.VOLUME_TO_CAPACITY_RATIO, KpiMethod.HCM): ValueOrigin.DERIVED,
    (KpiName.CAPACITY, KpiMethod.HCM): ValueOrigin.DERIVED,
    (KpiName.SATURATION_FLOW_RATE, KpiMethod.HCM): ValueOrigin.DERIVED,
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
    the spread between them.

    The element is identified by exactly one ID, matching the level:
    movement_id, approach_id or intersection_id. Its parents (e.g. the
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

    intersection_id: str | None = None
    approach_id: str | None = None
    movement_id: str | None = None

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
    run_ids: list[str]

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
        "intersection_id",
        "approach_id",
        "movement_id",
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

        if not cleaned_values:
            raise ValueError("at least one run ID is required")

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
        if (self.kpi, self.method) not in VALUE_ORIGINS:
            raise ValueError(
                f"{self.kpi.value} is not calculated "
                f"with the {self.method.value} method"
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

    @property
    def replication_count(self) -> int:
        """Number of simulation runs this result summarizes."""

        return len(self.run_ids)

    @property
    def value_origin(self) -> ValueOrigin | None:
        """
        How the value was produced, looked up from VALUE_ORIGINS.
        None when the result has no value.
        """

        if self.status != KpiStatus.OK:
            return None

        return VALUE_ORIGINS[(self.kpi, self.method)]
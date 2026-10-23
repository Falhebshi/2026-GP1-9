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

from .scenario import ReplicationPair


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


class UncontrolledMovements(str, Enum):
    """
    Whether an approach or intersection value covers the uncontrolled
    right-turn slips (docs/kpi_engine.md section 11.3). Simulation
    results include them; HCM results exclude them, because a slip
    has no lane group. The dashboard shows it as a tag.
    """

    INCLUDED = "included"
    EXCLUDED = "excluded"


# The only tag each method can carry: measured values always include
# the slips, HCM values always exclude them.
UNCONTROLLED_TAG_BY_METHOD: dict[KpiMethod, UncontrolledMovements] = {
    KpiMethod.SIMULATION: UncontrolledMovements.INCLUDED,
    KpiMethod.HCM: UncontrolledMovements.EXCLUDED,
}


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

    An approach or intersection result whose element has uncontrolled
    right-turn slips says whether its value includes or excludes them
    in uncontrolled_movements (None when the element has no slip).

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
    uncontrolled_movements: UncontrolledMovements | None = None

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
    def validate_uncontrolled_tag(self) -> "KpiResult":
        """
        The slip tag describes a combined value: approach or
        intersection level, status 'ok', and the one tag its method
        can carry.
        """

        tag = self.uncontrolled_movements

        if tag is None:
            return self

        if self.level not in {KpiLevel.APPROACH, KpiLevel.INTERSECTION}:
            raise ValueError(
                "uncontrolled_movements is only used on approach and "
                "intersection results"
            )

        if self.status != KpiStatus.OK:
            raise ValueError(
                "a result without a value must not have "
                "uncontrolled_movements"
            )

        if tag != UNCONTROLLED_TAG_BY_METHOD[self.method]:
            raise ValueError(
                f"{self.method.value} results cannot be "
                f"'{tag.value}' for uncontrolled movements"
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


# ============================================================
# KPI COMPARISON
# ============================================================

class KpiComparison(BaseModel):
    """
    The change in one KPI for one element and one interval between a
    baseline and an intervention scenario (docs/kpi_engine.md
    section 12).

    Simulation comparisons use matched pairs from a ReplicationSet:
    mean_change is the mean of the per-pair differences (intervention
    minus baseline) over used_pairs, and standard_deviation is their
    spread. A negative change in delay or queue is an improvement.
    baseline_mean is the baseline mean over the same pairs, the
    denominator of percent_change.

    HCM comparisons have no runs: used_pairs and replication_set_id
    are empty, and mean_change is the plain difference.

    pair_count is the number of pairs in the ReplicationSet (simulation
    comparisons only). When fewer pairs were used, is_partial_sample is
    true: the comparison's baseline values can then differ from the
    baseline scenario's own results, which use all its runs. pair_count
    repeats a fact of the ReplicationSet on purpose, so the dashboard
    can show "based on 1 of 3 matched runs" without a lookup; the KPI
    engine fills it from the set.

    Level of service is a letter, so it has no change: a comparison of
    LOS holds baseline_los_grade and intervention_los_grade instead.

    Both scenario IDs are always stored (as KpiResult keeps
    scenario_id): an HCM comparison has no ReplicationSet to look
    them up from. For simulation comparisons the KPI engine checks
    that they agree with the ReplicationSet.

    percent_change and is_partial_sample are computed fields. For
    storage, dump with exclude={"percent_change", "is_partial_sample"};
    otherwise reloading the dump fails, because extra fields are
    forbidden.
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

    interval_start: datetime
    interval_end: datetime

    unit: KpiUnit
    method: KpiMethod

    baseline_scenario_id: str
    intervention_scenario_id: str
    replication_set_id: str | None = None
    used_pairs: list[ReplicationPair] = Field(default_factory=list)
    pair_count: int | None = Field(default=None, ge=1)

    status: KpiStatus
    reason: str | None = None

    mean_change: float | None = None
    standard_deviation: float | None = Field(default=None, ge=0)
    baseline_mean: float | None = Field(default=None, ge=0)

    baseline_los_grade: LevelOfServiceGrade | None = None
    intervention_los_grade: LevelOfServiceGrade | None = None

    input_origins: list[InputOrigin] = Field(default_factory=list)
    uncontrolled_movements: UncontrolledMovements | None = None

    @field_validator("baseline_scenario_id", "intervention_scenario_id")
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
        "replication_set_id",
        "reason",
    )
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("value must not be empty")

        return value

    @field_validator("input_origins")
    @classmethod
    def validate_input_origins(
        cls,
        values: list[InputOrigin],
    ) -> list[InputOrigin]:
        if len(values) != len(set(values)):
            raise ValueError("input_origins must not contain duplicates")

        return values

    @field_validator("pair_count", mode="before")
    @classmethod
    def validate_pair_count(cls, value):
        """Reject booleans being interpreted as a number of pairs."""

        if isinstance(value, bool):
            raise ValueError("pair_count must be an integer, not a boolean")

        return value

    @field_validator("interval_start", "interval_end")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")

        if value.utcoffset() != timedelta(hours=3):
            raise ValueError("timestamp must use Riyadh time (UTC+03:00)")

        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "KpiComparison":
        if self.interval_end <= self.interval_start:
            raise ValueError("interval_end must be later than interval_start")

        return self

    @model_validator(mode="after")
    def validate_scenarios(self) -> "KpiComparison":
        if self.baseline_scenario_id == self.intervention_scenario_id:
            raise ValueError(
                "baseline and intervention scenarios must be different"
            )

        return self

    @model_validator(mode="after")
    def validate_level_ids(self) -> "KpiComparison":
        ids = {
            KpiLevel.LANE: self.lane_id,
            KpiLevel.LANE_GROUP: self.lane_group_id,
            KpiLevel.MOVEMENT: self.movement_id,
            KpiLevel.APPROACH: self.approach_id,
            KpiLevel.INTERSECTION: self.intersection_id,
        }

        if ids[self.level] is None:
            raise ValueError(
                f"{self.level.value}-level comparisons require "
                f"{self.level.value}_id"
            )

        for level, element_id in ids.items():
            if level != self.level and element_id is not None:
                raise ValueError(
                    f"{self.level.value}-level comparisons must not have "
                    f"{level.value}_id"
                )

        return self

    @model_validator(mode="after")
    def validate_kpi_definition(self) -> "KpiComparison":
        """Unit, method and level follow the same tables as KpiResult."""

        if self.unit not in ALLOWED_KPI_UNITS[self.kpi]:
            raise ValueError(
                f"unit '{self.unit.value}' is not allowed for {self.kpi.value}"
            )

        if (self.kpi, self.method) not in VALUE_COMPUTATIONS:
            raise ValueError(
                f"{self.kpi.value} is not calculated "
                f"with the {self.method.value} method"
            )

        if self.level not in ALLOWED_KPI_LEVELS[(self.kpi, self.method)]:
            raise ValueError(
                f"{self.kpi.value} ({self.method.value}) is not "
                f"reported at {self.level.value} level"
            )

        return self

    @model_validator(mode="after")
    def validate_pairs_for_method(self) -> "KpiComparison":
        """
        Simulation comparisons come from a ReplicationSet; HCM
        comparisons have no runs.
        """

        if self.method == KpiMethod.SIMULATION:
            if self.replication_set_id is None:
                raise ValueError(
                    "simulation comparisons require a replication_set_id"
                )

            if self.pair_count is None:
                raise ValueError(
                    "simulation comparisons require a pair_count"
                )

            if self.status == KpiStatus.OK and not self.used_pairs:
                raise ValueError(
                    "a simulation comparison with status 'ok' "
                    "requires at least one used pair"
                )

            if len(self.used_pairs) > self.pair_count:
                raise ValueError(
                    "used_pairs cannot hold more pairs than pair_count"
                )

        elif (
            self.replication_set_id is not None
            or self.used_pairs
            or self.pair_count is not None
        ):
            raise ValueError(
                "HCM comparisons have no replication set or pairs"
            )

        if self.status != KpiStatus.OK and self.used_pairs:
            raise ValueError(
                "a comparison without a value must not list used pairs"
            )

        run_ids = [
            run_id
            for pair in self.used_pairs
            for run_id in (pair.baseline_run_id, pair.intervention_run_id)
        ]

        if len(run_ids) != len(set(run_ids)):
            raise ValueError("each run may appear only once in used_pairs")

        return self

    @model_validator(mode="after")
    def validate_status_and_values(self) -> "KpiComparison":
        is_grade = self.kpi == KpiName.LEVEL_OF_SERVICE
        numbers = (self.mean_change, self.standard_deviation, self.baseline_mean)
        grades = (self.baseline_los_grade, self.intervention_los_grade)

        if self.status != KpiStatus.OK:
            if any(v is not None for v in numbers + grades):
                raise ValueError(
                    f"a comparison with status '{self.status.value}' "
                    "must not have a value"
                )

            if self.reason is None:
                raise ValueError(
                    f"a comparison with status '{self.status.value}' "
                    "requires a reason"
                )

            return self

        if is_grade:
            if any(v is not None for v in numbers):
                raise ValueError(
                    "level_of_service comparisons hold the two grades, "
                    "not a numeric change"
                )

            if any(g is None for g in grades):
                raise ValueError(
                    "a level_of_service comparison with status 'ok' "
                    "requires both grades"
                )

            return self

        if any(g is not None for g in grades):
            raise ValueError("grades are only allowed for level_of_service")

        if self.mean_change is None or self.baseline_mean is None:
            raise ValueError(
                "a comparison with status 'ok' requires mean_change "
                "and baseline_mean"
            )

        if self.baseline_mean + self.mean_change < -1e-9:
            raise ValueError(
                "the intervention mean (baseline_mean + mean_change) "
                "must not be negative"
            )

        replicated = len(self.used_pairs) > 1

        if replicated and self.standard_deviation is None:
            raise ValueError(
                "comparisons over more than one pair require "
                "standard_deviation"
            )

        if not replicated and self.standard_deviation is not None:
            raise ValueError(
                "standard_deviation requires more than one pair"
            )

        return self

    @model_validator(mode="after")
    def validate_origins(self) -> "KpiComparison":
        if self.status != KpiStatus.OK:
            if self.input_origins:
                raise ValueError(
                    "a comparison without a value must not have input_origins"
                )

            return self

        if not self.input_origins:
            raise ValueError(
                "a comparison with status 'ok' requires "
                "at least one input origin"
            )

        if (
            self.method == KpiMethod.SIMULATION
            and InputOrigin.SIMULATED not in self.input_origins
        ):
            raise ValueError(
                "a simulation-based comparison must include "
                "'simulated' in input_origins"
            )

        return self

    @model_validator(mode="after")
    def validate_uncontrolled_tag(self) -> "KpiComparison":
        tag = self.uncontrolled_movements

        if tag is None:
            return self

        if self.level not in {KpiLevel.APPROACH, KpiLevel.INTERSECTION}:
            raise ValueError(
                "uncontrolled_movements is only used on approach and "
                "intersection comparisons"
            )

        if self.status != KpiStatus.OK:
            raise ValueError(
                "a comparison without a value must not have "
                "uncontrolled_movements"
            )

        if tag != UNCONTROLLED_TAG_BY_METHOD[self.method]:
            raise ValueError(
                f"{self.method.value} comparisons cannot be "
                f"'{tag.value}' for uncontrolled movements"
            )

        return self

    @computed_field
    @property
    def percent_change(self) -> float | None:
        """
        mean_change as a percentage of baseline_mean (e.g. -10.0 for a
        10 % reduction). None without a value, for level of service,
        and when the baseline mean is 0 (no percentage of zero).
        """

        if self.mean_change is None or not self.baseline_mean:
            return None

        return 100 * self.mean_change / self.baseline_mean

    @computed_field
    @property
    def is_partial_sample(self) -> bool:
        """
        True when a simulation comparison with a value used fewer pairs
        than the ReplicationSet holds (the dashboard's "based on 1 of 3
        matched runs" tag).
        """

        return (
            self.status == KpiStatus.OK
            and self.pair_count is not None
            and len(self.used_pairs) < self.pair_count
        )

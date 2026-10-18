from datetime import datetime, timedelta
from enum import Enum
from math import isclose

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

class SignalControlType(str, Enum):
    """Signal-control strategies currently supported by Jaadah."""

    FIXED_TIME = "fixed_time"


class SignalProgramSource(str, Enum):
    """Origin of a Jaadah signal program."""

    OBSERVED = "observed"
    BASELINE_MODEL = "baseline_model"
    INTERVENTION = "intervention"


class SignalIndication(str, Enum):
    """Movement-level signal indications exposed by Jaadah."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# ============================================================
# SIGNAL PHASE
# ============================================================

class SignalPhase(BaseModel):
    """
    One engineering-level phase within a Jaadah signal program.

    A phase identifies which canonical movements are served and
    records its green, yellow, and all-red durations.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    phase_id: str
    sequence_order: int = Field(ge=0)

    served_movement_ids: list[str]

    green_time_s: float = Field(gt=0)
    yellow_time_s: float = Field(ge=0)
    all_red_time_s: float = Field(ge=0)

    @field_validator("phase_id")
    @classmethod
    def validate_phase_id(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("served_movement_ids")
    @classmethod
    def validate_served_movement_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError(
                    "served movement ID must not be empty"
                )

            cleaned_values.append(value)

        if not cleaned_values:
            raise ValueError(
                "at least one served movement ID is required"
            )

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError(
                "served_movement_ids must not contain duplicates"
            )

        return cleaned_values

    @field_validator("sequence_order", mode="before")
    @classmethod
    def validate_sequence_order(cls, value):
        if isinstance(value, bool):
            raise ValueError(
                "sequence_order must be an integer, not a boolean"
            )

        return value


# ============================================================
# SIGNAL PROGRAM
# ============================================================

class SignalProgram(BaseModel):
    """
    Signal-control program associated with a Jaadah scenario.

    The model exposes engineering-level phase information while the
    raw SUMO traffic-light representation remains an adapter concern.

    Jaadah currently models signal phases as sequential, non-overlapping
    phases. Concurrent or overlapping phase execution is not represented
    by this canonical model.

    The intersection is found through scenario_id (Scenario), not
    stored here.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    signal_program_id: str
    scenario_id: str

    control_type: SignalControlType

    cycle_length_s: float = Field(gt=0)

    phases: list[SignalPhase]

    source: SignalProgramSource

    @field_validator(
        "signal_program_id",
        "scenario_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("phases")
    @classmethod
    def validate_phases(
        cls,
        values: list[SignalPhase],
    ) -> list[SignalPhase]:
        if not values:
            raise ValueError(
                "signal program must contain at least one phase"
            )

        phase_ids = [
            phase.phase_id
            for phase in values
        ]

        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError(
                "phase IDs must be unique within a signal program"
            )

        sequence_orders = [
            phase.sequence_order
            for phase in values
        ]

        if len(sequence_orders) != len(set(sequence_orders)):
            raise ValueError(
                "sequence_order values must be unique "
                "within a signal program"
            )

        return values

    @model_validator(mode="after")
    def validate_cycle_length(self) -> "SignalProgram":
        """
        Require the declared cycle length to match the total duration
        of all sequential phases in the signal program.
        """

        total_phase_time = sum(
            phase.green_time_s
            + phase.yellow_time_s
            + phase.all_red_time_s
            for phase in self.phases
        )

        if not isclose(
            self.cycle_length_s,
            total_phase_time,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "cycle_length_s must equal the total duration "
                "of all signal phases"
            )

        return self


# ============================================================
# MOVEMENT SIGNAL STATE
# ============================================================

class MovementSignalState(BaseModel):
    """
    Current signal indication for one canonical Jaadah movement.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    movement_id: str
    indication: SignalIndication

    @field_validator("movement_id")
    @classmethod
    def validate_movement_id(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value


# ============================================================
# CURRENT SIGNAL STATE
# ============================================================

class CurrentSignalState(BaseModel):
    """
    Signal state observed during one concrete simulation run.

    Converts the current SUMO traffic-light state into Jaadah's
    movement-level representation.

    The scenario is found through run_id (SimulationRun) and the
    intersection through signal_program_id (SignalProgram), not stored
    here. That the program belongs to the run's scenario is checked
    where both are available, not in this model.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    run_id: str
    signal_program_id: str

    simulation_time_s: float = Field(ge=0)
    timestamp: datetime

    active_phase_id: str

    phase_elapsed_s: float = Field(ge=0)
    phase_remaining_s: float | None = Field(
        default=None,
        ge=0,
    )

    movement_states: list[MovementSignalState]

    @field_validator(
        "run_id",
        "signal_program_id",
        "active_phase_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
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

    @field_validator("movement_states")
    @classmethod
    def validate_movement_states(
        cls,
        values: list[MovementSignalState],
    ) -> list[MovementSignalState]:
        if not values:
            raise ValueError(
                "at least one movement signal state is required"
            )

        movement_ids = [
            state.movement_id
            for state in values
        ]

        if len(movement_ids) != len(set(movement_ids)):
            raise ValueError(
                "movement_states must not contain "
                "duplicate movement IDs"
            )

        return values
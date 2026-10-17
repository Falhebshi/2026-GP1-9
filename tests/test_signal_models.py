from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.signals import (
    CurrentSignalState,
    MovementSignalState,
    SignalControlType,
    SignalIndication,
    SignalPhase,
    SignalProgram,
    SignalProgramSource,
)


RIYADH = timezone(timedelta(hours=3))


# ============================================================
# TEST HELPERS
# ============================================================

def make_phase(
    phase_id="PHASE_1",
    sequence_order=0,
    served_movement_ids=None,
    green_time_s=40,
    yellow_time_s=3,
    all_red_time_s=2,
):
    if served_movement_ids is None:
        served_movement_ids = ["MOV_E_W"]

    return SignalPhase(
        phase_id=phase_id,
        sequence_order=sequence_order,
        served_movement_ids=served_movement_ids,
        green_time_s=green_time_s,
        yellow_time_s=yellow_time_s,
        all_red_time_s=all_red_time_s,
    )


def make_120_second_phases():
    return [
        make_phase(
            phase_id="PHASE_EAST",
            sequence_order=0,
            served_movement_ids=["MOV_E_W", "MOV_E_S"],
            green_time_s=40,
            yellow_time_s=3,
            all_red_time_s=2,
        ),
        make_phase(
            phase_id="PHASE_SOUTH",
            sequence_order=1,
            served_movement_ids=["MOV_S_W"],
            green_time_s=15,
            yellow_time_s=3,
            all_red_time_s=2,
        ),
        make_phase(
            phase_id="PHASE_WEST",
            sequence_order=2,
            served_movement_ids=["MOV_W_E", "MOV_W_N"],
            green_time_s=30,
            yellow_time_s=3,
            all_red_time_s=2,
        ),
        make_phase(
            phase_id="PHASE_NORTH",
            sequence_order=3,
            served_movement_ids=["MOV_N_E"],
            green_time_s=15,
            yellow_time_s=3,
            all_red_time_s=2,
        ),
    ]


# ============================================================
# SIGNAL PHASE TESTS
# ============================================================

def test_valid_signal_phase():
    phase = make_phase()

    assert phase.phase_id == "PHASE_1"
    assert phase.sequence_order == 0
    assert phase.served_movement_ids == ["MOV_E_W"]
    assert phase.green_time_s == 40


def test_signal_phase_ids_are_trimmed():
    phase = make_phase(
        phase_id="  PHASE_1  ",
        served_movement_ids=[
            "  MOV_E_W  ",
            "  MOV_E_S  ",
        ],
    )

    assert phase.phase_id == "PHASE_1"
    assert phase.served_movement_ids == [
        "MOV_E_W",
        "MOV_E_S",
    ]


def test_blank_phase_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        make_phase(phase_id="   ")


def test_empty_served_movement_list_is_rejected():
    with pytest.raises(
        ValidationError,
        match="at least one served movement ID is required",
    ):
        make_phase(served_movement_ids=[])


def test_blank_served_movement_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="served movement ID must not be empty",
    ):
        make_phase(
            served_movement_ids=[
                "MOV_E_W",
                "   ",
            ]
        )


def test_duplicate_served_movement_ids_are_rejected():
    with pytest.raises(
        ValidationError,
        match="must not contain duplicates",
    ):
        make_phase(
            served_movement_ids=[
                "MOV_E_W",
                "MOV_E_W",
            ]
        )


def test_boolean_sequence_order_is_rejected():
    with pytest.raises(
        ValidationError,
        match="sequence_order must be an integer",
    ):
        make_phase(sequence_order=True)


def test_negative_sequence_order_is_rejected():
    with pytest.raises(ValidationError):
        make_phase(sequence_order=-1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("green_time_s", 0),
        ("green_time_s", -1),
        ("yellow_time_s", -1),
        ("all_red_time_s", -1),
    ],
)
def test_invalid_phase_durations_are_rejected(
    field,
    value,
):
    data = {
        "phase_id": "PHASE_1",
        "sequence_order": 0,
        "served_movement_ids": ["MOV_E_W"],
        "green_time_s": 40,
        "yellow_time_s": 3,
        "all_red_time_s": 2,
    }

    data[field] = value

    with pytest.raises(ValidationError):
        SignalPhase(**data)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_phase_duration_is_rejected(value):
    with pytest.raises(ValidationError):
        make_phase(green_time_s=value)


def test_signal_phase_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        SignalPhase(
            phase_id="PHASE_1",
            sequence_order=0,
            served_movement_ids=["MOV_E_W"],
            green_time_s=40,
            yellow_time_s=3,
            all_red_time_s=2,
            raw_sumo_state="GGrr",
        )

# ============================================================
# SIGNAL PROGRAM TESTS
# ============================================================

def test_valid_signal_program():
    program = SignalProgram(
        signal_program_id="PROGRAM_BASELINE",
        scenario_id="SCN_001",
        control_type=SignalControlType.FIXED_TIME,
        cycle_length_s=120,
        phases=make_120_second_phases(),
        source=SignalProgramSource.BASELINE_MODEL,
    )

    assert program.cycle_length_s == 120
    assert len(program.phases) == 4
    assert program.control_type == SignalControlType.FIXED_TIME


def test_signal_program_ids_are_trimmed():
    program = SignalProgram(
        signal_program_id="  PROGRAM_001  ",
        scenario_id="  SCN_001  ",
        control_type=SignalControlType.FIXED_TIME,
        cycle_length_s=120,
        phases=make_120_second_phases(),
        source=SignalProgramSource.BASELINE_MODEL,
    )

    assert program.signal_program_id == "PROGRAM_001"
    assert program.scenario_id == "SCN_001"


@pytest.mark.parametrize(
    "field",
    [
        "signal_program_id",
        "scenario_id",
    ],
)
def test_blank_signal_program_ids_are_rejected(field):
    data = {
        "signal_program_id": "PROGRAM_001",
        "scenario_id": "SCN_001",
        "control_type": SignalControlType.FIXED_TIME,
        "cycle_length_s": 120,
        "phases": make_120_second_phases(),
        "source": SignalProgramSource.BASELINE_MODEL,
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        SignalProgram(**data)


def test_empty_phase_list_is_rejected():
    with pytest.raises(
        ValidationError,
        match="signal program must contain at least one phase",
    ):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=120,
            phases=[],
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_duplicate_phase_ids_are_rejected():
    phases = [
        make_phase(
            phase_id="PHASE_1",
            sequence_order=0,
            green_time_s=40,
        ),
        make_phase(
            phase_id="PHASE_1",
            sequence_order=1,
            green_time_s=40,
        ),
    ]

    with pytest.raises(
        ValidationError,
        match="phase IDs must be unique",
    ):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=90,
            phases=phases,
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_duplicate_sequence_orders_are_rejected():
    phases = [
        make_phase(
            phase_id="PHASE_1",
            sequence_order=0,
            green_time_s=40,
        ),
        make_phase(
            phase_id="PHASE_2",
            sequence_order=0,
            green_time_s=40,
        ),
    ]

    with pytest.raises(
        ValidationError,
        match="sequence_order values must be unique",
    ):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=90,
            phases=phases,
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_cycle_length_must_match_phase_total():
    with pytest.raises(
        ValidationError,
        match="cycle_length_s must equal the total duration",
    ):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=118,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_small_floating_point_difference_is_allowed():
    program = SignalProgram(
        signal_program_id="PROGRAM_001",
        scenario_id="SCN_001",
        control_type=SignalControlType.FIXED_TIME,
        cycle_length_s=120.0000001,
        phases=make_120_second_phases(),
        source=SignalProgramSource.BASELINE_MODEL,
    )

    assert program.cycle_length_s == 120.0000001


@pytest.mark.parametrize(
    "cycle_length",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_cycle_length_is_rejected(cycle_length):
    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=cycle_length,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_invalid_control_type_is_rejected():
    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type="magic_control",
            cycle_length_s=120,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
        )


def test_invalid_signal_program_source_is_rejected():
    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=120,
            phases=make_120_second_phases(),
            source="unknown",
        )


def test_sumo_tls_id_is_rejected_from_canonical_signal_program():
    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=120,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
            sumo_tls_id="TLS_001",
        )


def test_signal_program_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=120,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
            raw_tls_state="GGrr",
        )

        
# ============================================================
# MOVEMENT SIGNAL STATE TESTS
# ============================================================

@pytest.mark.parametrize(
    "indication",
    [
        SignalIndication.GREEN,
        SignalIndication.YELLOW,
        SignalIndication.RED,
    ],
)
def test_valid_movement_signal_indications(indication):
    state = MovementSignalState(
        movement_id="MOV_E_W",
        indication=indication,
    )

    assert state.indication == indication


def test_movement_id_is_trimmed():
    state = MovementSignalState(
        movement_id="  MOV_E_W  ",
        indication=SignalIndication.GREEN,
    )

    assert state.movement_id == "MOV_E_W"


def test_blank_movement_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        MovementSignalState(
            movement_id="   ",
            indication=SignalIndication.GREEN,
        )


def test_invalid_signal_indication_is_rejected():
    with pytest.raises(ValidationError):
        MovementSignalState(
            movement_id="MOV_E_W",
            indication="blue",
        )


def test_movement_signal_state_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        MovementSignalState(
            movement_id="MOV_E_W",
            indication=SignalIndication.GREEN,
            sumo_link_index=4,
        )


# ============================================================
# CURRENT SIGNAL STATE TESTS
# ============================================================

def test_valid_current_signal_state():
    state = CurrentSignalState(
        run_id="RUN_001",
        signal_program_id="PROGRAM_001",
        simulation_time_s=100,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        active_phase_id="PHASE_EAST",
        phase_elapsed_s=10,
        phase_remaining_s=30,
        movement_states=[
            MovementSignalState(
                movement_id="MOV_E_W",
                indication=SignalIndication.GREEN,
            ),
            MovementSignalState(
                movement_id="MOV_S_W",
                indication=SignalIndication.RED,
            ),
        ],
    )

    assert state.active_phase_id == "PHASE_EAST"
    assert state.phase_remaining_s == 30
    assert len(state.movement_states) == 2


def test_phase_remaining_time_may_be_missing():
    state = CurrentSignalState(
        run_id="RUN_001",
        signal_program_id="PROGRAM_001",
        simulation_time_s=100,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        active_phase_id="PHASE_EAST",
        phase_elapsed_s=10,
        movement_states=[
            MovementSignalState(
                movement_id="MOV_E_W",
                indication=SignalIndication.GREEN,
            )
        ],
    )

    assert state.phase_remaining_s is None


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "signal_program_id",
        "active_phase_id",
    ],
)
def test_blank_current_signal_ids_are_rejected(field):
    data = {
        "run_id": "RUN_001",
        "signal_program_id": "PROGRAM_001",
        "simulation_time_s": 100,
        "timestamp": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "active_phase_id": "PHASE_EAST",
        "phase_elapsed_s": 10,
        "phase_remaining_s": 30,
        "movement_states": [
            MovementSignalState(
                movement_id="MOV_E_W",
                indication=SignalIndication.GREEN,
            )
        ],
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        CurrentSignalState(**data)


def test_current_signal_ids_are_trimmed():
    state = CurrentSignalState(
        run_id="  RUN_001  ",
        signal_program_id="  PROGRAM_001  ",
        simulation_time_s=100,
        timestamp=datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        active_phase_id="  PHASE_EAST  ",
        phase_elapsed_s=10,
        movement_states=[
            MovementSignalState(
                movement_id="MOV_E_W",
                indication=SignalIndication.GREEN,
            )
        ],
    )

    assert state.run_id == "RUN_001"
    assert state.signal_program_id == "PROGRAM_001"
    assert state.active_phase_id == "PHASE_EAST"


def test_naive_current_signal_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(2026, 10, 10, 8, 0),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                )
            ],
        )


def test_non_riyadh_current_signal_timestamp_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must use Riyadh time",
    ):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(
                2026,
                10,
                10,
                5,
                0,
                tzinfo=timezone.utc,
            ),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                )
            ],
        )


def test_empty_movement_states_are_rejected():
    with pytest.raises(
        ValidationError,
        match="at least one movement signal state is required",
    ):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[],
        )


def test_duplicate_movement_states_are_rejected():
    with pytest.raises(
        ValidationError,
        match="duplicate movement IDs",
    ):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                ),
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.RED,
                ),
            ],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("simulation_time_s", -1),
        ("phase_elapsed_s", -1),
        ("phase_remaining_s", -1),
    ],
)
def test_negative_current_signal_times_are_rejected(
    field,
    value,
):
    data = {
        "run_id": "RUN_001",
        "signal_program_id": "PROGRAM_001",
        "simulation_time_s": 100,
        "timestamp": datetime(
            2026, 10, 10, 8, 0, tzinfo=RIYADH
        ),
        "active_phase_id": "PHASE_EAST",
        "phase_elapsed_s": 10,
        "phase_remaining_s": 30,
        "movement_states": [
            MovementSignalState(
                movement_id="MOV_E_W",
                indication=SignalIndication.GREEN,
            )
        ],
    }

    data[field] = value

    with pytest.raises(ValidationError):
        CurrentSignalState(**data)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_current_signal_times_are_rejected(value):
    with pytest.raises(ValidationError):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=value,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                )
            ],
        )


def test_current_signal_state_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(
                2026, 10, 10, 8, 0, tzinfo=RIYADH
            ),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                )
            ],
            raw_sumo_tls_state="GGrr",
        )

def test_signal_program_intersection_id_is_not_a_field():
    """Rule (a): the intersection is found through scenario_id."""

    with pytest.raises(ValidationError):
        SignalProgram(
            signal_program_id="PROGRAM_001",
            scenario_id="SCN_001",
            intersection_id="INT_001",
            control_type=SignalControlType.FIXED_TIME,
            cycle_length_s=120,
            phases=make_120_second_phases(),
            source=SignalProgramSource.BASELINE_MODEL,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("scenario_id", "SCN_001"), ("intersection_id", "INT_001")],
)
def test_current_signal_parent_ids_are_not_fields(field, value):
    """Rule (a): found through run_id and signal_program_id."""

    with pytest.raises(ValidationError):
        CurrentSignalState(
            run_id="RUN_001",
            signal_program_id="PROGRAM_001",
            simulation_time_s=100,
            timestamp=datetime(2026, 10, 10, 8, 0, tzinfo=RIYADH),
            active_phase_id="PHASE_EAST",
            phase_elapsed_s=10,
            movement_states=[
                MovementSignalState(
                    movement_id="MOV_E_W",
                    indication=SignalIndication.GREEN,
                )
            ],
            **{field: value},
        )
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.scenario import (
    ControlMode,
    Scenario,
    SimulationConfig,
    SimulationRun,
    SimulationRunStatus,
    TimeContext,
)


RIYADH = timezone(timedelta(hours=3))


# ============================================================
# SCENARIO TESTS
# ============================================================

def test_valid_historical_baseline_scenario():
    scenario = Scenario(
        scenario_id="SCN_001",
        intersection_id="INT_001",
        time_context=TimeContext.HISTORICAL,
        control_mode=ControlMode.BASELINE,
        start_time=datetime(2026, 10, 1, 8, 0, tzinfo=RIYADH),
        end_time=datetime(2026, 10, 1, 9, 0, tzinfo=RIYADH),
    )

    assert scenario.scenario_id == "SCN_001"
    assert scenario.reference_scenario_id is None


def test_valid_current_open_ended_scenario():
    scenario = Scenario(
        scenario_id="SCN_CURRENT",
        intersection_id="INT_001",
        time_context=TimeContext.CURRENT,
        control_mode=ControlMode.BASELINE,
        start_time=datetime(2026, 10, 10, 12, 0, tzinfo=RIYADH),
    )

    assert scenario.end_time is None


def test_valid_intervention_scenario():
    scenario = Scenario(
        scenario_id="SCN_INT_001",
        intersection_id="INT_001",
        time_context=TimeContext.HISTORICAL,
        control_mode=ControlMode.INTERVENTION,
        start_time=datetime(2026, 10, 1, 8, 0, tzinfo=RIYADH),
        end_time=datetime(2026, 10, 1, 9, 0, tzinfo=RIYADH),
        reference_scenario_id="SCN_BASE_001",
    )

    assert scenario.reference_scenario_id == "SCN_BASE_001"


@pytest.mark.parametrize(
    "field",
    [
        "scenario_id",
        "intersection_id",
    ],
)
def test_blank_required_scenario_ids_are_rejected(field):
    data = {
        "scenario_id": "SCN_001",
        "intersection_id": "INT_001",
        "time_context": TimeContext.HISTORICAL,
        "control_mode": ControlMode.BASELINE,
        "start_time": datetime(
            2026, 10, 1, 8, 0, tzinfo=RIYADH
        ),
        "end_time": datetime(
            2026, 10, 1, 9, 0, tzinfo=RIYADH
        ),
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Scenario(**data)


def test_scenario_ids_are_trimmed():
    scenario = Scenario(
        scenario_id="  SCN_001  ",
        intersection_id="  INT_001  ",
        time_context=TimeContext.HISTORICAL,
        control_mode=ControlMode.BASELINE,
        start_time=datetime(2026, 10, 1, 8, 0, tzinfo=RIYADH),
        end_time=datetime(2026, 10, 1, 9, 0, tzinfo=RIYADH),
    )

    assert scenario.scenario_id == "SCN_001"
    assert scenario.intersection_id == "INT_001"


def test_blank_reference_scenario_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Scenario(
            scenario_id="SCN_INT_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.INTERVENTION,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
            reference_scenario_id="   ",
        )


def test_naive_start_time_is_rejected():
    with pytest.raises(
        ValidationError,
        match="timestamp must include timezone information",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(2026, 10, 1, 8, 0),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
        )


def test_non_riyadh_scenario_timezone_is_rejected():
    utc = timezone.utc

    with pytest.raises(
        ValidationError,
        match="timestamp must use Riyadh time",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=utc
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
        )


def test_end_time_equal_to_start_time_is_rejected():
    timestamp = datetime(
        2026, 10, 1, 8, 0, tzinfo=RIYADH
    )

    with pytest.raises(
        ValidationError,
        match="end_time must be later than start_time",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=timestamp,
            end_time=timestamp,
        )


def test_end_time_before_start_time_is_rejected():
    with pytest.raises(
        ValidationError,
        match="end_time must be later than start_time",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
        )


@pytest.mark.parametrize(
    "time_context",
    [
        TimeContext.HISTORICAL,
        TimeContext.FORECAST,
    ],
)
def test_bounded_time_context_requires_end_time(time_context):
    with pytest.raises(
        ValidationError,
        match="must have an end_time",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=time_context,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
        )


def test_intervention_requires_reference_scenario():
    with pytest.raises(
        ValidationError,
        match="intervention scenario must reference",
    ):
        Scenario(
            scenario_id="SCN_INT_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.INTERVENTION,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
        )


def test_baseline_cannot_reference_another_scenario():
    with pytest.raises(
        ValidationError,
        match="baseline scenario must not reference",
    ):
        Scenario(
            scenario_id="SCN_BASE_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
            reference_scenario_id="SCN_OTHER",
        )


def test_scenario_cannot_reference_itself():
    with pytest.raises(
        ValidationError,
        match="scenario must not reference itself",
    ):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.INTERVENTION,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
            reference_scenario_id="SCN_001",
        )


def test_invalid_time_context_is_rejected():
    with pytest.raises(ValidationError):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context="futureish",
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
        )


def test_scenario_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        Scenario(
            scenario_id="SCN_001",
            intersection_id="INT_001",
            time_context=TimeContext.HISTORICAL,
            control_mode=ControlMode.BASELINE,
            start_time=datetime(
                2026, 10, 1, 8, 0, tzinfo=RIYADH
            ),
            end_time=datetime(
                2026, 10, 1, 9, 0, tzinfo=RIYADH
            ),
            sumo_config="unexpected",
        )


# ============================================================
# SIMULATION RUN TESTS
# ============================================================

def test_valid_simulation_run():
    run = SimulationRun(
        run_id="RUN_001",
        scenario_id="SCN_001",
        random_seed=42,
        network_version="network-v1",
        sumo_version="1.27.1",
        step_length_s=0.5,
        started_at=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=RIYADH,
        ),
        status=SimulationRunStatus.RUNNING,
    )

    assert run.run_id == "RUN_001"
    assert run.random_seed == 42
    assert run.step_length_s == 0.5


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "scenario_id",
        "network_version",
        "sumo_version",
    ],
)
def test_blank_simulation_run_strings_are_rejected(field):
    data = {
        "run_id": "RUN_001",
        "scenario_id": "SCN_001",
        "random_seed": 42,
        "network_version": "network-v1",
        "sumo_version": "1.27.1",
        "step_length_s": 0.5,
        "started_at": datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=RIYADH,
        ),
        "status": SimulationRunStatus.RUNNING,
    }

    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="value must not be empty",
    ):
        SimulationRun(**data)


def test_simulation_run_strings_are_trimmed():
    run = SimulationRun(
        run_id="  RUN_001  ",
        scenario_id="  SCN_001  ",
        random_seed=42,
        network_version="  network-v1  ",
        sumo_version="  1.27.1  ",
        step_length_s=0.5,
        started_at=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=RIYADH,
        ),
        status=SimulationRunStatus.RUNNING,
    )

    assert run.run_id == "RUN_001"
    assert run.scenario_id == "SCN_001"
    assert run.network_version == "network-v1"
    assert run.sumo_version == "1.27.1"


def test_negative_random_seed_is_rejected():
    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=-1,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=0.5,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status=SimulationRunStatus.RUNNING,
        )


def test_boolean_random_seed_is_rejected():
    with pytest.raises(
        ValidationError,
        match="random_seed must be an integer",
    ):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=True,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=0.5,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status=SimulationRunStatus.RUNNING,
        )


@pytest.mark.parametrize(
    "step_length",
    [
        0,
        -0.5,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_step_length_is_rejected(step_length):
    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=42,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=step_length,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status=SimulationRunStatus.RUNNING,
        )


def test_boolean_step_length_is_rejected():
    with pytest.raises(
        ValidationError,
        match="step_length_s must be a number",
    ):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=42,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=True,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status=SimulationRunStatus.RUNNING,
        )


def test_naive_started_at_is_rejected():
    with pytest.raises(
        ValidationError,
        match="started_at must include timezone information",
    ):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=42,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=0.5,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
            ),
            status=SimulationRunStatus.RUNNING,
        )


def test_started_at_can_use_utc():
    run = SimulationRun(
        run_id="RUN_001",
        scenario_id="SCN_001",
        random_seed=42,
        network_version="network-v1",
        sumo_version="1.27.1",
        step_length_s=0.5,
        started_at=datetime(
            2026,
            10,
            10,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        status=SimulationRunStatus.RUNNING,
    )

    assert run.started_at.utcoffset() == timedelta(0)


def test_invalid_run_status_is_rejected():
    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=42,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=0.5,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status="done-ish",
        )


def test_simulation_run_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        SimulationRun(
            run_id="RUN_001",
            scenario_id="SCN_001",
            random_seed=42,
            network_version="network-v1",
            sumo_version="1.27.1",
            step_length_s=0.5,
            started_at=datetime(
                2026,
                10,
                10,
                12,
                0,
                tzinfo=RIYADH,
            ),
            status=SimulationRunStatus.RUNNING,
            vehicle_count=100,
        )


# ============================================================
# SIMULATION CONFIG TESTS
# ============================================================

def test_valid_bounded_simulation_config():
    config = SimulationConfig(
        simulation_duration_s=900,
        warmup_duration_s=300,
    )

    assert config.simulation_duration_s == 900
    assert config.warmup_duration_s == 300


def test_valid_open_ended_simulation_config():
    config = SimulationConfig(
        warmup_duration_s=300,
    )

    assert config.simulation_duration_s is None


def test_zero_warmup_is_allowed():
    config = SimulationConfig(
        simulation_duration_s=900,
        warmup_duration_s=0,
    )

    assert config.warmup_duration_s == 0


@pytest.mark.parametrize(
    "duration",
    [
        0,
        -1,
    ],
)
def test_invalid_simulation_duration_is_rejected(duration):
    with pytest.raises(ValidationError):
        SimulationConfig(
            simulation_duration_s=duration,
            warmup_duration_s=300,
        )


def test_negative_warmup_is_rejected():
    with pytest.raises(ValidationError):
        SimulationConfig(
            simulation_duration_s=900,
            warmup_duration_s=-1,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("simulation_duration_s", True),
        ("warmup_duration_s", False),
    ],
)
def test_boolean_durations_are_rejected(field, value):
    data = {
        "simulation_duration_s": 900,
        "warmup_duration_s": 300,
    }

    data[field] = value

    with pytest.raises(
        ValidationError,
        match="duration must be an integer",
    ):
        SimulationConfig(**data)


def test_simulation_config_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        SimulationConfig(
            simulation_duration_s=900,
            warmup_duration_s=300,
            extraction_interval_s=1,
        )
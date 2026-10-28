import json
from datetime import datetime, timedelta

import pytest

from backend.outputs.playback import (
    build_failed_run_index,
    build_run_index,
    interval_files,
    pack_signal_changes,
    pack_vehicle_intervals,
    write_failed_run,
    write_playback,
)
from backend.outputs.signals import SignalChange
from jaadah.models.outputs import (
    VehicleState,
    VehicleType,
)
from jaadah.models.signals import (
    MovementSignalState,
    SignalIndication,
)


RUN_START = datetime.fromisoformat("2026-10-20T07:45:00+03:00")


def make_state(
    simulation_time_s: float,
    vehicle_id: str = "CAR_A",
) -> VehicleState:
    """Create one vehicle state for playback tests."""

    return VehicleState(
        vehicle_id=vehicle_id,
        run_id="RUN_TEST",
        simulation_time_s=simulation_time_s,
        timestamp=RUN_START + timedelta(seconds=simulation_time_s),
        longitude=46.641463,
        latitude=24.738699,
        speed_mps=23.66,
        heading_deg=243.85,
        vehicle_type=VehicleType.CAR,
        sumo_edge_id="713369663#1",
        sumo_lane_id="713369663#1_2",
        signals=8,
        movement_id="MOV_E_S",
    )


def trip_times(
    payload: dict,
) -> list[float]:
    """Return the sample times of the only trip of a vehicle payload."""

    [trip] = payload["trips"]

    return trip["timestamps"]


def test_run_is_cut_into_15_minute_files() -> None:
    intervals = interval_files(
        run_start=RUN_START,
        duration_s=5400,
    )

    assert [
        interval["file"]
        for interval in intervals
    ] == [
        "vehicles_0800.json",
        "vehicles_0815.json",
        "vehicles_0830.json",
        "vehicles_0845.json",
        "vehicles_0900.json",
        "vehicles_0915.json",
    ]
    assert intervals[1]["start_s"] == 900
    assert intervals[1]["end_s"] == 1800


def test_run_not_in_whole_intervals_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match="whole number of 15-minute intervals",
    ):
        interval_files(
            run_start=RUN_START,
            duration_s=5000,
        )


def test_run_index_lists_the_run_and_its_files() -> None:
    index = build_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        duration_s=5400,
        warm_up_s=900,
        clearance_s=900,
    )

    assert index["run_id"] == "RUN_TEST"
    assert index["intersection_id"] == "INT_001"
    assert index["run_start"] == "2026-10-20T07:45:00+03:00"
    assert index["interval_s"] == 900
    assert index["analysis_start_s"] == 900
    assert index["analysis_end_s"] == 4500
    assert len(index["intervals"]) == 6
    assert index["signals_file"] == "signals.json"


def test_run_without_an_analysis_period_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match="leave an analysis period",
    ):
        build_run_index(
            run_id="RUN_TEST",
            intersection_id="INT_001",
            scenario="baseline",
            run_start=RUN_START,
            duration_s=1800,
            warm_up_s=900,
            clearance_s=900,
        )


def test_sample_on_a_boundary_goes_into_both_files() -> None:
    payloads = pack_vehicle_intervals(
        states=[
            make_state(simulation_time_s=899.6),
            make_state(simulation_time_s=900.0),
            make_state(simulation_time_s=900.4),
        ],
        intervals=interval_files(
            run_start=RUN_START,
            duration_s=1800,
        ),
    )

    assert trip_times(payloads["vehicles_0800.json"]) == [899.6, 900.0]
    assert trip_times(payloads["vehicles_0815.json"]) == [900.0, 900.4]


def test_height_function_is_used() -> None:
    payloads = pack_vehicle_intervals(
        states=[make_state(simulation_time_s=10.0)],
        intervals=interval_files(
            run_start=RUN_START,
            duration_s=900,
        ),
        height_of=lambda state: -7.0,
    )

    [trip] = payloads["vehicles_0800.json"]["trips"]

    assert trip["z"] == [-7.0]


def test_without_height_every_car_is_at_street_level() -> None:
    payloads = pack_vehicle_intervals(
        states=[make_state(simulation_time_s=10.0)],
        intervals=interval_files(
            run_start=RUN_START,
            duration_s=900,
        ),
    )

    [trip] = payloads["vehicles_0800.json"]["trips"]

    assert trip["z"] == [0.0]
    assert trip["movement_id"] == "MOV_E_S"
    assert trip["signals"] == [8]


def test_signal_changes_become_movement_colours() -> None:
    payload = pack_signal_changes(
        run_id="RUN_TEST",
        changes=[
            SignalChange(
                simulation_time_s=40.0,
                timestamp=RUN_START + timedelta(seconds=40),
                movement_states=[
                    MovementSignalState(
                        movement_id="MOV_A",
                        indication=SignalIndication.YELLOW,
                    ),
                ],
            ),
        ],
    )

    assert payload["changes"] == [
        {
            "t": 40.0,
            "movements": {"MOV_A": "yellow"},
        },
    ]


def test_playback_files_are_written(tmp_path) -> None:
    index = build_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        duration_s=900,
        warm_up_s=0,
        clearance_s=0,
    )
    vehicle_payloads = pack_vehicle_intervals(
        states=[make_state(simulation_time_s=10.0)],
        intervals=index["intervals"],
    )
    signal_payload = pack_signal_changes(
        run_id="RUN_TEST",
        changes=[],
    )

    write_playback(
        output_dir=tmp_path / "baseline",
        run_index=index,
        vehicle_payloads=vehicle_payloads,
        signal_payload=signal_payload,
    )

    written = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "baseline").iterdir()
    }

    assert written == {
        "run.json": index,
        "signals.json": signal_payload,
        "vehicles_0800.json": vehicle_payloads["vehicles_0800.json"],
    }


def test_time_under_a_roof_becomes_a_hidden_span() -> None:
    covered_times = {900.4, 900.8, 901.2}
    payloads = pack_vehicle_intervals(
        states=[
            make_state(simulation_time_s=time_s)
            for time_s in [900.0, 900.4, 900.8, 901.2, 901.6]
        ],
        intervals=interval_files(
            run_start=RUN_START,
            duration_s=1800,
        ),
        covered_of=lambda state: state.simulation_time_s in covered_times,
    )

    [trip] = payloads["vehicles_0815.json"]["trips"]

    assert trip["hidden_spans"] == [[900.4, 901.2]]


def test_car_never_under_a_roof_has_no_hidden_spans() -> None:
    payloads = pack_vehicle_intervals(
        states=[make_state(simulation_time_s=10.0)],
        intervals=interval_files(
            run_start=RUN_START,
            duration_s=900,
        ),
    )

    [trip] = payloads["vehicles_0800.json"]["trips"]

    assert "hidden_spans" not in trip


def test_completed_run_says_so() -> None:
    index = build_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        duration_s=5400,
        warm_up_s=900,
        clearance_s=900,
    )

    assert index["status"] == "completed"
    assert "failure_reason" not in index


def test_failed_run_has_its_reason_and_no_files() -> None:
    index = build_failed_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        failure_reason=" TraCIException: connection closed ",
    )

    assert index["status"] == "failed"
    assert index["failure_reason"] == "TraCIException: connection closed"
    assert "intervals" not in index
    assert "signals_file" not in index


def test_failed_run_without_a_reason_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match="needs a failure reason",
    ):
        build_failed_run_index(
            run_id="RUN_TEST",
            intersection_id="INT_001",
            scenario="baseline",
            run_start=RUN_START,
            failure_reason="  ",
        )


def test_failed_run_writes_only_run_json(
    tmp_path,
) -> None:
    index = build_failed_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        failure_reason="SUMO stopped",
    )

    write_failed_run(
        output_dir=tmp_path,
        run_index=index,
    )

    assert [path.name for path in tmp_path.iterdir()] == ["run.json"]

    with (tmp_path / "run.json").open(
        encoding="utf-8",
    ) as file:
        assert json.load(file) == index


def test_only_a_test_run_is_marked_as_test() -> None:
    real = build_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        duration_s=5400,
        warm_up_s=900,
        clearance_s=900,
    )
    test = build_run_index(
        run_id="RUN_TEST",
        intersection_id="INT_001",
        scenario="baseline",
        run_start=RUN_START,
        duration_s=5400,
        warm_up_s=900,
        clearance_s=900,
        is_test=True,
    )

    assert "is_test" not in real
    assert test["is_test"] is True

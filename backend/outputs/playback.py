import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path

from backend.outputs.signals import SignalChange
from jaadah.models.outputs import VehicleState
from jaadah.models.scenario import (
    SimulationRunStatus,
)


INTERVAL_S = 15 * 60

PLAYBACK_UNITS = {
    "time_unit": "seconds from run_start",
    "angle_convention": "0 = north, clockwise",
    "speed_unit": "m/s",
    "z_unit": "m relative to street level (negative = underpass)",
    "signals_bits": {
        "1": "right blinker",
        "2": "left blinker",
        "8": "brake light",
    },
}


def interval_files(
    run_start: datetime,
    duration_s: int,
) -> list[dict]:
    """
    Return the 15-minute intervals of a run, each with the name of its
    vehicle file, labelled by the real time of the interval end.
    """

    if duration_s <= 0 or duration_s % INTERVAL_S != 0:
        raise ValueError(
            "run duration must be a whole number of 15-minute intervals"
        )

    intervals = []

    for start_s in range(0, duration_s, INTERVAL_S):
        end_s = start_s + INTERVAL_S
        label = (run_start + timedelta(seconds=end_s)).strftime("%H%M")

        intervals.append(
            {
                "start_s": start_s,
                "end_s": end_s,
                "file": f"vehicles_{label}.json",
            }
        )

    return intervals


def build_run_index(
    run_id: str,
    intersection_id: str,
    scenario: str,
    run_start: datetime,
    duration_s: int,
    warm_up_s: int,
    clearance_s: int,
) -> dict:
    """
    Return the table of contents of a run's playback files. The view
    shows only the analysis period, between the warm-up (the network
    filling up) and the clearance (the last vehicles finishing).
    """

    analysis_end_s = duration_s - clearance_s

    if (
        warm_up_s < 0
        or clearance_s < 0
        or warm_up_s % INTERVAL_S != 0
        or clearance_s % INTERVAL_S != 0
        or analysis_end_s <= warm_up_s
    ):
        raise ValueError(
            "warm-up and clearance must be whole 15-minute intervals "
            "that leave an analysis period"
        )

    return {
        "run_id": run_id,
        "intersection_id": intersection_id,
        "scenario": scenario,
        "status": SimulationRunStatus.COMPLETED.value,
        "run_start": run_start.isoformat(),
        "duration_s": duration_s,
        "analysis_start_s": warm_up_s,
        "analysis_end_s": analysis_end_s,
        "interval_s": INTERVAL_S,
        "time_unit": "seconds from run_start",
        "intervals": interval_files(
            run_start=run_start,
            duration_s=duration_s,
        ),
        "signals_file": "signals.json",
    }


def build_failed_run_index(
    run_id: str,
    intersection_id: str,
    scenario: str,
    run_start: datetime,
    failure_reason: str,
) -> dict:
    """
    Return run.json for a run that failed: its status and why, and no
    files, so the view shows the failure instead of a partial run.
    """

    failure_reason = failure_reason.strip()

    if not failure_reason:
        raise ValueError("a failed run needs a failure reason")

    return {
        "run_id": run_id,
        "intersection_id": intersection_id,
        "scenario": scenario,
        "status": SimulationRunStatus.FAILED.value,
        "failure_reason": failure_reason,
        "run_start": run_start.isoformat(),
    }


def no_height(
    state: VehicleState,
) -> float:
    """Height used when none is given: every car at street level."""

    return 0.0


def never_covered(
    state: VehicleState,
) -> bool:
    """Used when no roof is given: every car can be seen from above."""

    return False


def pack_vehicle_intervals(
    states: Iterable[VehicleState],
    intervals: list[dict],
    height_of: Callable[[VehicleState], float] = no_height,
    covered_of: Callable[[VehicleState], bool] = never_covered,
) -> dict[str, dict]:
    """
    Group vehicle states into one playback payload per 15-minute
    interval, keyed by file name. A sample on an interval boundary goes
    into both intervals, so a car crossing the boundary appears in both
    files without a gap. A car that drives under a roof, where it cannot
    be seen from above, gets the times it is covered in hidden_spans.
    """

    trips_by_file: dict[str, dict] = {
        interval["file"]: {}
        for interval in intervals
    }

    for state in states:
        for interval in intervals:
            if not (
                interval["start_s"]
                <= state.simulation_time_s
                <= interval["end_s"]
            ):
                continue

            trip = trips_by_file[interval["file"]].setdefault(
                state.vehicle_id,
                {
                    "vehicle_id": state.vehicle_id,
                    "movement_id": state.movement_id,
                    "path": [],
                    "z": [],
                    "timestamps": [],
                    "angles": [],
                    "speeds": [],
                    "signals": [],
                    "hidden_spans": [],
                },
            )
            trip["path"].append(
                [
                    round(state.longitude, 7),
                    round(state.latitude, 7),
                ]
            )
            trip["z"].append(round(height_of(state), 2))
            trip["timestamps"].append(round(state.simulation_time_s, 2))
            trip["angles"].append(round(state.heading_deg, 1))
            trip["speeds"].append(round(state.speed_mps, 2))
            trip["signals"].append(state.signals or 0)

            if covered_of(state):
                time_s = trip["timestamps"][-1]
                spans = trip["hidden_spans"]
                last_time_s = (
                    trip["timestamps"][-2]
                    if len(trip["timestamps"]) > 1
                    else None
                )

                if spans and spans[-1][1] == last_time_s:
                    spans[-1][1] = time_s
                else:
                    spans.append([time_s, time_s])

    for trips in trips_by_file.values():
        for trip in trips.values():
            if not trip["hidden_spans"]:
                del trip["hidden_spans"]

    return {
        interval["file"]: {
            **PLAYBACK_UNITS,
            "t_start": interval["start_s"],
            "t_end": interval["end_s"],
            "trips": list(trips_by_file[interval["file"]].values()),
        }
        for interval in intervals
    }


def pack_signal_changes(
    run_id: str,
    changes: list[SignalChange],
) -> dict:
    """Return the playback payload of a run's movement signal changes."""

    return {
        "run_id": run_id,
        "time_unit": "seconds from run_start",
        "changes": [
            {
                "t": round(change.simulation_time_s, 2),
                "movements": {
                    state.movement_id: state.indication.value
                    for state in change.movement_states
                },
            }
            for change in changes
        ],
    }


def write_json(
    path: Path,
    payload: dict,
) -> None:
    """Write one playback file in compact JSON."""

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            separators=(",", ":"),
        )


def write_failed_run(
    output_dir: str | Path,
    run_index: dict,
) -> None:
    """
    Write run.json of a failed run into output_dir. The files of an
    earlier run may stay in the folder; the view does not read them,
    because run.json lists none.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_json(
        path=output_dir / "run.json",
        payload=run_index,
    )


def write_playback(
    output_dir: str | Path,
    run_index: dict,
    vehicle_payloads: dict[str, dict],
    signal_payload: dict,
) -> None:
    """
    Write run.json, one vehicle file per interval and signals.json into
    output_dir, in compact JSON.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = {
        "run.json": run_index,
        run_index["signals_file"]: signal_payload,
        **vehicle_payloads,
    }

    for name, payload in files.items():
        write_json(
            path=output_dir / name,
            payload=payload,
        )

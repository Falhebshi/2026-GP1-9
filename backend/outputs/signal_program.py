"""
The study intersection's signal program for the website: the "Signal
type" of the Location card on Current Traffic, Traffic Forecast and
Traffic Patterns & Trends.

The program is read from the network file that SUMO runs, with the KPI
engine's own reader (jaadah/kpi_inputs/signal_program.py), so the pages
describe the same plan as every simulation and KPI. It is written to
frontend/public/data/<intersection>/signal_program.json, which is
committed: the plan is part of the network, not RCRC data.

Rebuild it after any change to the signal plan in the network:

    python -m backend.outputs.signal_program

A test checks that the committed file matches the network, so a plan
changed without rebuilding the file is caught.
"""

import argparse
import json
from pathlib import Path

from backend.analytics.service import DEFAULT_MAPPING_PATH, DEFAULT_NETWORK_PATH, FRONTEND_DATA_DIR
from jaadah.kpi_inputs.signal_program import build_signal_program
from jaadah.mapping.loader import load_network_mappings

FILE_NAME = "signal_program.json"


def signal_program_payload(
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
    network_path: str | Path = DEFAULT_NETWORK_PATH,
) -> dict:
    """The file's content: the plan of the intersection's signal in the network."""

    config = load_network_mappings(mapping_path)
    intersection_id = config.intersection_mapping.intersection_id
    program = build_signal_program(
        config, network_path,
        scenario_id=f"SCN_{intersection_id}_NETWORK",
        signal_program_id=f"SP_{intersection_id}_NETWORK",
    )

    return {
        "intersection_id": intersection_id,
        "network_sha256": config.network.sha256,
        "control_type": program.control_type.value,
        "source": program.source.value,
        "cycle_length_s": program.cycle_length_s,
        "phases": [
            {
                "phase_id": phase.phase_id,
                "sequence_order": phase.sequence_order,
                "served_movement_ids": phase.served_movement_ids,
                "green_time_s": phase.green_time_s,
                "yellow_time_s": phase.yellow_time_s,
                "all_red_time_s": phase.all_red_time_s,
            }
            for phase in program.phases
        ],
    }


def write_signal_program(
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
    network_path: str | Path = DEFAULT_NETWORK_PATH,
    out_dir: str | Path | None = None,
) -> Path:
    """Write signal_program.json and return its path."""

    payload = signal_program_payload(mapping_path, network_path)
    folder = Path(out_dir) if out_dir else FRONTEND_DATA_DIR / payload["intersection_id"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Write the website's copy of the signal program.")
    parser.add_argument("--out", type=Path, help="folder; default: frontend/public/data/<intersection>/")
    args = parser.parse_args(argv)

    path = write_signal_program(out_dir=args.out)
    payload = json.loads(path.read_text(encoding="utf-8"))
    greens = ", ".join(f"{p['green_time_s']:g}" for p in payload["phases"])
    print(f"Written: {path} (cycle {payload['cycle_length_s']:g} s, greens {greens} s)")


if __name__ == "__main__":
    main()

"""
Build the test run the 3D view shows until the baseline run exists.

Usage (from the repository root):
    python simulation/scene_3d/build_test_run.py

The demand is made up: the same number of vehicles (default 20) for
every movement and 15-minute interval of an 08:00-09:00 analysis with
15 minutes of warm-up and clearance. It covers the movements with
detectors and, for display only, the three tunnel movements, which no
detector counts. The vehicles are planned and written with the SUMO
demand generation, simulated with SUMO, and converted with
build_playback.py into frontend/public/data/INT_001/baseline/. No KPI
uses this run.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(REPO_ROOT))

from build_playback import (  # noqa: E402
    MAPPING_PATH,
    NETWORK_PATH,
    build_playback,
)
from jaadah.mapping.loader import load_network_mappings  # noqa: E402
from jaadah.models.scenario import (  # noqa: E402
    Scenario,
    SimulationConfig,
)
from jaadah.models.traffic import SimulationDemand  # noqa: E402
from jaadah.sumo_demand.planner import (  # noqa: E402
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import write_sumo_demand  # noqa: E402


RUN_ID = "TEST_SUMO_DEMAND_CHECK"

ANALYSIS_START = datetime.fromisoformat("2026-10-20T08:00:00+03:00")
ANALYSIS_END = datetime.fromisoformat("2026-10-20T09:00:00+03:00")
WARM_UP_S = 15 * 60
CLEARANCE_S = 15 * 60

# Tunnel movements: no detector counts them, so they get test demand only
TUNNEL_MOVEMENTS = frozenset(
    {
        "MOV_N_S_TUNNEL",
        "MOV_S_N_TUNNEL",
        "MOV_TUNNEL_ONRAMP",
    }
)

SEED = 42
STEP_LENGTH_S = 0.2
FCD_PERIOD_S = 0.4


def make_test_demand(
    window,
    movements: frozenset[str],
    vehicles_per_record: int,
) -> list[SimulationDemand]:
    """
    Return the same number of vehicles for every movement and interval
    of the run window.
    """

    demands = []

    for interval_start in window.interval_starts():
        interval_end = interval_start + timedelta(minutes=15)
        label = interval_end.strftime("%Y%m%dT%H%M")

        for movement_id in sorted(movements):
            demands.append(
                SimulationDemand(
                    demand_id=f"DEM_TEST_{movement_id}_{label}",
                    interval_start=interval_start,
                    interval_end=interval_end,
                    movement_id=movement_id,
                    vehicle_count=vehicles_per_record,
                    source="synthetic",
                    source_observation_ids=[
                        f"OBS_TEST_{movement_id}_{label}"
                    ],
                )
            )

    return demands


def run_sumo(
    sumo_bin: str,
    run_dir: Path,
    route_file: Path,
    end_s: int,
) -> None:
    """
    Run SUMO with the outputs the 3D view needs: FCD with geographic
    positions and vehicle signals, and every traffic-light state.
    """

    additional = run_dir / "tls_record.add.xml"
    additional.write_text(
        "<additional>"
        '<timedEvent type="SaveTLSStates" dest="tls_states.xml"/>'
        "</additional>",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sumo_bin,
            "--net-file", str(NETWORK_PATH),
            "--route-files", str(route_file),
            "--additional-files", str(additional),
            "--begin", "0",
            "--end", str(end_s),
            "--step-length", str(STEP_LENGTH_S),
            "--seed", str(SEED),
            "--fcd-output", "fcd.xml",
            "--fcd-output.geo",
            "--fcd-output.signals",
            "--device.fcd.period", str(FCD_PERIOD_S),
            "--no-step-log",
        ],
        cwd=run_dir,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[0],
    )
    parser.add_argument(
        "--vehicles-per-record",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--sumo-bin",
        default="sumo",
    )
    args = parser.parse_args()

    if shutil.which(args.sumo_bin) is None:
        parser.error("sumo was not found: pass --sumo-bin")

    mapping = load_network_mappings(MAPPING_PATH)
    window = build_run_window(
        Scenario(
            scenario_id="SCN_SCENE_3D_TEST",
            intersection_id=mapping.intersection_mapping.intersection_id,
            time_context="historical",
            control_mode="baseline",
            start_time=ANALYSIS_START,
            end_time=ANALYSIS_END,
        ),
        SimulationConfig(
            warmup_duration_s=WARM_UP_S,
            clearance_duration_s=CLEARANCE_S,
        ),
    )
    movements = demand_movement_ids(mapping) | TUNNEL_MOVEMENTS
    demands = make_test_demand(
        window=window,
        movements=movements,
        vehicles_per_record=args.vehicles_per_record,
    )

    # The tunnel movements pass no stop line, so their vehicles depart
    # in their own interval without a free-flow shift
    free_flow_s = compute_free_flow_times(mapping, NETWORK_PATH) | {
        movement_id: 0.0
        for movement_id in TUNNEL_MOVEMENTS
    }
    plan = plan_departures(
        demands,
        window=window,
        routes=movement_routes(mapping),
        expected_movements=movements,
        free_flow_s=free_flow_s,
        seed=SEED,
    )

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        generated = write_sumo_demand(
            plan,
            demands,
            mapping,
            run_dir,
        )
        run_sumo(
            sumo_bin=args.sumo_bin,
            run_dir=run_dir,
            route_file=generated.route_file,
            end_s=window.duration_s,
        )
        build_playback(
            run_dir=run_dir,
            run_id=RUN_ID,
            run_start=window.epoch,
            duration_s=window.duration_s,
            warm_up_s=WARM_UP_S,
            clearance_s=CLEARANCE_S,
            scenario="baseline",
            is_test=True,
        )


if __name__ == "__main__":
    main()

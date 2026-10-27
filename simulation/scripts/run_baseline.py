"""
Run one baseline simulation from the synthetic traffic source.

The run covers the analysis period plus 15 minutes of warm-up before it
and 15 minutes of clearance after it, as one continuous SUMO run. For an
08:00-09:00 analysis that is 07:45-09:15.

Steps:

1. ask the source for the latest interval it has stored, and stop if the
   whole run window is not available yet;
2. fetch and ingest the observations of the run window; stop if any
   record is rejected;
3. turn them into movement demand; stop if any demand cannot be built;
4. generate the SUMO demand, check it and run SUMO once.

Nothing is written before step 4, so a run that stops early leaves no
route file behind. The run stops at the raw SUMO outputs (raw/fcd.xml
and raw/tripinfo.xml); KPIs are calculated from them afterwards.

Exit codes: 0 the run completed, 1 the SUMO run failed, 2 the run could
not start.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Support direct invocation from any working directory without installing Jaadah.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx2

from backend.demand.service import build_simulation_demand
from backend.ingestion.client import SyntheticTrafficClient
from backend.ingestion.service import ingest_synthetic_observations
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import (
    ControlMode,
    Scenario,
    SimulationConfig,
    SimulationRun,
    SimulationRunStatus,
    TimeContext,
)
from jaadah.sumo_demand.checks import DemandCheckError
from jaadah.sumo_demand.planner import DemandPlanningError, build_run_window
from jaadah.sumo_demand.writer import DemandWritingError
from simulation.scripts.run_scenario import generate_and_execute_scenario

DEFAULT_SOURCE_URL = "http://127.0.0.1:8000"
DEFAULT_MAPPING = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
DEFAULT_NETWORK = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "simulation/outputs/baseline_runs"
WARMUP_S = 900
CLEARANCE_S = 900
RIYADH = timezone(timedelta(hours=3))


class BaselineNotStarted(Exception):
    """Raised when the run cannot start; lists every reason found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def sumo_version(sumo_bin: str = "sumo") -> str:
    """Return the version reported by SUMO, such as 1.27.1."""

    output = subprocess.run(
        [sumo_bin, "--version"], capture_output=True, text=True, check=True
    ).stdout
    first_line = output.splitlines()[0] if output else ""
    # The first line reads "Eclipse SUMO sumo 1.27.1"
    return first_line.split()[-1] if first_line else "unknown"


def _ingestion_problems(errors) -> list[str]:
    return [
        f"source record {error.record_number} (detector {error.detector_id}, "
        f"{error.source_timestamp}): {error.message}"
        for error in errors
    ]


def _demand_problems(errors) -> list[str]:
    problems = []
    for error in errors:
        where = ", ".join(
            part for part in (
                f"movement {error.movement_id}" if error.movement_id else "",
                f"detector {error.detector_id}" if error.detector_id else "",
                error.interval_end.isoformat() if error.interval_end else "",
            ) if part
        )
        problems.append(f"{where}: {error.message}" if where else error.message)
    return problems


def run_baseline(
    analysis_start: datetime,
    analysis_end: datetime,
    *,
    client: SyntheticTrafficClient,
    output_dir: str | Path,
    run_id: str,
    seed: int = 42,
    step_length_s: float = 0.4,
    mapping_path: str | Path = DEFAULT_MAPPING,
    network_path: str | Path = DEFAULT_NETWORK,
    sumo_bin: str = "sumo",
) -> dict:
    """
    Run one baseline simulation and return its summary; raise
    BaselineNotStarted when the run cannot start.
    """

    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists():
        raise BaselineNotStarted([f"Output folder already exists: {output_dir}"])

    mapping = load_network_mappings(mapping_path, network_path=network_path)
    scenario = Scenario(
        scenario_id=f"SCN_BASELINE_{analysis_start:%Y%m%dT%H%M}",
        intersection_id=mapping.intersection_mapping.intersection_id,
        time_context=TimeContext.HISTORICAL,
        control_mode=ControlMode.BASELINE,
        start_time=analysis_start,
        end_time=analysis_end,
    )
    config = SimulationConfig(warmup_duration_s=WARMUP_S, clearance_duration_s=CLEARANCE_S)
    window = build_run_window(scenario, config)

    # 1. The whole run window must be available at the source.
    latest = client.fetch_latest_available_timestamp()
    if latest is None or latest < window.run_end:
        raise BaselineNotStarted([
            "Traffic data are not yet complete for this simulation window.",
            f"Required through: {window.run_end.isoformat()}",
            f"Latest available: {latest.isoformat() if latest else 'none'}",
        ])

    # 2. Ingestion: every source record must be accepted.
    ingestion = ingest_synthetic_observations(client, start=window.epoch, end=window.run_end)
    if ingestion.errors:
        raise BaselineNotStarted(
            ["Source records were rejected during ingestion:"]
            + _ingestion_problems(ingestion.errors)
        )

    # 3. Demand: every movement and interval must be built.
    transformation = build_simulation_demand(
        ingestion.observations,
        mapping_path=mapping_path,
        window_start=window.epoch,
        window_end=window.run_end,
    )
    if transformation.errors:
        raise BaselineNotStarted(
            ["Movement demand could not be built:"]
            + _demand_problems(transformation.errors)
        )

    # 4. Generate the SUMO demand, check it and run SUMO once.
    run = SimulationRun(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        random_seed=seed,
        network_version=mapping.network.version,
        sumo_version=sumo_version(sumo_bin),
        step_length_s=step_length_s,
        status=SimulationRunStatus.PENDING,
    )
    started_at = datetime.now(RIYADH)
    try:
        result = generate_and_execute_scenario(
            scenario, config, run, transformation.demands,
            mapping_path=mapping_path, network_path=network_path,
            demand_dir=output_dir / "demand", run_dir=output_dir / "run",
            sumo_bin=sumo_bin,
        )
    except (DemandPlanningError, DemandWritingError, DemandCheckError) as exc:
        raise BaselineNotStarted(["Generated SUMO demand is not valid:"] + exc.problems) from exc

    generated = result["generated_demand"]
    execution = result["scenario_execution"]
    # Record what the run used and how it ended (contract rule e).
    finished = SimulationRun(**{
        **run.model_dump(),
        "status": (
            SimulationRunStatus.COMPLETED
            if execution["execution"]["status"] == "completed"
            else SimulationRunStatus.FAILED
        ),
        "started_at": started_at,
        "mapping_version": mapping.mapping_version,
        "demand_sha256": generated.demand_sha256,
        "route_file_sha256": generated.route_file_sha256,
    })
    summary = {
        "run_id": run.run_id,
        "scenario_id": scenario.scenario_id,
        "status": execution["execution"]["status"],
        "run_window": {
            "start": window.epoch.isoformat(),
            "analysis_start": window.analysis_start.isoformat(),
            "analysis_end": window.analysis_end.isoformat(),
            "end": window.run_end.isoformat(),
            "duration_s": window.duration_s,
        },
        "source": {
            "url": client.base_url,
            "latest_available_timestamp": latest.isoformat(),
            "records_accepted": ingestion.accepted_count,
        },
        "demand": {
            "records": len(transformation.demands),
            "vehicles": sum(item.vehicle_count for item in transformation.demands),
            "files": {
                name: {"path": str(getattr(generated, name)), "sha256": getattr(generated, f"{sha}_sha256")}
                for name, sha in (
                    ("route_file", "route_file"),
                    ("manifest_file", "manifest"),
                    ("demand_file", "demand"),
                )
            },
        },
        "simulation_run": finished.model_dump(mode="json"),
        "provenance": execution["provenance"],
        "raw_outputs": execution["raw_outputs"],
        "execution": execution["execution"],
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["summary_file"] = str(summary_path)
    return summary


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--analysis-start", required=True, type=datetime.fromisoformat,
                        help="Start of the analysis period, e.g. 2026-10-20T08:00+03:00")
    parser.add_argument("--analysis-end", required=True, type=datetime.fromisoformat,
                        help="End of the analysis period, e.g. 2026-10-20T09:00+03:00")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--step-length", type=float, default=0.4)
    parser.add_argument("--run-id", help="Default: RUN_BASELINE_<analysis start>_S<seed>")
    parser.add_argument("--out", type=Path,
                        help="Default: simulation/outputs/baseline_runs/<run-id>")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--net", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--sumo-bin", default="sumo")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or f"RUN_BASELINE_{args.analysis_start:%Y%m%dT%H%M}_S{args.seed}"
    output_dir = args.out or DEFAULT_OUTPUT_ROOT / run_id

    try:
        summary = run_baseline(
            args.analysis_start, args.analysis_end,
            client=SyntheticTrafficClient(args.source_url),
            output_dir=output_dir, run_id=run_id, seed=args.seed,
            step_length_s=args.step_length, mapping_path=args.mapping,
            network_path=args.net, sumo_bin=args.sumo_bin,
        )
    except BaselineNotStarted as exc:
        print(f"The baseline run did not start.\n{exc}", file=sys.stderr)
        return 2
    except httpx2.HTTPError as exc:
        print(f"The baseline run did not start: the traffic source could not be read ({exc}).",
              file=sys.stderr)
        return 2
    except (ValueError, FileExistsError) as exc:
        print(f"The baseline run did not start: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({key: summary[key] for key in (
        "run_id", "status", "run_window", "source", "raw_outputs", "summary_file")}, indent=2))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Run the calibration test hours and score the model against RCRC counts.

For every day in the range, the day's two test hours (peak_hours.py)
are simulated once per seed:

1. Demand: the hour plus warm-up and clearance is read from the RCRC
   replay source and turned into SUMO demand with the same steps as
   run_baseline.py (ingestion, demand transformation, departure
   planning, demand writer, demand checks). Generated demand is kept in
   the private data folder and reused by later calibration runs with the
   same hour, seed and mapping version.
2. SUMO: one run with induction loops at the 12 detector positions and
   no FCD output. Driver settings given with --set are applied to a copy
   of the route file; the generated demand itself is never changed.
3. Score: hourly counts are compared with the observed ones (geh.py).
   The mean of the seeds is compared, and only eligible detector-hours
   count.

Results hold RCRC-derived numbers, so they are written to the private
data folder, never to the repository:
    ../jaadah-private-data/processed/calibration/results/<label>.csv
    ../jaadah-private-data/processed/calibration/results/<label>.json

The replay source must release the requested days; start it with
JAADAH_REPLAY_OFFSET_WEEKS=0 (docs/rcrc_replay_source.md).

Example:
    python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12
    python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12 --set tau=1.2 --seeds 42 43 44 45 --jobs 2
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx2

from backend.demand.service import build_simulation_demand
from backend.ingestion.client import RcrcReplayClient
from backend.ingestion.service import ingest_rcrc_observations
from jaadah.calibration.detectors import calibration_detectors, write_e1_additional
from jaadah.calibration.e1_output import read_e1_intervals
from jaadah.calibration.geh import HourlyComparison, compare_hours, meets_target, pass_share
from jaadah.calibration.parameters import GEH_THRESHOLD, REQUIRED_PASS_SHARE
from jaadah.calibration.peak_hours import day_type, days_between, hour_windows
from jaadah.calibration.vehicle_type import parse_vehicle_settings, route_file_with_settings
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.scenario import ControlMode, Scenario, SimulationConfig, TimeContext
from jaadah.sumo_demand.checks import check_generated_demand
from jaadah.sumo_demand.planner import (
    build_run_window,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import write_sumo_demand
from simulation.scripts.run_baseline import (
    CLEARANCE_S,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_MAPPING,
    DEFAULT_NETWORK,
    DEFAULT_SOURCE_URLS,
    WARMUP_S,
)
from traffic_source.rcrc_replay.config import PRIVATE_DATA_DIR

SOURCE = "rcrc"
SITE_ID = "1444"
DEFAULT_OUTPUT_ROOT = PRIVATE_DATA_DIR / "processed" / "calibration"


class HourSkipped(Exception):
    """A test hour cannot be simulated; the reason is reported, not hidden."""


@dataclass
class PreparedHour:
    """One test hour and seed, ready to simulate."""

    day: date
    start: datetime
    end: datetime
    seed: int
    epoch: datetime
    duration_s: float
    route_file: Path
    observed_counts: dict = field(default_factory=dict)      # (detector, interval end) -> count
    observed_occupancy: dict = field(default_factory=dict)   # (detector, interval end) -> percent


# ============================================================
# 1. DEMAND
# ============================================================

def prepare_hour(
    client: RcrcReplayClient,
    mapping,
    start: datetime,
    end: datetime,
    seed: int,
    *,
    demand_root: Path,
    mapping_path: Path,
    network_path: Path,
    history_days: int,
    free_flow_s: dict,
) -> PreparedHour:
    """Read the hour's observations and build (or reuse) its SUMO demand."""

    scenario = Scenario(
        scenario_id=f"SCN_CALIBRATION_{start:%Y%m%dT%H%M}-{end:%H%M}",
        intersection_id=mapping.intersection_mapping.intersection_id,
        time_context=TimeContext.HISTORICAL,
        control_mode=ControlMode.BASELINE,
        start_time=start,
        end_time=end,
    )
    config = SimulationConfig(warmup_duration_s=WARMUP_S, clearance_duration_s=CLEARANCE_S)
    window = build_run_window(scenario, config)

    latest = client.fetch_latest_available_timestamp()
    if latest is None or latest < window.run_end:
        raise HourSkipped(
            f"source has data only until {latest}; start the replay source with "
            "JAADAH_REPLAY_OFFSET_WEEKS=0"
        )

    ingestion = ingest_rcrc_observations(client, start=window.epoch, end=window.run_end)
    if ingestion.errors:
        raise HourSkipped(f"{len(ingestion.errors)} source records were rejected")

    hour = [item for item in ingestion.observations if start < item.interval_end <= end]
    prepared = PreparedHour(
        day=start.date(), start=start, end=end, seed=seed,
        epoch=window.epoch, duration_s=window.duration_s,
        route_file=Path(),
        observed_counts={(item.detector_id, item.interval_end): item.vehicle_count for item in hour},
        observed_occupancy={
            (item.detector_id, item.interval_end): item.occupancy_percent
            for item in hour
            if item.occupancy_percent is not None
        },
    )

    demand_dir = demand_root / mapping.mapping_version / f"{start:%Y%m%dT%H%M}_S{seed}"
    route_file = demand_dir / f"{demand_dir.name}_routes.rou.xml"
    prepared.route_file = route_file
    if route_file.is_file():
        return prepared

    history = ingest_rcrc_observations(
        client, start=window.epoch - timedelta(days=history_days), end=window.epoch
    ).observations
    transformation = build_simulation_demand(
        ingestion.observations,
        mapping_path=mapping_path,
        history=history,
        window_start=window.epoch,
        window_end=window.run_end,
        available_until=latest,
    )
    if transformation.errors:
        raise HourSkipped(f"demand could not be built: {transformation.errors[0]}")

    plan = plan_departures(
        transformation.demands,
        window=window,
        routes=movement_routes(mapping),
        expected_movements=demand_movement_ids(mapping),
        free_flow_s=free_flow_s,
        seed=seed,
    )
    demand_dir.mkdir(parents=True, exist_ok=False)
    try:
        write_sumo_demand(plan, transformation.demands, mapping, demand_dir)
        check_generated_demand(demand_dir, mapping, network_path, window=window, seed=seed)
    except Exception:
        shutil.rmtree(demand_dir, ignore_errors=True)
        raise
    return prepared


# ============================================================
# 2. SUMO
# ============================================================

def simulate(
    prepared: PreparedHour,
    detectors,
    settings: dict[str, float],
    *,
    network_path: Path,
    sumo_bin: str,
    step_length_s: float,
) -> list:
    """Run SUMO once for the prepared hour and return the loop intervals."""

    with tempfile.TemporaryDirectory(prefix="jaadah_calibration_") as folder:
        folder = Path(folder)
        route_file = (
            route_file_with_settings(prepared.route_file, folder / "routes.rou.xml", settings)
            if settings
            else prepared.route_file
        )
        loops_output = folder / "loops.xml"
        loops = write_e1_additional(detectors, folder / "loops.add.xml", loops_output)
        command = [
            sumo_bin,
            "--net-file", str(network_path),
            "--route-files", str(route_file),
            "--additional-files", str(loops),
            "--begin", "0",
            "--end", f"{prepared.duration_s:g}",
            "--step-length", f"{step_length_s:g}",
            "--seed", str(prepared.seed),
            "--random", "false",
            "--no-step-log", "true",
            "--no-warnings", "true",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"SUMO failed for {prepared.start:%Y-%m-%d %H:%M} seed {prepared.seed}: "
                f"{result.stderr.strip()[-500:]}"
            )
        return read_e1_intervals(loops_output, detectors, prepared.epoch)


# ============================================================
# 3. SCORE
# ============================================================

def score_hour(runs: list[PreparedHour], intervals_by_seed: list[list], detector_ids) -> list[HourlyComparison]:
    """Compare one test hour (all its seeds) with the observations."""

    simulated = [
        {(item.detector_id, item.interval_end): item.vehicle_count for item in intervals}
        for intervals in intervals_by_seed
    ]
    return compare_hours(runs[0].observed_counts, simulated, detector_ids, [runs[0].end])


def mean_occupancy(values: dict, detector_id: str, end: datetime) -> float | None:
    """Mean occupancy of the hour's four intervals, or None if any is missing."""

    points = [values.get((detector_id, end - step * timedelta(minutes=15))) for step in range(4)]
    if any(point is None for point in points):
        return None
    return sum(points) / 4


# ============================================================
# COMMAND LINE
# ============================================================

def parse_days(text: str) -> list[date]:
    """'2026-08-30..2026-09-12' (both included) or one day '2026-08-30'."""

    first, separator, last = text.partition("..")
    first_day = date.fromisoformat(first.strip())
    last_day = date.fromisoformat(last.strip()) if separator else first_day
    return days_between(first_day, last_day)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score SUMO against RCRC counts on the calibration test hours.")
    parser.add_argument("--days", required=True, type=parse_days,
                        help="first..last day (both included), e.g. 2026-08-30..2026-09-12")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--set", dest="settings", action="append", default=[], metavar="NAME=VALUE",
                        help="driver setting for this run, e.g. --set tau=1.2 (repeatable)")
    parser.add_argument("--jobs", type=int, default=1, help="SUMO runs at the same time")
    parser.add_argument("--label", help="name of the results files (default: date-time and settings)")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URLS[SOURCE])
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS[SOURCE])
    parser.add_argument("--step-length", type=float, default=0.4)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--net", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--sumo-bin", default="sumo")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    try:
        args.settings = parse_vehicle_settings(args.settings)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def default_label(settings: dict[str, float]) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    tuned = "_".join(f"{name}{value:g}" for name, value in sorted(settings.items())) or "defaults"
    return f"{stamp}_{tuned}"


def main(argv=None) -> int:
    args = parse_args(argv)
    sumo_bin = shutil.which(args.sumo_bin)
    if sumo_bin is None:
        print(f"SUMO not found: {args.sumo_bin}", file=sys.stderr)
        return 2

    mapping = load_network_mappings(args.mapping, network_path=args.net)
    detectors = calibration_detectors(mapping, source=SOURCE, site_id=SITE_ID)
    detector_ids = [item.detector_id for item in detectors]
    approach_of = {item.detector_id: item.approach_id for item in detectors}
    free_flow_s = compute_free_flow_times(mapping, args.net)
    client = RcrcReplayClient(args.source_url)

    # 1. Demand, one test hour and seed at a time (the source is read in order).
    prepared, skipped = [], []
    for day in args.days:
        for start, end in hour_windows(day):
            for seed in args.seeds:
                try:
                    prepared.append(prepare_hour(
                        client, mapping, start, end, seed,
                        demand_root=args.out_root / "demand",
                        mapping_path=args.mapping, network_path=args.net,
                        history_days=args.history_days, free_flow_s=free_flow_s,
                    ))
                except HourSkipped as exc:
                    skipped.append((start, seed, str(exc)))
                except httpx2.HTTPError as exc:
                    print(f"The replay source could not be read ({exc}). Is it running?", file=sys.stderr)
                    return 2
    print(f"{len(prepared)} runs to simulate ({len(args.days)} days, {len(args.seeds)} seed(s)); "
          f"{len(skipped)} skipped")
    for start, seed, reason in skipped:
        print(f"  skipped {start:%Y-%m-%d %H:%M} seed {seed}: {reason}")

    # 2. SUMO runs.
    def run(item):
        return simulate(item, detectors, args.settings, network_path=args.net,
                        sumo_bin=sumo_bin, step_length_s=args.step_length)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        intervals = list(pool.map(run, prepared))

    # 3. Score each test hour over its seeds.
    hours = {}
    for item, result in zip(prepared, intervals):
        hours.setdefault(item.start, []).append((item, result))

    rows, comparisons = [], []
    for start, group in sorted(hours.items()):
        runs = [item for item, _ in group]
        results = [result for _, result in group]
        hour_comparisons = score_hour(runs, results, detector_ids)
        comparisons += hour_comparisons
        simulated_occupancy = [
            {(i.detector_id, i.interval_end): i.occupancy_percent for i in result} for result in results
        ]
        for comparison in hour_comparisons:
            per_seed = [mean_occupancy(values, comparison.detector_id, comparison.hour_end)
                        for values in simulated_occupancy]
            sim_occupancy = (sum(per_seed) / len(per_seed)) if None not in per_seed else None
            obs_occupancy = mean_occupancy(runs[0].observed_occupancy, comparison.detector_id, comparison.hour_end)
            rows.append({
                "day": runs[0].day.isoformat(),
                "day_type": day_type(runs[0].day),
                "hour_start": f"{runs[0].start:%H:%M}",
                "detector_id": comparison.detector_id,
                "approach_id": approach_of[comparison.detector_id],
                "observed_veh_h": comparison.observed,
                "simulated_veh_h": round(comparison.simulated, 1),
                "geh": round(comparison.geh, 2),
                "match": comparison.matches,
                "observed_occupancy_pct": None if obs_occupancy is None else round(obs_occupancy, 1),
                "simulated_occupancy_pct": None if sim_occupancy is None else round(sim_occupancy, 1),
            })

    share = pass_share(comparisons)
    label = args.label or default_label(args.settings)
    results_dir = args.out_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / f"{label}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["day"])
        writer.writeheader()
        writer.writerows(rows)

    by_approach = {}
    for row in rows:
        by_approach.setdefault(row["approach_id"], []).append(row["match"])
    summary = {
        "label": label,
        "days": [args.days[0].isoformat(), args.days[-1].isoformat()],
        "seeds": args.seeds,
        "settings": args.settings,
        "mapping_version": mapping.mapping_version,
        "eligible_detector_hours": len(comparisons),
        "pass_share": share,
        "target": REQUIRED_PASS_SHARE,
        "geh_threshold": GEH_THRESHOLD,
        "meets_target": meets_target(comparisons),
        "pass_share_by_approach": {
            approach: sum(matches) / len(matches) for approach, matches in sorted(by_approach.items())
        },
        "skipped": [{"hour_start": start.isoformat(), "seed": seed, "reason": reason}
                    for start, seed, reason in skipped],
    }
    (results_dir / f"{label}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if share is None:
        print("No eligible detector-hours: nothing was compared.")
        return 1
    print(f"\n{len(comparisons)} eligible detector-hours, {share:.1%} with GEH < {GEH_THRESHOLD:g} "
          f"(target {REQUIRED_PASS_SHARE:.0%}): {'MET' if summary['meets_target'] else 'NOT MET'}")
    for approach, value in summary["pass_share_by_approach"].items():
        print(f"  {approach}: {value:.1%}")
    print(f"Details: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

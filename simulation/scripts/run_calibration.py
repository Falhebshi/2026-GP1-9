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
   count. The pass rate of each seed is reported too.
4. Capacity: each detector-hour is marked within capacity when the
   observed hourly volume of its lane group is at or below the lane
   group's HCM capacity under the network's signal plan, as the KPI
   engine calculates it (saturation flow x effective green / cycle).
   The pass rate on all eligible detector-hours is the result; the
   pass rate within capacity is reported next to it.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx2

from backend.analytics.kpi.capacity import calculate_capacity
from backend.analytics.kpi.lane_groups import derive_lane_groups
from backend.demand.service import build_simulation_demand
from backend.ingestion.client import RcrcReplayClient
from backend.ingestion.service import ingest_rcrc_observations
from jaadah.calibration.detectors import calibration_detectors, write_e1_additional
from jaadah.calibration.e1_output import read_e1_intervals
from jaadah.calibration.geh import HourlyComparison, compare_hours, meets_target, pass_share
from jaadah.calibration.parameters import (
    GEH_THRESHOLD,
    INDICATIVE_BELOW,
    REQUIRED_PASS_SHARE,
)
from jaadah.calibration.peak_hours import day_type, days_between, hour_windows
from jaadah.calibration.vehicle_type import parse_vehicle_settings, route_file_with_settings
from jaadah.kpi_inputs.network_inputs import build_network_inputs
from jaadah.kpi_inputs.signal_program import build_signal_program
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import KpiStatus
from jaadah.models.scenario import ControlMode, Scenario, SimulationConfig, TimeContext
from jaadah.models.traffic import SimulationDemand
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


class SourceNotReady(Exception):
    """The replay source has no report loaded; no hour can be prepared."""


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
    movement_demand: dict = field(default_factory=dict)      # movement -> vehicles in the hour (= veh/h)


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
    if latest is None:
        raise SourceNotReady(
            "the replay source has no report loaded; load it with "
            "python -m traffic_source.rcrc_replay.load <report.csv> and restart the server"
        )
    if latest < window.run_end:
        raise HourSkipped(
            f"source has data only until {latest:%Y-%m-%d %H:%M}; if the report covers "
            "this hour, start the replay source with JAADAH_REPLAY_OFFSET_WEEKS=0"
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
        prepared.movement_demand = hour_movement_demand(demand_dir, start, end)
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
    prepared.movement_demand = hour_movement_demand(demand_dir, start, end)
    return prepared


def hour_movement_demand(demand_dir: Path, start: datetime, end: datetime) -> dict[str, int]:
    """Vehicles per movement in [start, end), read from the stored demand file."""

    demand_file = demand_dir / f"{demand_dir.name}_demand.json"
    totals: dict[str, int] = {}
    for record in json.loads(demand_file.read_text(encoding="utf-8")):
        demand = SimulationDemand.model_validate(record)
        if start <= demand.interval_start and demand.interval_end <= end:
            totals[demand.movement_id] = totals.get(demand.movement_id, 0) + demand.vehicle_count
    return totals


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


# ============================================================
# 4. CAPACITY
# ============================================================

@dataclass(frozen=True)
class GroupCapacity:
    """One lane group in one test hour."""

    lane_group_id: str
    observed_veh_h: int | None
    capacity_veh_h: float | None

    @property
    def within_capacity(self) -> bool | None:
        if self.observed_veh_h is None or self.capacity_veh_h is None:
            return None
        return self.observed_veh_h <= self.capacity_veh_h


def hour_capacities(
    groups,
    lanes_by_id,
    movements,
    movement_attributes,
    program,
    movement_demand: dict[str, int],
    observed_hourly: dict[str, int | None],
    detector_of_lane: dict[str, str],
) -> dict[str, GroupCapacity]:
    """
    Capacity of every lane group in one test hour, keyed by detector ID.

    The capacity comes from the KPI engine (calculate_capacity) with the
    hour's movement demand. The observed volume of a lane group is the
    sum of the observed hourly counts of its lanes' detectors; it is
    unknown (None) when a lane has no detector or no eligible count.
    """

    demand = {m: float(v) for m, v in movement_demand.items() if m in movement_attributes}
    results = calculate_capacity(groups, lanes_by_id, movements, movement_attributes, program, demand)

    by_detector = {}
    for group in groups:
        result = results.lane_groups.get(group.lane_group_id)
        capacity = (
            result.capacity_veh_h
            if result is not None and result.status == KpiStatus.OK
            else None
        )
        counts = [observed_hourly.get(detector_of_lane.get(lane)) for lane in group.lane_ids]
        observed = None if any(count is None for count in counts) else sum(counts)
        for lane in group.lane_ids:
            if lane in detector_of_lane:
                by_detector[detector_of_lane[lane]] = GroupCapacity(
                    group.lane_group_id, observed, capacity
                )
    return by_detector


def describe_share(comparisons: list[HourlyComparison]) -> str:
    """'84.2% of 336' or 'none'; marked indicative below INDICATIVE_BELOW."""

    share = pass_share(comparisons)
    if share is None:
        return "none"
    note = " (indicative: fewer than %d)" % INDICATIVE_BELOW if len(comparisons) < INDICATIVE_BELOW else ""
    return f"{share:.1%} of {len(comparisons)}{note}"


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
    detector_of_lane = {item.lane_id: item.detector_id for item in detectors if item.lane_id}
    free_flow_s = compute_free_flow_times(mapping, args.net)
    client = RcrcReplayClient(args.source_url)

    # Capacity inputs, as the KPI engine builds them.
    network = build_network_inputs(mapping)
    program = build_signal_program(
        mapping, args.net, scenario_id="SCN_CALIBRATION", signal_program_id="SP_CALIBRATION"
    )
    groups = derive_lane_groups(network.lanes, list(network.movement_attributes.values()))
    lanes_by_id = {lane.lane_id: lane for lane in network.lanes}
    movements = {m: network.movements[m] for m in network.movement_attributes}

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
                except SourceNotReady as exc:
                    print(f"Nothing was run: {exc}.", file=sys.stderr)
                    return 2
                except httpx2.HTTPError as exc:
                    print(f"The replay source could not be read ({exc}). Is it running?", file=sys.stderr)
                    return 2
    print(f"{len(prepared)} runs to simulate ({len(args.days)} days, {len(args.seeds)} seed(s)); "
          f"{len(skipped)} skipped")
    for start, seed, reason in skipped:
        print(f"  skipped {start:%Y-%m-%d %H:%M} seed {seed}: {reason}")

    # 2. SUMO runs, with progress.
    def run(item):
        return simulate(item, detectors, args.settings, network_path=args.net,
                        sumo_bin=sumo_bin, step_length_s=args.step_length)

    intervals = [None] * len(prepared)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run, item): index for index, item in enumerate(prepared)}
        for done, future in enumerate(as_completed(futures), start=1):
            intervals[futures[future]] = future.result()
            item = prepared[futures[future]]
            print(f"  run {done}/{len(prepared)} done ({item.start:%Y-%m-%d %H:%M}, seed {item.seed})",
                  flush=True)

    # 3. Score each test hour over its seeds; 4. capacity of its lane groups.
    hours = {}
    for item, result in zip(prepared, intervals):
        hours.setdefault(item.start, []).append((item, result))

    rows, comparisons, within = [], [], []
    per_seed = {seed: [] for seed in args.seeds}
    for start, group in sorted(hours.items()):
        runs = [item for item, _ in group]
        results = [result for _, result in group]
        hour_comparisons = score_hour(runs, results, detector_ids)
        comparisons += hour_comparisons
        for item, result in group:
            per_seed[item.seed] += score_hour([item], [result], detector_ids)

        observed_hourly = {c.detector_id: c.observed for c in hour_comparisons}
        capacities = hour_capacities(
            groups, lanes_by_id, movements, network.movement_attributes, program,
            runs[0].movement_demand, observed_hourly, detector_of_lane,
        )
        simulated_occupancy = [
            {(i.detector_id, i.interval_end): i.occupancy_percent for i in result} for result in results
        ]
        for comparison in hour_comparisons:
            seed_occupancy = [mean_occupancy(values, comparison.detector_id, comparison.hour_end)
                              for values in simulated_occupancy]
            sim_occupancy = (sum(seed_occupancy) / len(seed_occupancy)) if None not in seed_occupancy else None
            obs_occupancy = mean_occupancy(runs[0].observed_occupancy, comparison.detector_id, comparison.hour_end)
            capacity = capacities.get(comparison.detector_id)
            if capacity is not None and capacity.within_capacity:
                within.append(comparison)
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
                "lane_group_id": None if capacity is None else capacity.lane_group_id,
                "lane_group_observed_veh_h": None if capacity is None else capacity.observed_veh_h,
                "lane_group_capacity_veh_h": (
                    None if capacity is None or capacity.capacity_veh_h is None
                    else round(capacity.capacity_veh_h, 1)
                ),
                "within_capacity": None if capacity is None else capacity.within_capacity,
            })

    share = pass_share(comparisons)
    seed_shares = {seed: pass_share(items) for seed, items in per_seed.items()}
    known = [value for value in seed_shares.values() if value is not None]
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
        "indicative": len(comparisons) < INDICATIVE_BELOW,
        "pass_share": share,
        "target": REQUIRED_PASS_SHARE,
        "geh_threshold": GEH_THRESHOLD,
        "meets_target": meets_target(comparisons),
        "within_capacity_detector_hours": len(within),
        "pass_share_within_capacity": pass_share(within),
        "pass_share_by_seed": {str(seed): value for seed, value in seed_shares.items()},
        "seed_spread": (max(known) - min(known)) if known else None,
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
    print(f"\nAll eligible detector-hours: {describe_share(comparisons)} with GEH < {GEH_THRESHOLD:g} "
          f"(target {REQUIRED_PASS_SHARE:.0%}): {'MET' if summary['meets_target'] else 'NOT MET'}")
    print(f"Within capacity:              {describe_share(within)}")
    for approach, value in summary["pass_share_by_approach"].items():
        print(f"  {approach}: {value:.1%}")
    if len(args.seeds) > 1:
        shares = ", ".join(f"{seed}: {value:.1%}" for seed, value in seed_shares.items() if value is not None)
        print(f"Per seed: {shares} (spread {summary['seed_spread']:.1%})")
    print(f"Details: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

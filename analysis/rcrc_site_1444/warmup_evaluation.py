"""
How long must a live chain started during the day warm up?

The live loop (docs/live_update_loop.md) starts a new chain during the
day after a pause or a long stop. The chain starts on empty roads, so it
first simulates some intervals before the newest one without showing
them (the warm-up). This evaluation finds the shortest warm-up after
which a restarted chain shows the same traffic as a chain that has run
since 03:00, and whether a warm-up on estimated traffic works after an
outage, when the hours before the restart have no data.

For each day and restart time t, and each seed:

1. reference: one SUMO run of the whole day from 02:45, on the real
   counts (the day's chain);
2. warm-up w: a run that starts at t - w on empty roads, on the same
   demand, for each w in --warmups;
3. outage: a run that starts at t - 180 min on demand in which the
   counts of those 3 hours were removed, so the demand transformation
   estimates them (level-adjusted, then plain time-slot average), as the
   live loop would for silent detectors.

Every run ends 90 minutes after t. The measure is the mean time loss
(SUMO tripinfo timeLoss) of the vehicles that depart in [t, t + 1 h).
The vehicles are the same in every run: departures depend only on the
movement, the interval and the seed.

Rule: a warm-up is long enough when, in every case, the mean over the
seeds of its difference from the reference is within --tolerance
(default 5 %). The result is the shortest warm-up that passes every
case.

The results are simulation outputs on RCRC demand; they are written to
the private data folder, outside the repository:
    ../jaadah-private-data/processed/live/warmup_evaluation/

Usage, from the repository root (the replay's report must be loaded;
the replay server does not need to run):
    python analysis/rcrc_site_1444/warmup_evaluation.py --jobs 8
    python analysis/rcrc_site_1444/warmup_evaluation.py --cases 2026-10-06T17:30 --warmups 15 180 --seeds 42 --jobs 2
"""

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.demand.service import build_simulation_demand  # noqa: E402
from backend.ingestion.client import RcrcBatch  # noqa: E402
from backend.ingestion.service import ingest_rcrc_observations  # noqa: E402
from jaadah.mapping.loader import load_network_mappings  # noqa: E402
from jaadah.sumo_demand.planner import (  # noqa: E402
    RunWindow,
    compute_free_flow_times,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import write_sumo_demand  # noqa: E402
from simulation.scripts.run_baseline import DEFAULT_MAPPING, DEFAULT_NETWORK  # noqa: E402
from traffic_source.rcrc_replay.config import PRIVATE_DATA_DIR, RCRC_REPLAY_DATABASE_PATH, RIYADH  # noqa: E402
from traffic_source.rcrc_replay.storage import RcrcReplayStorage  # noqa: E402

# A workday, a second workday, a Friday and a Saturday in October, restarted
# in their busy periods (calibration test hours, docs/calibration.md, plus the
# evening peak). In October the 35 days of history all come after the
# late-August demand increase; just after such a change, a time-slot average
# lags behind the traffic (estimated warm-up demand on 1 Sep was over a third
# too low), which would measure the history rather than the warm-up.
DEFAULT_CASES = [
    "2026-10-06T07:45", "2026-10-06T14:15", "2026-10-06T17:30",
    "2026-10-08T07:45", "2026-10-08T14:15", "2026-10-08T17:30",
    "2026-10-09T17:30", "2026-10-09T21:30",
    "2026-10-10T17:30", "2026-10-10T21:30",
]
DEFAULT_WARMUPS = [15, 30, 60, 90, 120, 180, 240]
OUTAGE_WARMUP = 180
DAY_START = timedelta(hours=2, minutes=45)    # the daily chain's second 0
MEASURED = timedelta(hours=1)
RUN_AFTER = timedelta(minutes=90)
STEP_LENGTH_S = 0.4
HISTORY_DAYS = 35
DEFAULT_OUT = PRIVATE_DATA_DIR / "processed" / "live" / "warmup_evaluation"


class ReportSource:
    """The replay's stored report as a source that has delivered everything."""

    def __init__(self, storage: RcrcReplayStorage):
        info = storage.get_report_info()
        if info is None:
            raise SystemExit("the replay has no report loaded")
        self.storage, self.site_id = storage, info["site_id"]

    def fetch_observations(self, start, end):
        return RcrcBatch(site_id=self.site_id, records=self.storage.get_rows(after=start, through=end))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", nargs="+", default=DEFAULT_CASES, help="restart times, Riyadh time")
    parser.add_argument("--warmups", nargs="+", type=int, default=DEFAULT_WARMUPS, help="minutes")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 43, 44])
    parser.add_argument("--tolerance", type=float, default=0.05)
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sumo-bin", default="sumo")
    args = parser.parse_args(argv)
    args.cases = [datetime.fromisoformat(c).replace(tzinfo=RIYADH) for c in args.cases]
    return args


def day_demand(source, mapping_path, epoch, end, *, silent=None):
    """Movement demand from epoch to end; silent=(start, end] removes those counts first."""

    observations = ingest_rcrc_observations(source, start=epoch, end=end).observations
    if silent:
        observations = [o for o in observations if not silent[0] < o.interval_end <= silent[1]]
    history = ingest_rcrc_observations(source, start=epoch - timedelta(days=HISTORY_DAYS), end=epoch).observations
    result = build_simulation_demand(
        observations, mapping_path=mapping_path, history=history, window_start=epoch,
        window_end=end, available_until=end, fallback_gap_intervals=10_000 if silent else None,
    )
    if result.errors:
        raise RuntimeError(f"demand for {epoch:%Y-%m-%d %H:%M}: {result.errors[0]}")
    return result.demands


def route_file(demands, mapping, free_flow, epoch, end, seed, folder: Path) -> Path:
    path = folder / "routes.rou.xml"
    if path.is_file():
        return path
    window = RunWindow(epoch=epoch, analysis_start=epoch + timedelta(minutes=15), analysis_end=end, run_end=end)
    plan = plan_departures(demands, window=window, routes=movement_routes(mapping),
                           expected_movements=demand_movement_ids(mapping), free_flow_s=free_flow, seed=seed)
    generated = write_sumo_demand(plan, demands, mapping, folder / "demand")
    path.write_bytes(generated.route_file.read_bytes())
    return path


def simulate(sumo_bin, network, routes: Path, seed, begin_s, end_s, folder: Path) -> Path:
    trip = folder / f"trip_{int(begin_s)}.xml"
    if not trip.is_file():
        subprocess.run([
            sumo_bin, "-n", str(network), "-r", str(routes), "--begin", f"{begin_s:g}", "--end", f"{end_s:g}",
            "--step-length", str(STEP_LENGTH_S), "--seed", str(seed), "--random", "false",
            "--tripinfo-output", str(trip), "--no-step-log", "true", "--no-warnings", "true",
        ], check=True, capture_output=True)
    return trip


def mean_time_loss(trip: Path, start_s: float, end_s: float) -> float:
    losses = [float(t.get("timeLoss")) for t in ET.parse(trip).getroot().iter("tripinfo")
              if start_s <= float(t.get("depart")) < end_s]
    return statistics.mean(losses)


def main(argv=None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source = ReportSource(RcrcReplayStorage(RCRC_REPLAY_DATABASE_PATH))
    mapping = load_network_mappings(DEFAULT_MAPPING, network_path=DEFAULT_NETWORK)
    free_flow = compute_free_flow_times(mapping, DEFAULT_NETWORK)

    # 1. Demand and route files: one per day and seed, and one per outage case and seed
    days = {}
    for case in args.cases:
        day = case.date()
        epoch = datetime.combine(day, datetime.min.time(), RIYADH) + DAY_START
        days.setdefault(day, {"epoch": epoch, "end": epoch})
        days[day]["end"] = max(days[day]["end"], case + RUN_AFTER)
    jobs = []
    for day, info in days.items():
        print(f"demand for {day} ...", flush=True)
        demands = day_demand(source, DEFAULT_MAPPING, info["epoch"], info["end"])
        for seed in args.seeds:
            folder = args.out / f"{day}" / f"s{seed}"
            folder.mkdir(parents=True, exist_ok=True)
            info[seed] = route_file(demands, mapping, free_flow, info["epoch"], info["end"], seed, folder)
    for case in args.cases:
        info = days[case.date()]
        silent = (case - timedelta(minutes=OUTAGE_WARMUP), case)
        print(f"outage demand for {case:%Y-%m-%d %H:%M} ...", flush=True)
        demands = day_demand(source, DEFAULT_MAPPING, info["epoch"], info["end"], silent=silent)
        for seed in args.seeds:
            folder = args.out / f"{case:%Y-%m-%dT%H%M}" / f"outage_s{seed}"
            folder.mkdir(parents=True, exist_ok=True)
            routes = route_file(demands, mapping, free_flow, info["epoch"], info["end"], seed, folder)
            jobs.append((case, "outage", OUTAGE_WARMUP, seed, routes, folder))

    # 2. SUMO runs: the reference per day and seed, the warm-ups per case and seed
    for day, info in days.items():
        for seed in args.seeds:
            jobs.append((day, "reference", None, seed, info[seed], info[seed].parent))
            for case in (c for c in args.cases if c.date() == day):
                for warmup in args.warmups:
                    jobs.append((case, "real", warmup, seed, info[seed], info[seed].parent))

    def run(job):
        key, kind, warmup, seed, routes, folder = job
        info = days[key.date() if isinstance(key, datetime) else key]
        if kind == "reference":
            begin = 0.0
            end = (info["end"] - info["epoch"]).total_seconds()
        else:
            begin = (key - timedelta(minutes=warmup) - info["epoch"]).total_seconds()
            end = (key + RUN_AFTER - info["epoch"]).total_seconds()
        return job, simulate(args.sumo_bin, DEFAULT_NETWORK, routes, seed, begin, end, folder)

    print(f"{len(jobs)} SUMO runs, {args.jobs} at a time", flush=True)
    trips = {}
    with ThreadPoolExecutor(args.jobs) as pool:
        for done, future in enumerate(as_completed([pool.submit(run, job) for job in jobs]), 1):
            job, trip = future.result()
            trips[job[:4]] = trip
            print(f"  {done}/{len(jobs)} runs done ({(time.monotonic() - started) / 60:.0f} min)", flush=True)

    # 3. Compare: mean time loss of vehicles departing in [t, t + 1 h)
    rows = []
    for case in args.cases:
        info = days[case.date()]
        start_s = (case - info["epoch"]).total_seconds()
        end_s = start_s + MEASURED.total_seconds()
        reference = {s: mean_time_loss(trips[(case.date(), "reference", None, s)], start_s, end_s) for s in args.seeds}
        variants = [("real", w) for w in args.warmups] + [("outage", OUTAGE_WARMUP)]
        for kind, warmup in variants:
            diffs = []
            for seed in args.seeds:
                value = mean_time_loss(trips[(case, kind, warmup, seed)], start_s, end_s)
                diffs.append((value - reference[seed]) / reference[seed])
            rows.append({
                "case": f"{case:%Y-%m-%d %a %H:%M}", "warmup": f"{warmup} min" + (" estimated" if kind == "outage" else ""),
                "reference_s": round(statistics.mean(reference.values()), 1),
                "mean_diff": round(statistics.mean(diffs), 4),
                "seed_diffs": " ".join(f"{d:+.1%}" for d in diffs),
                "seed_spread": round((max(reference.values()) - min(reference.values())) / statistics.mean(reference.values()), 4),
            })

    with (args.out / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\nMean difference from the run since 03:00 (mean over seeds):")
    labels = [f"{w} min" for w in args.warmups] + [f"{OUTAGE_WARMUP} min estimated"]
    print(f"{'case':22}" + "".join(f"{label:>18}" for label in labels))
    for case in dict.fromkeys(r["case"] for r in rows):
        values = {r["warmup"]: r["mean_diff"] for r in rows if r["case"] == case}
        print(f"{case:22}" + "".join(f"{values[label]:>+18.1%}" for label in labels))

    passing = [w for w in args.warmups
               if all(abs(r["mean_diff"]) <= args.tolerance for r in rows if r["warmup"] == f"{w} min")]
    estimated_ok = all(abs(r["mean_diff"]) <= args.tolerance for r in rows if r["warmup"].endswith("estimated"))
    summary = {
        "cases": len(args.cases), "seeds": args.seeds, "tolerance": args.tolerance,
        "shortest_passing_warmup_min": min(passing) if passing else None,
        "estimated_warmup_passes": estimated_ok,
        "minutes": round((time.monotonic() - started) / 60),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nshortest warm-up within {args.tolerance:.0%} in every case: "
          + (f"{min(passing)} min" if passing else "none of those tried"))
    print(f"warm-up on estimated traffic ({OUTAGE_WARMUP} min) within {args.tolerance:.0%} in every case: "
          + ("yes" if estimated_ok else "no"))
    print(f"results: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

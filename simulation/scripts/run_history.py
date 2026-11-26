"""
Simulate whole days and keep their KPI measurements for the history.

See docs/kpi_engine.md, section 17.

For each day, one after another:

1. run the baseline simulation for 00:00-24:00 Riyadh time, with 15
   minutes of warm-up before and clearance after (run_baseline.py);
2. read its FCD into measurement records (collect_measurements);
3. store them in data/history/<date>.json.gz (backend/analytics/history.py);
4. delete the run's raw FCD and tripinfo files (about 4.3 GB a day).

Rules applied, and why:

- A day that is already stored is skipped, so an interrupted batch can
  be started again with the same dates and continues where it stopped.
- A day whose run folder already holds a completed run is not
  simulated again: its FCD is read as it is. This recovers a day whose
  run finished but whose measurements were not stored (the slow part is
  the simulation, about 9 minutes a day).
- A day that fails is reported and the batch continues with the next
  day; nothing partial is stored. The exit code is 1 if any day failed.
- Every day uses the same fixed seed (42 by default): normal historical
  simulations use one fixed seed (kpi_engine.md, decision on
  replication), so a day can always be rebuilt identically.
- Only days the source has fully released are run: a day needs its
  data to 00:15 the next day (its clearance). With the RCRC replay
  source, which runs 13 weeks behind the real clock, the demo's current
  day and everything after it are never run. A later day asked for is
  reported as not released yet, not as a failure.
- The last day defaults to the last released day, so the same command
  run every night stores the day that has just finished, and tries
  again any earlier day that failed.
- One demand source per history: if the folder holds days from another
  source, nothing is run.
- A detector silent for longer than 75 minutes is estimated with the
  plain time-slot average, as in the live update loop
  (LIVE_FALLBACK_GAP_INTERVALS), so a long outage does not stop the day.
  A day whose counts still cannot be estimated (for example a time slot
  with fewer than 3 earlier values of its day type) fails and is
  reported.

Usage, from the repository root, with the RCRC replay source running:
    python simulation/scripts/run_history.py --first-day 2026-07-13

Exit codes: 0 every released day is stored, 1 a day failed or nothing
could be run.
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Support direct invocation from any working directory without installing Jaadah.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx2

from backend.analytics.history import HISTORY_DIR, save_day, stored_days, stored_source
from backend.analytics.service import collect_measurements, load_run
from backend.demand.imputation import LIVE_FALLBACK_GAP_INTERVALS
from backend.ingestion.client import RcrcReplayClient, SyntheticTrafficClient
from jaadah.models.scenario import SimulationRunStatus
from simulation.scripts.run_baseline import (
    CLEARANCE_S,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SOURCE_URLS,
    RIYADH,
    BaselineNotStarted,
    run_baseline,
)

CLIENTS = {"rcrc": RcrcReplayClient, "synthetic": SyntheticTrafficClient}

# The raw SUMO outputs deleted once a day's measurements are stored
RAW_FILES = (Path("run") / "raw" / "fcd.xml", Path("run") / "raw" / "tripinfo.xml")


class DayOutcome(NamedTuple):
    """
    What happened to one day, with details: 'stored', 'skipped' (already
    stored), 'not released' (the source has not delivered the whole day
    yet) or 'failed'.
    """

    day: date
    status: str
    detail: str


def history_run_id(day: date, seed: int) -> str:
    """RUN_HISTORY_<date>_S<seed>, e.g. RUN_HISTORY_20261022_S42."""

    return f"RUN_HISTORY_{day:%Y%m%d}_S{seed}"


def day_end(day: date) -> datetime:
    """When a day's run window ends: 00:15 the next day, Riyadh time (its clearance)."""

    return datetime(day.year, day.month, day.day, tzinfo=RIYADH) + timedelta(days=1, seconds=CLEARANCE_S)


def last_released_day(latest: datetime) -> date:
    """
    The last day whose whole run window the source has released, given
    the end of its latest interval. Example: latest 27 Aug 08:15 gives
    26 Aug (its window ends 27 Aug 00:15); latest 27 Aug 00:00 gives
    25 Aug, because 26 Aug's clearance is not released yet.
    """

    return (latest.astimezone(RIYADH) - timedelta(seconds=CLEARANCE_S)).date() - timedelta(days=1)


def days_between(first_day: date, last_day: date) -> list[date]:
    """Every day from first_day to last_day, both included."""

    if last_day < first_day:
        raise ValueError(f"last day {last_day} is before first day {first_day}")

    return [first_day + timedelta(days=n) for n in range((last_day - first_day).days + 1)]


def run_history(
    days: list[date],
    *,
    client: RcrcReplayClient | SyntheticTrafficClient,
    source: str = "rcrc",
    seed: int = 42,
    history_dir: str | Path = HISTORY_DIR,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    keep_raw: bool = False,
    run: Callable = run_baseline,
    collect: Callable = collect_measurements,
    report: Callable[[str], None] = print,
) -> list[DayOutcome]:
    """
    Simulate and store each released day that is not stored yet; return
    one outcome per day, in the order given. run and collect are the
    simulation and FCD-reading steps (replaced in tests).

    Raises ValueError when the folder holds days from another source.
    """

    history_dir, output_root = Path(history_dir), Path(output_root)

    existing = stored_source(history_dir)
    if existing is not None and existing != source:
        raise ValueError(
            f"{history_dir} holds days from the {existing} source; a history uses one "
            f"source, so {source} days are not added. Move or delete those days first."
        )

    already = set(stored_days(history_dir))
    latest = client.fetch_latest_available_timestamp()
    options = {"source": source, "history_days": DEFAULT_HISTORY_DAYS[source],
               "fallback_gap_intervals": LIVE_FALLBACK_GAP_INTERVALS}
    outcomes = []

    for number, day in enumerate(days, start=1):
        prefix = f"[{number}/{len(days)}] {day}"

        if day in already:
            outcomes.append(DayOutcome(day, "skipped", "already stored"))
            report(f"{prefix}: already stored, skipped")
            continue

        if latest is None or day_end(day) > latest:
            released = latest.isoformat() if latest else "nothing"
            outcomes.append(DayOutcome(day, "not released", f"the source has released {released}"))
            report(f"{prefix}: not released yet ({outcomes[-1].detail}), skipped")
            continue

        started = time.monotonic()
        try:
            detail = _store_day(day, client, seed, history_dir, output_root, keep_raw, run, collect, options)
        except (BaselineNotStarted, httpx2.HTTPError, ValueError, OSError) as exc:
            outcomes.append(DayOutcome(day, "failed", str(exc)))
            report(f"{prefix}: FAILED - {exc}")
            continue

        minutes = (time.monotonic() - started) / 60
        outcomes.append(DayOutcome(day, "stored", detail))
        report(f"{prefix}: stored in {minutes:.1f} min ({detail})")

    return outcomes


def _store_day(day, client, seed, history_dir, output_root, keep_raw, run, collect, options) -> str:
    """Simulate (or reuse) one day's run, store its measurements, delete its raw files."""

    run_id = history_run_id(day, seed)
    run_dir = output_root / run_id

    if run_dir.exists():
        files = load_run(run_dir)
        if files.run.status != SimulationRunStatus.COMPLETED or not files.fcd_path.exists():
            raise ValueError(
                f"{run_dir} holds an unfinished run; delete that folder to simulate the day again"
            )
        how = "existing run reused"
    else:
        start = datetime(day.year, day.month, day.day, tzinfo=RIYADH)
        summary = run(
            start, start + timedelta(days=1),
            client=client, output_dir=run_dir, run_id=run_id, seed=seed, **options,
        )
        if summary["status"] != "completed":
            raise ValueError(f"the simulation did not complete (status {summary['status']}); see {run_dir}")
        files = load_run(run_dir)
        how = "simulated"

    path = save_day(collect(files), history_dir)

    if not keep_raw:
        for raw in RAW_FILES:
            (run_dir / raw).unlink(missing_ok=True)

    return f"{how}; {path.name}"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--first-day", required=True, type=date.fromisoformat,
                        help="First day to simulate, e.g. 2026-07-13")
    parser.add_argument("--last-day", type=date.fromisoformat,
                        help="Last day to simulate, included. Default: the last day "
                             "the source has fully released (the day before the demo's today)")
    parser.add_argument("--source", choices=sorted(CLIENTS), default="rcrc",
                        help="Traffic source (default rcrc)")
    parser.add_argument("--source-url",
                        help="Default: http://127.0.0.1:8002 (rcrc), :8000 (synthetic)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--keep-raw", action="store_true",
                        help="Keep each day's FCD and tripinfo files (about 4.3 GB a day)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    client = CLIENTS[args.source](args.source_url or DEFAULT_SOURCE_URLS[args.source])

    try:
        last_day = args.last_day
        if last_day is None:
            latest = client.fetch_latest_available_timestamp()
            if latest is None:
                raise ValueError("the source has released no data yet")
            last_day = last_released_day(latest)
        days = days_between(args.first_day, last_day)
        outcomes = run_history(
            days, client=client, source=args.source, seed=args.seed,
            history_dir=args.history_dir, keep_raw=args.keep_raw,
        )
    except (ValueError, httpx2.HTTPError) as exc:
        print(exc, file=sys.stderr)
        return 1

    counts = {s: sum(o.status == s for o in outcomes)
              for s in ("stored", "skipped", "not released", "failed")}
    print(f"\n{len(days)} days: stored {counts['stored']}, "
          f"already stored {counts['skipped']}, not released {counts['not released']}, "
          f"failed {counts['failed']}")
    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"  {outcome.day}: {outcome.detail}")

    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

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

Usage, from the repository root, with the synthetic source running:
    python simulation/scripts/run_history.py --first-day 2026-10-27 --last-day 2026-11-09

Exit codes: 0 every day is stored, 1 at least one day failed.
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

from backend.analytics.history import HISTORY_DIR, save_day, stored_days
from backend.analytics.service import collect_measurements, load_run
from backend.ingestion.client import SyntheticTrafficClient
from jaadah.models.scenario import SimulationRunStatus
from simulation.scripts.run_baseline import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SOURCE_URL,
    RIYADH,
    BaselineNotStarted,
    run_baseline,
)

# The raw SUMO outputs deleted once a day's measurements are stored
RAW_FILES = (Path("run") / "raw" / "fcd.xml", Path("run") / "raw" / "tripinfo.xml")


class DayOutcome(NamedTuple):
    """What happened to one day: 'stored', 'skipped' or 'failed', with details."""

    day: date
    status: str
    detail: str


def history_run_id(day: date, seed: int) -> str:
    """RUN_HISTORY_<date>_S<seed>, e.g. RUN_HISTORY_20261022_S42."""

    return f"RUN_HISTORY_{day:%Y%m%d}_S{seed}"


def days_between(first_day: date, last_day: date) -> list[date]:
    """Every day from first_day to last_day, both included."""

    if last_day < first_day:
        raise ValueError(f"last day {last_day} is before first day {first_day}")

    return [first_day + timedelta(days=n) for n in range((last_day - first_day).days + 1)]


def run_history(
    days: list[date],
    *,
    client: SyntheticTrafficClient,
    seed: int = 42,
    history_dir: str | Path = HISTORY_DIR,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    keep_raw: bool = False,
    run: Callable = run_baseline,
    collect: Callable = collect_measurements,
    report: Callable[[str], None] = print,
) -> list[DayOutcome]:
    """
    Simulate and store each day that is not stored yet; return one
    outcome per day, in the order given. run and collect are the
    simulation and FCD-reading steps (replaced in tests).
    """

    history_dir, output_root = Path(history_dir), Path(output_root)
    already = set(stored_days(history_dir))
    outcomes = []

    for number, day in enumerate(days, start=1):
        prefix = f"[{number}/{len(days)}] {day}"

        if day in already:
            outcomes.append(DayOutcome(day, "skipped", "already stored"))
            report(f"{prefix}: already stored, skipped")
            continue

        started = time.monotonic()
        try:
            detail = _store_day(day, client, seed, history_dir, output_root, keep_raw, run, collect)
        except (BaselineNotStarted, httpx2.HTTPError, ValueError, OSError) as exc:
            outcomes.append(DayOutcome(day, "failed", str(exc)))
            report(f"{prefix}: FAILED - {exc}")
            continue

        minutes = (time.monotonic() - started) / 60
        outcomes.append(DayOutcome(day, "stored", detail))
        report(f"{prefix}: stored in {minutes:.1f} min ({detail})")

    return outcomes


def _store_day(day, client, seed, history_dir, output_root, keep_raw, run, collect) -> str:
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
            client=client, output_dir=run_dir, run_id=run_id, seed=seed,
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
                        help="First day to simulate, e.g. 2026-10-27")
    parser.add_argument("--last-day", required=True, type=date.fromisoformat,
                        help="Last day to simulate, included, e.g. 2026-11-09")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--keep-raw", action="store_true",
                        help="Keep each day's FCD and tripinfo files (about 4.3 GB a day)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        days = days_between(args.first_day, args.last_day)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    outcomes = run_history(
        days, client=SyntheticTrafficClient(args.source_url), seed=args.seed,
        history_dir=args.history_dir, keep_raw=args.keep_raw,
    )

    counts = {s: sum(o.status == s for o in outcomes) for s in ("stored", "skipped", "failed")}
    print(f"\n{len(days)} days: stored {counts['stored']}, "
          f"already stored {counts['skipped']}, failed {counts['failed']}")
    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"  {outcome.day}: {outcome.detail}")

    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

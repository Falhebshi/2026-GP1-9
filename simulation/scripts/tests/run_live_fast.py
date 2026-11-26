"""
Run the live update loop through a stretch of real data as fast as it
can go: a soak test that takes an hour instead of a day.

The real loop waits for the source to deliver each 15-minute interval.
This check gives it the intervals of the RCRC replay back to back
instead, from the replay's stored report, so a whole day (its peaks, the
03:00 handover to the next day's chain, and the cleaning up) runs in
about the time the updates themselves take. After every update it
reports how long the update took and how much disk the loop uses.

It shows what a day-long run would show about the loop: that every
update finishes well inside 15 minutes, also at the evening peak; that
the disk use stays flat because old files are removed; and that the
03:00 handover starts the next day's chain. It does not show the parts
that depend on real time: waiting for the source, the page's clock, a
laptop going to sleep, and removing a chain's working folder 24 hours
after its last update (that rule reads the files' real times). The
loop's own clock is set to the data time.

Usage, from the repository root (the replay's report must be loaded;
the replay server does not need to run):

    python simulation/scripts/tests/run_live_fast.py --first 2026-08-18T02:45 --last 2026-08-19T03:30

The working files and the page files go to
simulation/outputs/tests/live_fast/work/ and .../live_fast/live/
(ignored by git), never to the page's live folder. The report, one line per update, is written there as
report.csv; it holds timings and file sizes only, no traffic data.

Exit codes: 0 every update ran, 1 an update failed or the loop paused,
2 the check could not start.
"""

import argparse
import csv
import logging
import resource
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ingestion.client import RcrcBatch  # noqa: E402
from simulation.live.chain import INTERVAL, RIYADH  # noqa: E402
from simulation.live.loop import LiveLoop, LoopSettings  # noqa: E402
from simulation.scripts.run_baseline import DEFAULT_MAPPING, DEFAULT_NETWORK, sumo_version  # noqa: E402
from traffic_source.rcrc_replay.config import RCRC_REPLAY_DATABASE_PATH  # noqa: E402
from traffic_source.rcrc_replay.storage import RcrcReplayStorage  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "simulation" / "outputs" / "tests" / "live_fast"


class SteppedSource:
    """
    The replay's stored report, delivered up to a time this check moves
    forward itself, with the same methods the loop uses on the replay
    client. It has no replay clock (fetch_source_clock), so the loop
    reports a clock offset of 0.
    """

    base_url = "stepped replay"

    def __init__(self, storage: RcrcReplayStorage, latest: datetime):
        info = storage.get_report_info()
        if info is None:
            raise SystemExit("the replay has no report loaded (python -m traffic_source.rcrc_replay.load ...)")
        self.storage = storage
        self.site_id = info["site_id"]
        self.latest = latest

    def fetch_latest_available_timestamp(self) -> datetime:
        return self.latest

    def fetch_observations(self, start: datetime, end: datetime) -> RcrcBatch:
        return RcrcBatch(
            site_id=self.site_id,
            records=self.storage.get_rows(after=start, through=min(end, self.latest)),
        )


def folder_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1e6


def peak_memory_mb() -> float:
    """The largest memory the process has used so far (macOS reports bytes, Linux kB)."""

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / 1e6 if sys.platform == "darwin" else value / 1e3


def parse_time(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=RIYADH)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--first", type=parse_time, required=True, help="first interval end, Riyadh time")
    parser.add_argument("--last", type=parse_time, required=True, help="last interval end, Riyadh time")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keep", action="store_true", help="continue in an existing output folder")
    parser.add_argument("--sumo-bin", default="sumo")
    args = parser.parse_args(argv)
    if args.last < args.first:
        parser.error("--last is before --first")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if args.out.exists() and not args.keep:
        shutil.rmtree(args.out)
    work, page = args.out / "work", args.out / "live"  # the publisher only writes to a folder named live

    source = SteppedSource(RcrcReplayStorage(RCRC_REPLAY_DATABASE_PATH), args.first)
    try:
        loop = LiveLoop(
            source,
            LoopSettings(
                source="rcrc", work_root=work, output_dir=page,
                mapping_path=DEFAULT_MAPPING, network_path=DEFAULT_NETWORK,
                sumo_version=sumo_version(args.sumo_bin), sumo_bin=args.sumo_bin,
            ),
            now=lambda: source.latest,
        )
    except Exception as exc:  # noqa: BLE001 - report why the check cannot start
        print(f"cannot start: {exc}")
        return 2

    rows, problems = [], []
    print(f"{'data time':16}  {'state':8}  {'update':>7}  {'chain':28}  {'work MB':>8}  {'page MB':>8}  {'memory MB':>9}")
    started = time.monotonic()
    while source.latest <= args.last:
        before = time.monotonic()
        state = loop.pass_once()
        seconds = time.monotonic() - before
        record = loop.record
        row = {
            "data_time": source.latest.strftime("%Y-%m-%d %H:%M"),
            "state": state["state"] if state else "failed",
            "seconds": round(seconds, 1),
            "chain": record.run_id if record else "",
            "segments": len(record.segments) if record else 0,
            "work_mb": round(folder_mb(work)),
            "page_mb": round(folder_mb(page)),
            "memory_mb": round(peak_memory_mb()),
        }
        rows.append(row)
        print(f"{row['data_time']:16}  {row['state']:8}  {seconds:6.1f}s  {row['chain']:28}  "
              f"{row['work_mb']:8}  {row['page_mb']:8}  {row['memory_mb']:9}", flush=True)
        if row["state"] not in ("running", "starting"):
            problems.append(f"{row['data_time']}: {row['state']}"
                            + (f" ({state.get('message')})" if state else ""))
        source.latest += INTERVAL

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "report.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # Summary: the longest update of each hour, the largest disk use, the chains
    print(f"\n{len(rows)} updates in {(time.monotonic() - started) / 60:.0f} min")
    by_hour: dict[str, float] = {}
    for row in rows:
        hour = row["data_time"][:13]
        by_hour[hour] = max(by_hour.get(hour, 0.0), row["seconds"])
    print("longest update per hour:", "  ".join(f"{h[-2:]}h {s:.0f}s" for h, s in by_hour.items()))
    print(f"longest update: {max(r['seconds'] for r in rows):.0f} s (an interval is 900 s)")
    print(f"largest work folder: {max(r['work_mb'] for r in rows)} MB; "
          f"largest page folder: {max(r['page_mb'] for r in rows)} MB; "
          f"memory: {max(r['memory_mb'] for r in rows)} MB")
    chains = list(dict.fromkeys(r["chain"] for r in rows if r["chain"]))
    print("chains:", ", ".join(chains))
    print(f"report: {args.out / 'report.csv'}")
    if problems:
        print("updates that did not run:", *problems, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

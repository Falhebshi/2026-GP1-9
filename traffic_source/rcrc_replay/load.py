"""
Load an RCRC report into the replay source and print a coverage check.

    python -m traffic_source.rcrc_replay.load <report.csv>

Loading the same file again changes nothing. Loading a different report
replaces the stored one.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from traffic_source.rcrc_replay.clock import replay_now
from traffic_source.rcrc_replay.config import (
    INTERVAL_MINUTES,
    RCRC_REPLAY_DATABASE_PATH,
    ReplayConfig,
)
from traffic_source.rcrc_replay.report import RcrcReport, read_rcrc_report
from traffic_source.rcrc_replay.storage import RcrcReplayStorage


def missing_runs(report: RcrcReport) -> dict[str, list[tuple[datetime, int]]]:
    """
    For each detector, the runs of consecutive intervals between the
    report's first and last time stamp in which it has no row, as
    (first missing interval end, number of intervals).
    """

    step = timedelta(minutes=INTERVAL_MINUTES)
    present = defaultdict(set)

    for row in report.rows:
        if row.interval_end is not None:
            present[row.values["Detector ID : Description"]].add(row.interval_end)

    if not present:
        return {}

    first = min(min(times) for times in present.values())
    last = max(max(times) for times in present.values())
    runs = {}

    for detector, times in sorted(present.items()):
        detector_runs = []
        moment, run_start, length = first, None, 0

        while moment <= last + step:
            if moment <= last and moment not in times:
                run_start = run_start or moment
                length += 1
            elif run_start is not None:
                detector_runs.append((run_start, length))
                run_start, length = None, 0
            moment += step

        runs[detector] = detector_runs

    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load an RCRC report into the replay source.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--database", type=Path, default=RCRC_REPLAY_DATABASE_PATH)
    arguments = parser.parse_args(argv)

    storage = RcrcReplayStorage(arguments.database)
    storage.initialize()

    report = read_rcrc_report(arguments.report)
    changed = storage.load_report(report)
    info = storage.get_report_info()

    print(("Loaded" if changed else "Already loaded") + f": site {report.site_id}")
    print(report.title.splitlines()[-1])
    print(
        f"Rows: {len(report.rows)}  repeated headers skipped: "
        f"{report.repeated_header_count}  rows without a readable time stamp "
        f"(never served): {len(report.undated_rows)}"
    )
    print(
        f"Data: {info['first_interval_end']:%Y-%m-%d %H:%M} to "
        f"{info['last_interval_end']:%Y-%m-%d %H:%M} (interval ends)"
    )
    config = ReplayConfig()
    print(
        f"Replay: {config.offset_weeks} weeks behind the real clock; "
        f"now showing {replay_now(datetime.now().astimezone(), config):%a %d %b %Y %H:%M}"
    )
    print()
    print(f"{'Detector':<30} {'Missing':>8} {'Longest gap':>12}")

    for detector, runs in missing_runs(report).items():
        print(
            f"{detector:<30} {sum(n for _, n in runs):>8} "
            f"{max((n for _, n in runs), default=0):>12}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

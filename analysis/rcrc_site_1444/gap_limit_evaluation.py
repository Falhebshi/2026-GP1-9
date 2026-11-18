"""
Gap-limit evaluation: how long after a site goes silent can its missing
counts still be estimated from the data before the outage?

Method:

1. Read the private RCRC site 1444 report and convert its rows with
   Jaadah's own RCRC adapter.
2. Pretend the whole site goes silent at many starting points where the
   real counts are known.
3. Estimate each missing interval k = 1, 2, ... of the pretend outage
   with Jaadah's own estimate functions (backend.demand.imputation),
   twice:
     - plain: the time-slot average (same time of day and day type);
     - level-adjusted: that average scaled by how busy the hour before
       the outage was compared with a typical day.
   Only data from before the outage day is used for the averages, as a
   live system would have.
4. Compare both with the real counts at each position k.

The gap limit is the longest outage for which the level-adjusted
estimate is better than the plain average on both measures at every
position: beyond it, the data from before the outage no longer helps,
and the estimate would only describe a typical day.

    python analysis/rcrc_site_1444/gap_limit_evaluation.py <report.csv>
"""

import argparse
import math
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.demand.imputation import (  # noqa: E402
    MIN_HISTORICAL_VALUES,
    RECENT_LEVEL_INTERVALS,
    day_type,
    level_adjusted_estimate,
    level_ratio,
)
from backend.ingestion.adapter import adapt_rcrc_record  # noqa: E402
from traffic_source.rcrc_replay.report import read_rcrc_report  # noqa: E402


INTERVAL = timedelta(minutes=15)
MAX_POSITION = 16
GEH_LIMIT = 5.0


def load_counts(path: Path) -> dict[str, dict]:
    """Counts per detector, keyed by interval start."""

    report = read_rcrc_report(path)
    counts = defaultdict(dict)

    for row in report.rows:
        observation = adapt_rcrc_record(row.values, site_id=report.site_id)
        counts[observation.detector_id][observation.interval_start] = (
            observation.vehicle_count
        )

    return counts


def past_slot_averages(counts: dict) -> dict:
    """
    For each interval, the average count in its time slot and day type
    on earlier days only, or None with fewer than MIN_HISTORICAL_VALUES.
    """

    groups = defaultdict(list)

    for moment in sorted(counts):
        groups[(moment.time(), day_type(moment))].append(moment)

    averages = {}

    for moments in groups.values():
        total, number = 0.0, 0

        for moment in moments:
            averages[moment] = total / number if number >= MIN_HISTORICAL_VALUES else None
            total += counts[moment]
            number += 1

    return averages


def geh(model: float, count: float) -> float:
    """GEH on hourly flows (15-minute counts x 4)."""

    model, count = model * 4, count * 4

    return 0.0 if model + count == 0 else math.sqrt(2 * (model - count) ** 2 / (model + count))


def evaluate(
    counts: dict[str, dict],
    every: int,
    window: int = RECENT_LEVEL_INTERVALS,
) -> list[dict]:
    """
    Error of both estimates at each position of a pretend outage.
    window is the number of intervals before the outage used for the
    level ratio (Jaadah uses RECENT_LEVEL_INTERVALS).
    """

    averages = {detector: past_slot_averages(c) for detector, c in counts.items()}
    starts = sorted(set.intersection(*(set(c) for c in counts.values())))
    totals = {
        k: {"actual": 0.0, "plain": 0.0, "adjusted": 0.0,
            "geh_plain": 0, "geh_adjusted": 0, "cases": 0}
        for k in range(1, MAX_POSITION + 1)
    }
    outages = 0

    for start in starts[::every]:
        recent = [start - step * INTERVAL for step in range(window, 0, -1)]
        positions = [start + (k - 1) * INTERVAL for k in range(1, MAX_POSITION + 1)]
        usable = True

        for detector, detector_counts in counts.items():
            needed = recent + positions

            if any(m not in detector_counts or averages[detector].get(m) is None for m in needed):
                usable = False
                break

        if not usable:
            continue

        outages += 1

        for detector, detector_counts in counts.items():
            ratio = level_ratio(
                [detector_counts[m] for m in recent],
                [averages[detector][m] for m in recent],
            )

            for k, moment in enumerate(positions, start=1):
                actual = detector_counts[moment]
                average = averages[detector][moment]
                plain = level_adjusted_estimate(average, None)
                adjusted = level_adjusted_estimate(average, ratio)
                row = totals[k]
                row["actual"] += actual
                row["plain"] += abs(plain - actual)
                row["adjusted"] += abs(adjusted - actual)
                row["geh_plain"] += geh(plain, actual) < GEH_LIMIT
                row["geh_adjusted"] += geh(adjusted, actual) < GEH_LIMIT
                row["cases"] += 1

    results = []

    for k, row in totals.items():
        results.append({
            "position": k,
            "error_plain": row["plain"] / row["actual"],
            "error_adjusted": row["adjusted"] / row["actual"],
            "geh_plain": row["geh_plain"] / row["cases"],
            "geh_adjusted": row["geh_adjusted"] / row["cases"],
            "cases": row["cases"],
        })

    return outages, results


def deviation_persistence(counts: dict[str, dict], lags=(1, 4, 8, 24)) -> dict[int, float]:
    """
    How long today's deviation from a typical day lasts: the correlation,
    averaged over detectors, between log(count / time-slot average) in
    one interval and `lag` intervals later. Intervals with a time-slot
    average below 5 vehicles are left out, so night counts do not
    dominate.
    """

    result = {}

    for lag in lags:
        correlations = []

        for detector_counts in counts.values():
            averages = past_slot_averages(detector_counts)
            deviation = {
                moment: math.log((count + 1) / (averages[moment] + 1))
                for moment, count in detector_counts.items()
                if averages.get(moment) is not None and averages[moment] >= 5
            }
            pairs = [
                (value, deviation[moment + lag * INTERVAL])
                for moment, value in deviation.items()
                if moment + lag * INTERVAL in deviation
            ]

            if len(pairs) > 2:
                correlations.append(_correlation(pairs))

        result[lag] = sum(correlations) / len(correlations)

    return result


def _correlation(pairs: list[tuple[float, float]]) -> float:
    n = len(pairs)
    mean_x = sum(x for x, _ in pairs) / n
    mean_y = sum(y for _, y in pairs) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    var_x = sum((x - mean_x) ** 2 for x, _ in pairs)
    var_y = sum((y - mean_y) ** 2 for _, y in pairs)

    return cov / math.sqrt(var_x * var_y) if var_x and var_y else 0.0


def gap_limit(results: list[dict]) -> int:
    """
    The longest outage for which the level-adjusted estimate beats the
    plain average on both measures at every position up to it.
    """

    limit = 0

    for row in results:
        if row["error_adjusted"] < row["error_plain"] and row["geh_adjusted"] > row["geh_plain"]:
            limit = row["position"]
        else:
            break

    return limit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("report", type=Path)
    parser.add_argument("--every", type=int, default=3,
                        help="Use every n-th interval as an outage start (default 3).")
    arguments = parser.parse_args(argv)

    counts = load_counts(arguments.report)
    outages, results = evaluate(counts, arguments.every)

    print("Persistence of today's deviation from a typical day:")

    for lag, correlation in deviation_persistence(counts).items():
        print(f"  after {lag * 15} minutes: {correlation:.2f}")

    print()
    print(f"Pretend site-wide outages evaluated: {outages}")
    print()
    print("| Position | Error, plain | Error, level-adjusted | GEH < 5, plain | GEH < 5, level-adjusted |")
    print("|---:|---:|---:|---:|---:|")

    for row in results:
        print(
            f"| {row['position']} | {row['error_plain']:.1%} | {row['error_adjusted']:.1%} "
            f"| {row['geh_plain']:.1%} | {row['geh_adjusted']:.1%} |"
        )

    print()
    print(f"Gap limit: {gap_limit(results)} intervals")
    print()
    print("Length of the period before the outage used for the level ratio")
    print(f"(Jaadah uses {RECENT_LEVEL_INTERVALS * 15} min, RECENT_LEVEL_INTERVALS = {RECENT_LEVEL_INTERVALS}):")
    print()
    print("| Period before | Error, 1st | GEH < 5, 1st | Error, 5th | GEH < 5, 5th | Gap limit |")
    print("|---:|---:|---:|---:|---:|---:|")

    for window in (2, 4, 8):
        _, compared = evaluate(counts, arguments.every, window=window)
        first, fifth = compared[0], compared[4]
        print(
            f"| {window * 15} min | {first['error_adjusted']:.1%} | {first['geh_adjusted']:.1%} "
            f"| {fifth['error_adjusted']:.1%} | {fifth['geh_adjusted']:.1%} | {gap_limit(compared)} |"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
All-day fixed signal plan from the RCRC site 1444 counts (Webster).

The model's signal plan is one fixed-time plan for the whole day, with
one phase per approach in the order E, S, W, N, each followed by 3 s
yellow and 2 s all-red. This script derives that plan from the private
RCRC report, so the plan in the network can be reproduced and replaced
when more data (or RCRC's own timing sheet) arrives.

Method (docs/sumo_network.md, "Signal plan"):

1. Read the report with Jaadah's RCRC adapter and add up each lane's
   counts per clock hour (complete hours only).
2. Flow ratio of a lane: hourly volume / saturation flow, with the KPI
   engine's values (backend/analytics/kpi/parameters.py): 1,900 veh/h
   for a through lane; left and shared left-through lanes divided by
   the left-turn equivalent 1.05. The critical flow ratio of a phase is
   that of its busiest lane; Y is the sum over the four phases.
3. Cycle: Webster's optimum C0 = (1.5 L + 5) / (1 - Y), with L the lost
   time per cycle (4 phases x 5 s, as in the KPI engine), at the
   workday morning peak (07:00-09:00), where Y is clearly below 1 and
   the formula holds. The cycle is the length dividing 900 s that is
   nearest to it, so that a later time-of-day plan can switch on any
   15-minute boundary without cutting a cycle.
4. Greens: the cycle's effective green (C - L) split in proportion to
   each phase's critical flow ratio added up over every complete hour
   of the report, every day type and time of day included, rounded to
   whole seconds (Webster's equal-saturation rule). Busy hours weigh
   more because they carry more traffic; no hours are picked by hand.
   With the KPI engine's lost times, effective green equals the
   displayed green.

Workdays are Sunday to Thursday. Only the plan and a short check are
printed; no data are written.

    python analysis/rcrc_site_1444/webster_plan.py <report.csv>
"""

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.analytics.kpi.parameters import (  # noqa: E402
    BASE_SATURATION_FLOW_PC_H_LN,
    LEFT_TURN_EQUIVALENT,
)
from backend.ingestion.adapter import adapt_rcrc_record  # noqa: E402
from traffic_source.rcrc_replay.report import read_rcrc_report  # noqa: E402


PHASES = ("E", "S", "W", "N")
YELLOW_S = 3
ALL_RED_S = 2
PHASE_LOST_TIME_S = YELLOW_S + ALL_RED_S
LOST_TIME_S = PHASE_LOST_TIME_S * len(PHASES)
CYCLES_DIVIDING_15_MIN = (90, 100, 150, 180, 225, 300, 450)

PEAK_HOURS = (7, 8)

# Site 1444 detectors: approach (phase) and lane turns, from the RCRC
# descriptions (docs/network_mapping.md, "RCRC site 1444 detectors").
DETECTOR_LANES = {
    "144409": ("S", "L"), "144410": ("S", "L"),
    "144411": ("W", "L"), "144412": ("W", "TL"), "144413": ("W", "T"),
    "144414": ("N", "L"), "144415": ("N", "L"), "144416": ("N", "L"),
    "144417": ("E", "L"), "144418": ("E", "TL"),
    "144419": ("E", "T"), "144420": ("E", "T"),
}


def saturation_flow(turns: str) -> float:
    """Saturation flow of one lane, veh/h (through, or left-equivalent)."""

    if turns == "T":
        return float(BASE_SATURATION_FLOW_PC_H_LN)

    return BASE_SATURATION_FLOW_PC_H_LN / LEFT_TURN_EQUIVALENT


def hourly_volumes(observations) -> dict[tuple, dict[str, int]]:
    """Lane volumes per (date, hour), for hours with all four intervals of every lane."""

    totals: dict[tuple, int] = defaultdict(int)
    intervals: dict[tuple, int] = defaultdict(int)

    for detector_id, interval_start, vehicle_count in observations:
        key = (interval_start.date(), interval_start.hour, detector_id)
        totals[key] += vehicle_count
        intervals[key] += 1

    hours: dict[tuple, dict[str, int]] = defaultdict(dict)
    for (day, hour, detector_id), volume in totals.items():
        if intervals[(day, hour, detector_id)] == 4:
            hours[(day, hour)][detector_id] = volume

    return {key: lanes for key, lanes in hours.items() if set(lanes) == set(DETECTOR_LANES)}


def critical_flow_ratios(volumes: dict[str, int]) -> dict[str, float]:
    """Critical flow ratio of each phase: that of its busiest lane."""

    return {
        phase: max(
            volumes[detector_id] / saturation_flow(turns)
            for detector_id, (approach, turns) in DETECTOR_LANES.items()
            if approach == phase
        )
        for phase in PHASES
    }


def webster_cycle(flow_ratio_sum: float, lost_time_s: float = LOST_TIME_S) -> float:
    """Webster's optimum cycle length, s."""

    if not 0 <= flow_ratio_sum < 1:
        raise ValueError(f"Webster's formula needs 0 <= Y < 1, got {flow_ratio_sum:.3f}")

    return (1.5 * lost_time_s + 5) / (1 - flow_ratio_sum)


def nearest_cycle(cycle_s: float) -> int:
    """The cycle length dividing 900 s nearest to cycle_s."""

    return min(CYCLES_DIVIDING_15_MIN, key=lambda c: (abs(c - cycle_s), c))


def split_greens(cycle_s: int, weights: dict[str, float]) -> dict[str, int]:
    """Whole-second greens in proportion to weights, adding up to the effective green."""

    effective = cycle_s - LOST_TIME_S
    total = sum(weights.values())
    exact = {phase: effective * weights[phase] / total for phase in PHASES}
    greens = {phase: int(exact[phase]) for phase in PHASES}

    for phase in sorted(PHASES, key=lambda p: exact[p] - greens[p], reverse=True):
        if sum(greens.values()) == effective:
            break
        greens[phase] += 1

    return greens


def is_workday(day) -> bool:
    return day.weekday() not in (4, 5)   # Friday, Saturday


def derive_plan(observations) -> tuple[int, dict[str, int], dict]:
    """The cycle, the greens and the figures they come from."""

    ratios = {
        key: critical_flow_ratios(volumes)
        for key, volumes in hourly_volumes(observations).items()
    }
    workday = {key: r for key, r in ratios.items() if is_workday(key[0])}

    peak_cycles = [
        webster_cycle(statistics.median(sum(r.values()) for (day, hour), r in workday.items() if hour == h))
        for h in PEAK_HOURS
    ]
    cycle = nearest_cycle(statistics.fmean(peak_cycles))

    weights = {phase: sum(r[phase] for r in ratios.values()) for phase in PHASES}
    greens = split_greens(cycle, weights)

    return cycle, greens, {"peak_webster_cycles_s": peak_cycles, "phase_weights": weights}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("report", type=Path, help="the private RCRC site 1444 report (CSV)")
    args = parser.parse_args()

    report = read_rcrc_report(args.report)
    observations = []
    for row in report.rows:
        observation = adapt_rcrc_record(row.values, report.site_id)
        observations.append((observation.detector_id, observation.interval_start, observation.vehicle_count))

    cycle, greens, figures = derive_plan(observations)

    print("Webster cycle at the workday morning peak: "
          + ", ".join(f"{c:.0f} s" for c in figures["peak_webster_cycles_s"]))
    print(f"Cycle (dividing 900 s): {cycle} s")
    print("Greens E/S/W/N: " + " / ".join(str(greens[p]) for p in PHASES)
          + f"  (+ {PHASE_LOST_TIME_S} s yellow and all-red after each)")


if __name__ == "__main__":
    main()

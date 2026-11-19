"""
Calibration and validation charts for the report (section 5.1).

Reads the detail files written by simulation/scripts/run_calibration.py
and draws two figures, each with calibration and validation side by side:

1. observed against simulated hourly count, one point per detector-hour
   (mean of the seeds), with the line of perfect agreement and the band
   where GEH < 5; within-capacity and over-capacity hours are told apart
   by colour and marker shape;
2. the distribution of GEH, stacked by within and over capacity, with
   the GEH = 5 threshold marked.

The figures show values derived from RCRC data, so they are written to
the private data folder, never to the repository:
    ../jaadah-private-data/processed/calibration/figures/

Example:
    python analysis/calibration/calibration_charts.py
    python analysis/calibration/calibration_charts.py --calibration calibration_final --validation validation_final
"""

import argparse
import csv
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jaadah.calibration.parameters import GEH_THRESHOLD
from traffic_source.rcrc_replay.config import PRIVATE_DATA_DIR

RESULTS_DIR = PRIVATE_DATA_DIR / "processed" / "calibration" / "results"
FIGURES_DIR = PRIVATE_DATA_DIR / "processed" / "calibration" / "figures"

# Colours: categorical slots 1 and 2 of the team's chart palette, checked
# for colour-vision deficiency; marker shape repeats the distinction.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
WITHIN = {"label": "Within capacity", "color": "#2a78d6", "marker": "o"}
OVER = {"label": "Over capacity", "color": "#eb6834", "marker": "^"}
UNKNOWN = {"label": "Capacity unknown", "color": "#9a9993", "marker": "s"}

GEH_BIN_WIDTH = 1.0
GEH_LAST_BIN = 15.0   # GEH at or above this is drawn in one "15+" bar


# ============================================================
# DATA
# ============================================================

def read_results(path: Path) -> list[dict]:
    """Rows of a run_calibration.py detail file, with numbers parsed."""

    rows = []
    with Path(path).open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            rows.append({
                "observed": float(row["observed_veh_h"]),
                "simulated": float(row["simulated_veh_h"]),
                "geh": float(row["geh"]),
                "match": row["match"] == "True",
                "capacity": {"True": "within", "False": "over"}.get(row.get("within_capacity", ""), "unknown"),
            })
    return rows


def geh_band(observed: float, threshold: float = GEH_THRESHOLD) -> tuple[float, float]:
    """
    Simulated counts with GEH exactly at the threshold, for one observed count.

    From GEH^2 = 2 (M - C)^2 / (M + C), with k = GEH^2 / 2:
    (M - C)^2 = k (M + C), so M = C + k/2 +- sqrt(k^2/4 + 2 k C).
    """

    k = threshold ** 2 / 2
    spread = math.sqrt(k * k / 4 + 2 * k * observed)
    return max(0.0, observed + k / 2 - spread), observed + k / 2 + spread


def geh_histogram(rows: list[dict]) -> tuple[list[float], dict[str, list[int]]]:
    """Bin left edges and the count per capacity class in each bin."""

    edges = [i * GEH_BIN_WIDTH for i in range(int(GEH_LAST_BIN / GEH_BIN_WIDTH) + 1)]
    counts = {name: [0] * len(edges) for name in ("within", "over", "unknown")}
    for row in rows:
        index = min(int(row["geh"] // GEH_BIN_WIDTH), len(edges) - 1)
        counts[row["capacity"]][index] += 1
    return edges, counts


def pass_share(rows: list[dict]) -> float:
    return sum(row["match"] for row in rows) / len(rows) if rows else float("nan")


# ============================================================
# DRAWING
# ============================================================

def _style(axis, plt):
    axis.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(TEXT_SECONDARY)
        axis.spines[side].set_linewidth(0.8)
    axis.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    axis.grid(color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)


def _classes(rows):
    present = []
    for style, name in ((WITHIN, "within"), (OVER, "over"), (UNKNOWN, "unknown")):
        subset = [row for row in rows if row["capacity"] == name]
        if subset:
            present.append((style, name, subset))
    return present


def scatter_figure(sets: list[tuple[str, list[dict]]], plt):
    """Observed against simulated, one panel per set, shared scales."""

    top = max(max(r["observed"], r["simulated"]) for _, rows in sets for r in rows) * 1.05
    figure, axes = plt.subplots(1, len(sets), figsize=(5.2 * len(sets), 5.0), sharex=True, sharey=True)
    figure.patch.set_facecolor(SURFACE)
    axes = axes if len(sets) > 1 else [axes]

    line = [i * top / 200 for i in range(201)]
    low = [geh_band(c)[0] for c in line]
    high = [geh_band(c)[1] for c in line]

    for axis, (name, rows) in zip(axes, sets):
        _style(axis, plt)
        axis.fill_between(line, low, high, color=GRID, alpha=0.7, linewidth=0,
                          label=f"GEH < {GEH_THRESHOLD:g}")
        axis.plot([0, top], [0, top], color=TEXT_SECONDARY, linewidth=1.2, label="Simulated = observed")
        for style, _, subset in _classes(rows):
            axis.scatter(
                [r["observed"] for r in subset], [r["simulated"] for r in subset],
                s=26, marker=style["marker"], color=style["color"], alpha=0.85,
                edgecolors=SURFACE, linewidths=0.8, label=f"{style['label']} ({len(subset)})",
            )
        axis.set_xlim(0, top)
        axis.set_ylim(0, top)
        axis.set_aspect("equal")
        axis.set_title(
            f"{name}: {pass_share(rows):.1%} of {len(rows)} detector-hours with GEH < {GEH_THRESHOLD:g}",
            fontsize=10, color=TEXT, loc="left",
        )
        axis.set_xlabel("Observed (veh/h)", fontsize=9, color=TEXT_SECONDARY)
    axes[0].set_ylabel("Simulated, mean of seeds (veh/h)", fontsize=9, color=TEXT_SECONDARY)
    axes[-1].legend(loc="upper left", fontsize=8, frameon=False, labelcolor=TEXT)
    figure.tight_layout()
    return figure


def histogram_figure(sets: list[tuple[str, list[dict]]], plt):
    """GEH distribution, stacked by capacity class, one panel per set."""

    figure, axes = plt.subplots(1, len(sets), figsize=(5.2 * len(sets), 3.8), sharey=True)
    figure.patch.set_facecolor(SURFACE)
    axes = axes if len(sets) > 1 else [axes]
    width = GEH_BIN_WIDTH * 0.86   # a gap of surface between bars

    for axis, (name, rows) in zip(axes, sets):
        _style(axis, plt)
        axis.grid(axis="x", visible=False)
        edges, counts = geh_histogram(rows)
        centres = [edge + GEH_BIN_WIDTH / 2 for edge in edges]
        bottom = [0] * len(edges)
        for style, key in ((WITHIN, "within"), (OVER, "over"), (UNKNOWN, "unknown")):
            if not any(counts[key]):
                continue
            axis.bar(centres, counts[key], width=width, bottom=bottom, color=style["color"],
                     edgecolor=SURFACE, linewidth=1.0, label=style["label"])
            bottom = [b + c for b, c in zip(bottom, counts[key])]
        axis.axvline(GEH_THRESHOLD, color=TEXT, linewidth=1.2, linestyle=(0, (4, 3)))
        axis.text(GEH_THRESHOLD + 0.15, max(bottom) * 0.97, f"GEH = {GEH_THRESHOLD:g}",
                  fontsize=8, color=TEXT, va="top")
        axis.set_xticks(edges)
        axis.set_xticklabels([f"{e:g}" for e in edges[:-1]] + [f"{GEH_LAST_BIN:g}+"], fontsize=8)
        axis.set_xlim(0, GEH_LAST_BIN + GEH_BIN_WIDTH)
        axis.set_title(f"{name}: {pass_share(rows):.1%} below {GEH_THRESHOLD:g}",
                       fontsize=10, color=TEXT, loc="left")
        axis.set_xlabel("GEH (hourly)", fontsize=9, color=TEXT_SECONDARY)
    axes[0].set_ylabel("Detector-hours", fontsize=9, color=TEXT_SECONDARY)
    axes[-1].legend(loc="upper right", fontsize=8, frameon=False, labelcolor=TEXT)
    figure.tight_layout()
    return figure


# ============================================================
# COMMAND LINE
# ============================================================

def results_path(value: str) -> Path:
    """A results label (e.g. calibration_final) or a path to a .csv."""

    path = Path(value)
    return path if path.suffix == ".csv" else RESULTS_DIR / f"{value}.csv"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Draw the calibration and validation charts.")
    parser.add_argument("--calibration", type=results_path, default=results_path("calibration_final"))
    parser.add_argument("--validation", type=results_path, default=results_path("validation_final"))
    parser.add_argument("--out", type=Path, default=FIGURES_DIR)
    args = parser.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sets = []
    for name, path in (("Calibration", args.calibration), ("Validation", args.validation)):
        if not path.is_file():
            print(f"Results file not found: {path}", file=sys.stderr)
            return 2
        sets.append((name, read_results(path)))

    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, figure in (
        ("observed_vs_simulated", scatter_figure(sets, plt)),
        ("geh_distribution", histogram_figure(sets, plt)),
    ):
        for suffix in ("png", "svg"):
            path = args.out / f"{stem}.{suffix}"
            figure.savefig(path, dpi=300, facecolor=SURFACE)
            written.append(path)
        plt.close(figure)

    print("Figures written:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Check the network map against the counts at the study intersection.

Step 7 of the Macro Map synthetic traffic. The map's city level in every
15 minutes is calibrated to TomTom (observed.py), so agreeing with
TomTom proves nothing. What can be checked against something the map
was not fitted to is the study intersection (RCRC Site 1444), on weeks
after the calibration weeks:

1. Pattern within the day: is the map's v/c on the roads arriving at
   the intersection high when the counted v/c is high? Each day's two
   series are divided by their own mean, so the day factor (which comes
   from the same counts) plays no part. TomTom's index alone is scored
   the same way, to show what the map adds to TomTom.
2. Peak times: the hour of the morning and evening peak in the counts
   and on the map, and whether the evening is the busier one in both.
3. Which approach is fuller: the four approaches ranked by their
   counted v/c and by the map's v/c, at the morning and evening peaks.

The counts are read and kept in memory only: the script prints summary
numbers (correlations, shares, hours), never a count or a v/c of the
intersection, and writes nothing.

    python -m jaadah.network_congestion.validation

The validation weeks are later than the RCRC replay has released (it
runs weeks behind the real clock), so by default the script reads the
private replay database itself, with every interval released, in this
process only; --url uses a running RCRC source instead.
"""

import argparse
from pathlib import Path
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from backend.demand.service import build_simulation_demand
from backend.ingestion.client import RcrcBatch, RcrcReplayClient
from backend.ingestion.service import ingest_rcrc_observations
from jaadah.network_congestion.observed import (
    approach_volume_to_capacity,
    approach_ways,
    day_factors,
    hourly_flows,
    interval_speeds,
    site_capacity,
    site_centre,
    site_segments,
    slot_of,
    tomtom_index,
)
from jaadah.network_congestion.parameters import IMPUTATION_HISTORY_DAYS
from jaadah.network_congestion.observed import build_model, load_road_network, load_site_inputs
from jaadah.network_congestion.parameters import CALIBRATION_START, CALIBRATION_WEEKS, NETWORK_SPREAD
from jaadah.network_congestion.producer import load_observed_model, observed_site_levels
from jaadah.network_congestion.storage import RIYADH
from jaadah.network_congestion.synthetic import DEFAULT_MAPPINGS

# Weeks after the calibration weeks (13 July to 16 August) and after the
# late-August rise in traffic, without National Day week (20 to 26
# September), as in the micro calibration decision
VALIDATION_PERIODS = (
    (date(2026, 8, 30), date(2026, 9, 19)),
    (date(2026, 9, 27), date(2026, 10, 10)),
)
MORNING_HOURS = range(6, 10)
EVENING_HOURS = range(15, 19)


# ============================================================
# SCORES (pure, tested without RCRC data)
# ============================================================

def day_type(day: date) -> str:
    return {4: "Friday", 5: "Saturday"}.get(day.weekday(), "workday")


def daily_shape_correlations(
    observed: dict[datetime, float],
    model: dict[datetime, float],
    min_intervals: int = 48,
) -> dict[date, float]:
    """
    For each day, Pearson r between the two series, each divided by its
    own mean over the day (so a day-wide factor makes no difference).
    Days with fewer common intervals than min_intervals are left out.
    """

    by_day: dict[date, list[tuple[float, float]]] = defaultdict(list)

    for moment, value in observed.items():
        if moment in model:
            by_day[moment.date()].append((value, model[moment]))

    result = {}

    for day, pairs in by_day.items():
        if len(pairs) < min_intervals:
            continue
        a, b = np.array(pairs).T
        if a.std() == 0 or b.std() == 0:
            continue
        result[day] = float(np.corrcoef(a / a.mean(), b / b.mean())[0, 1])

    return result


def peak_hour(series: dict[datetime, float], hours: range) -> float | None:
    """The start of the busiest hour (four quarter hours) within the given hours, in hours."""

    values = {slot_of(m): v for m, v in series.items()}
    best, best_slot = None, None

    for slot in range(hours.start * 4, hours.stop * 4 - 3):
        window = [values.get(slot + k) for k in range(4)]
        if None in window:
            continue
        total = sum(window)
        if best is None or total > best:
            best, best_slot = total, slot

    return None if best_slot is None else best_slot / 4


def peak_level(series: dict[datetime, float], hours: range) -> float | None:
    values = [v for m, v in series.items() if m.hour in hours]

    return max(values) if values else None


def rank_agreement(observed: dict[str, float], model: dict[str, float]) -> tuple[float, bool] | None:
    """
    Spearman rank correlation of the approaches' v/c, and whether both
    put the same approach first. None with fewer than 3 approaches in common.
    """

    common = sorted(set(observed) & set(model))

    if len(common) < 3:
        return None

    a = np.argsort(np.argsort([observed[k] for k in common]))
    b = np.argsort(np.argsort([model[k] for k in common]))
    rho = float(np.corrcoef(a, b)[0, 1]) if a.std() and b.std() else 0.0
    same_first = max(common, key=observed.get) == max(common, key=model.get)

    return rho, same_first


# ============================================================
# THE MAP AT THE INTERSECTION
# ============================================================

def speed_to_volume_to_capacity(speeds: np.ndarray) -> np.ndarray:
    """Back from speed (% of free flow) to v/c: speed = 1 / (1 + 0.15 (v/c)^4)."""

    ratio = np.clip(np.asarray(speeds, dtype=float), 1, 100) / 100

    return ((1 / ratio - 1) / 0.15) ** 0.25


def approach_segments(model, mappings_path=DEFAULT_MAPPINGS) -> dict[str, list[int]]:
    """Indexes of the segments arriving at the intersection, by approach."""

    way_ids = {
        r["segment_id"]: r["osm_way_id"]
        for r in json.loads(mappings_path.read_text(encoding="utf-8"))["mappings"]
    }
    ways = approach_ways()
    segments = model.network.segments
    at_site = {s.segment_id for s in site_segments(segments, site_centre())}
    by_approach: dict[str, list[int]] = defaultdict(list)

    for i, segment in enumerate(segments):
        approach_id = ways.get(way_ids[segment.segment_id])
        if approach_id is not None and segment.segment_id in at_site:
            by_approach[approach_id].append(i)

    return dict(by_approach)


class AllReleasedReplay(RcrcReplayClient):
    """
    The RCRC replay source run inside this process with no delay, so the
    whole report is released; the private database is read where it is
    and nothing is served or written.
    """

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from traffic_source.rcrc_replay.config import ReplayConfig
        from traffic_source.rcrc_replay.server import create_app

        super().__init__("in-process")
        self.app = TestClient(create_app(config=ReplayConfig(offset_weeks=0)))
        self.app.__enter__()

    def fetch_observations(self, start: datetime, end: datetime) -> RcrcBatch:
        response = self.app.get("/observations", params={"start": start.isoformat(), "end": end.isoformat()})
        response.raise_for_status()
        body = response.json()
        return RcrcBatch(site_id=str(body["site_id"]), records=body["observations"])

    def fetch_latest_available_timestamp(self) -> datetime | None:
        response = self.app.get("/health")
        response.raise_for_status()
        value = response.json()["latest_available_timestamp"]
        return datetime.fromisoformat(value) if value else None


# ============================================================
# COMMAND LINE
# ============================================================

def main() -> None:
    """Command line entry point: prints summary numbers only."""

    parser = argparse.ArgumentParser(description="Check the network map against Site 1444 (summary only).")
    parser.add_argument("--url", default=os.environ.get("JAADAH_RCRC_URL"),
                        help="a running RCRC source instead of the private replay database")
    parser.add_argument("--hourly-vc", type=Path, default=None,
                        help="rank roads on every day with this hourly v/c profile instead of the map's (for comparison)")
    args = parser.parse_args()

    client = RcrcReplayClient(args.url, timeout_s=300) if args.url else AllReleasedReplay()
    if args.hourly_vc is None:
        model = load_observed_model(client)
    else:
        site = load_site_inputs()
        start = CALIBRATION_START
        levels = observed_site_levels(client, site, start, start + timedelta(weeks=CALIBRATION_WEEKS))
        model = build_model(site, load_road_network(hourly_vc_path=args.hourly_vc, weekend_hourly_vc_path=args.hourly_vc), levels, NETWORK_SPREAD)
        print(f"Roads ranked with {args.hourly_vc.name}")
    site = model.site
    lengths = model.network.length_array
    arriving = approach_segments(model)
    all_arriving = sorted(i for idx in arriving.values() for i in idx)

    observed_level, observed_approach = {}, {}
    for first, last in VALIDATION_PERIODS:
        start = datetime(first.year, first.month, first.day, tzinfo=RIYADH)
        end = datetime(last.year, last.month, last.day, tzinfo=RIYADH) + timedelta(days=1)
        observations = ingest_rcrc_observations(
            client, start=start - timedelta(days=IMPUTATION_HISTORY_DAYS), end=end,
        ).observations
        window = [o for o in observations if o.interval_start >= start]
        history = [o for o in observations if o.interval_start < start] or window
        demand = build_simulation_demand(window, history=history, window_start=start,
                                         window_end=end, available_until=end)
        for moment, flows in hourly_flows(site, demand.demands).items():
            result = site_capacity(site, flows)
            if result.critical_volume_to_capacity is None:
                continue
            moment = moment.astimezone(RIYADH)
            observed_level[moment] = result.critical_volume_to_capacity
            observed_approach[moment] = approach_volume_to_capacity(site, result)

    factors = day_factors(model, observed_level)
    map_level, map_approach, tomtom = {}, {}, {}
    for moment, level in observed_level.items():
        speeds, _ = interval_speeds(model, moment, level, factors[moment])
        vc = speed_to_volume_to_capacity(speeds)
        weights = lengths[all_arriving]
        map_level[moment] = float((vc[all_arriving] * weights).sum() / weights.sum())
        map_approach[moment] = {
            a: float((vc[idx] * lengths[idx]).sum() / lengths[idx].sum()) for a, idx in arriving.items()
        }
        tomtom[moment] = tomtom_index(moment.date())[slot_of(moment)] - 1

    days = sorted({m.date() for m in observed_level})
    if not days:
        raise SystemExit("No counts in the validation weeks: the RCRC source has not released them.")
    print(f"Validation days: {len(days)} ({days[0]} to {days[-1]}, National Day week left out); "
          f"intervals with counts: {len(observed_level)}; approaches matched: {len(arriving)}")

    map_r = daily_shape_correlations(observed_level, map_level)
    tomtom_r = daily_shape_correlations(observed_level, tomtom)
    print("\n1. Pattern within the day (Pearson r per day, each series over its own daily mean; median [range])")
    for kind in ("workday", "Friday", "Saturday"):
        m = [r for d, r in map_r.items() if day_type(d) == kind]
        t = [r for d, r in tomtom_r.items() if day_type(d) == kind]
        if m:
            print(f"   {kind:9s} map {np.median(m):.2f} [{min(m):.2f} to {max(m):.2f}]   "
                  f"TomTom alone {np.median(t):.2f}   days {len(m)}")

    print("\n2. Peak times (mean absolute difference, hours) and evening above morning (share of days)")
    for kind in ("workday", "Friday", "Saturday"):
        am, pm, both_pm, counts_pm, map_pm = [], [], 0, 0, 0
        kind_days = [d for d in days if day_type(d) == kind]
        for d in kind_days:
            o = {m: v for m, v in observed_level.items() if m.date() == d}
            p = {m: v for m, v in map_level.items() if m.date() == d}
            for hours, out in ((MORNING_HOURS, am), (EVENING_HOURS, pm)):
                ho, hp = peak_hour(o, hours), peak_hour(p, hours)
                if ho is not None and hp is not None:
                    out.append(abs(ho - hp))
            om, oe, mm, me = (peak_level(o, MORNING_HOURS), peak_level(o, EVENING_HOURS),
                              peak_level(p, MORNING_HOURS), peak_level(p, EVENING_HOURS))
            if None not in (om, oe, mm, me):
                counts_pm += oe > om
                map_pm += me > mm
                both_pm += (oe > om) == (me > mm)
        if kind_days:
            print(f"   {kind:9s} morning peak off by {np.mean(am) if am else float('nan'):.1f} h, "
                  f"evening peak off by {np.mean(pm) if pm else float('nan'):.1f} h; evening busier: "
                  f"counts {counts_pm}/{len(kind_days)}, map {map_pm}/{len(kind_days)}, "
                  f"same answer {both_pm}/{len(kind_days)}")

    print("\n3. Which approach is fuller (peak hours: Spearman rho mean; same busiest approach, share)")
    for kind, label, hours in (("workday", "morning 06-10", MORNING_HOURS), ("workday", "evening 15-19", EVENING_HOURS),
                               ("Friday", "evening 19-23", range(19, 23)), ("Saturday", "evening 16-20", range(16, 20))):
        scores = [rank_agreement(observed_approach[m], map_approach[m])
                  for m in observed_level if m.hour in hours and day_type(m.date()) == kind]
        scores = [s for s in scores if s is not None]
        if scores:
            print(f"   {kind} {label}: rho {np.mean([s[0] for s in scores]):.2f}, "
                  f"same busiest {np.mean([s[1] for s in scores]):.0%} ({len(scores)} intervals)")

    print("\nThe city level is calibrated to TomTom, so it is not checked here; these numbers compare "
          "the map with counts it was not fitted to (weeks after the calibration weeks).")


if __name__ == "__main__":
    main()

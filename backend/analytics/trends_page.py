"""
The Traffic Patterns & Trends page's data, built from stored days
(docs/kpi_engine.md, section 17).

For one period (the last 7, 30 or 90 days up to the latest stored day)
and one day type (all, weekdays, weekends) it builds, as JSON-ready
dicts, the shape agreed in frontend/src/services/trendsService.js:

- summary: delay, level of service, throughput, the worst movement's
  queue, peak v/c with its interval, and the peak congestion window;
- trend: one value per day for delay, queue, throughput and v/c, with
  the level-of-service and capacity reference lines;
- weekdayWeekend: each KPI over the period's weekdays and weekends;
- heatmap: level of service and delay per weekday and hour;
- losDistribution: the share of 15-minute intervals at each grade, and
  the share whose grade is unavailable;
- breakdown: every KPI for approaches, movements and the intersection,
  for the whole day and for each hour.

The summary, trend, weekday/weekend pair and heatmap are given for the
intersection ("all") and for each approach, so the page's approach
filter needs no calculation.

Rules applied, and why (decisions of section 17):

- Coverage: a period (or one side of the weekday/weekend pair) is used
  only when at least HISTORY_MIN_DAY_SHARE of its days are stored and
  every weekday of its day type appears; otherwise the page says why.
  Missing days are unrelated to traffic, so a share of them only makes
  the result less certain; a missing weekday would change the mix.
- No comparison with a previous period: the trend shows the direction.
- Peak congestion window: the 15-minute slot of the day with the highest
  combined delay over the period's days (the usual time of day, not one
  bad day). Unavailable when any slot's delay is unavailable, because
  that slot could be the peak.
- Peak v/c: the highest single 15-minute value, with its interval.
- LOS distribution: intervals whose grade is unavailable are a share of
  their own, so the known grades are never scaled up; intervals with no
  vehicles have no grade and are not counted.
- Every value is a KpiResult combining days (run_combination "days"),
  belonging to the history scenario HISTORY_SCENARIO_ID.

Usage (from the repository root, after run_history.py has stored days):
    python -m backend.analytics.trends_page [--history-dir data/history] [--out <folder>]

It writes one file per period and day type, trends_<days>d_<day type>.json
(9 files, e.g. trends_30d_weekdays.json), to
frontend/public/data/<intersection>/history/ unless --out names another
folder. A period without enough days still gets its file, holding
available false and the reason, so the page can say why.

The files are compact (compact_trends), so their size does not grow
with the number of days: the fields every result shares (scenario_id,
run_combination, and run_ids, the runs of every day the period used)
are written once, as resultDefaults; in each result a field is left out
when it is null or equal to its default. A result is unpacked by
starting from resultDefaults and laying its own fields on top
(expand_result); a field still missing is null. Results with other runs
(one day's trend point, a heatmap cell's weekdays, HCM results without
runs) keep their own run_ids.
"""

import argparse
import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.analytics.kpi.comparison import input_origins
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.parameters import (
    HISTORY_MIN_DAY_SHARE,
    LOS_THRESHOLDS,
    VOLUME_TO_CAPACITY_LOS_F,
)
from backend.analytics.history import HISTORY_DIR, load_day, stored_days
from backend.analytics.service import FRONTEND_DATA_DIR
from backend.analytics.trends import (
    ALL_SLOTS,
    DELAY,
    LOS,
    QUEUE,
    QUEUE_DURATION,
    SLOTS_PER_DAY,
    STORAGE,
    THROUGHPUT,
    VC,
    DayParts,
    PeriodValue,
    hour_slots,
    period_values,
    prepare_day,
)
from jaadah.models.kpis import (
    KpiLevel,
    KpiMethod,
    KpiResult,
    KpiStatus,
    KpiUnit,
    LevelOfServiceGrade,
    RunCombination,
)
from jaadah.models.network import MovementControl, MovementType


PERIOD_LENGTHS = (7, 30, 90)
DAY_TYPES = ("all", "weekdays", "weekends")
HISTORY_SCENARIO_ID = "SCN_HISTORY_BASELINE"

WEEKEND = {4, 5}            # date.weekday(): Friday and Saturday
WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
ALL_ELEMENTS = "all"
WHOLE_DAY = "whole-day"

DELAY_ONLY = frozenset({"delay"})
GRADES = [g.value for g in LevelOfServiceGrade]

S_VEH, SECONDS, VEH_H, METRES, RATIO, GRADE = (
    KpiUnit.SECONDS_PER_VEHICLE, KpiUnit.SECONDS, KpiUnit.VEHICLES_PER_HOUR,
    KpiUnit.METRES, KpiUnit.RATIO, KpiUnit.GRADE,
)
TREND_METRICS = [(DELAY, S_VEH), (QUEUE, METRES), (THROUGHPUT, VEH_H), (VC, RATIO)]
BREAKDOWN_KPIS = [
    (DELAY, S_VEH), (LOS, GRADE), (VC, RATIO), (QUEUE, METRES),
    (STORAGE, RATIO), (QUEUE_DURATION, SECONDS), (THROUGHPUT, VEH_H),
]

NOT_STORED_REASON = "no simulation is stored for this day"
OTHER_DAY_TYPE_REASON = "not part of the selected day type"


# ============================================================
# DAYS AND COVERAGE
# ============================================================

def is_weekend(day: date) -> bool:
    return day.weekday() in WEEKEND


def matches_day_type(day: date, day_type: str) -> bool:
    if day_type not in DAY_TYPES:
        raise ValueError(f"day type must be one of {', '.join(DAY_TYPES)}, got {day_type!r}")
    if day_type == "weekdays":
        return not is_weekend(day)
    if day_type == "weekends":
        return is_weekend(day)
    return True


def page_weekday(day: date) -> int:
    """The page's weekday number: 0 = Sunday ... 6 = Saturday."""

    return (day.weekday() + 1) % 7


def expected_days(last_day: date, length: int, day_type: str) -> list[date]:
    """The days of the period ending on last_day that match the day type, oldest first."""

    first = last_day - timedelta(days=length - 1)
    days = [first + timedelta(days=n) for n in range(length)]
    return [d for d in days if matches_day_type(d, day_type)]


def check_coverage(expected: list[date], stored: set[date]) -> tuple[list[date], str | None]:
    """
    The expected days that are stored, and the reason they are not
    enough (None when they are): at least HISTORY_MIN_DAY_SHARE of the
    expected days, and every weekday among them at least once.
    """

    used = [d for d in expected if d in stored]
    needed = math.ceil(HISTORY_MIN_DAY_SHARE * len(expected) - 1e-9)

    if len(used) < needed:
        return used, (
            f"not enough data: {len(used)} of {len(expected)} days are stored "
            f"(at least {needed} are needed)"
        )

    missing = sorted({page_weekday(d) for d in expected} - {page_weekday(d) for d in used})
    if missing:
        names = ", ".join(WEEKDAY_NAMES[w] for w in missing)
        return used, f"not enough data: no {names} is stored in the period"

    return used, None


# ============================================================
# RESULTS
# ============================================================

class _Results:
    """Turns PeriodValues into KpiResults for one set of days."""

    def __init__(self, days: list[DayParts]):
        self.days = days
        self.model = days[0].calculation
        self.run_ids = sorted(d.calculation.run.run_id for d in days)
        self.origins: dict = {}

    def approach_of(self, level: KpiLevel, element_id: str) -> str | None:
        if level == KpiLevel.MOVEMENT:
            return self.model.movements[element_id].approach_id
        if level == KpiLevel.LANE:
            return next(l.approach_id for l in self.model.lanes if l.lane_id == element_id)
        if level == KpiLevel.APPROACH:
            return element_id
        return None

    def input_origins(self, method: KpiMethod, approach_id: str | None) -> list:
        key = (method, approach_id)
        if key not in self.origins:
            found = set()
            for d in self.days:
                c = d.calculation
                whole_day = AnalysisInterval(c.intervals[0].start, c.intervals[-1].end)
                found |= set(input_origins(method, c.demands, c.program, c.movements, whole_day, approach_id))
            self.origins[key] = sorted(found, key=lambda o: o.value)
        return self.origins[key]

    def result(self, kpi, unit, level, element_id, value: PeriodValue, interval: AnalysisInterval) -> KpiResult:
        method = KpiMethod.HCM if kpi == VC else KpiMethod.SIMULATION
        ok = value.status == KpiStatus.OK
        if kpi == VC and ok and value.peak_interval is not None:
            interval = value.peak_interval

        return KpiResult(
            kpi=kpi, level=level, **{f"{level.value}_id": element_id},
            measured_on_lane_id=value.measured_on_lane_id if ok else None,
            uncontrolled_movements=value.uncontrolled_movements if ok else None,
            interval_start=interval.start, interval_end=interval.end,
            value=value.value if ok and kpi != LOS else None,
            los_grade=value.los_grade if ok else None,
            unit=unit, status=value.status, reason=None if ok else value.reason,
            method=method,
            input_origins=self.input_origins(method, self.approach_of(level, element_id)) if ok else [],
            scenario_id=HISTORY_SCENARIO_ID,
            run_ids=self.run_ids if method == KpiMethod.SIMULATION else [],
            run_combination=RunCombination.DAYS,
        )

    def missing(self, kpi, unit, level, element_id, interval, reason) -> KpiResult:
        return self.result(kpi, unit, level, element_id, PeriodValue(KpiStatus.UNAVAILABLE, reason=reason), interval)


def _dump(result: KpiResult) -> dict:
    return result.model_dump(mode="json")


def _whole_days(days: list[date]) -> AnalysisInterval:
    first, last = min(days), max(days)
    return AnalysisInterval(_midnight(first), _midnight(last + timedelta(days=1)))


def _midnight(day: date) -> datetime:
    return datetime.fromisoformat(f"{day.isoformat()}T00:00:00+03:00")


def _slot_interval(day: date, slot: int) -> AnalysisInterval:
    start = _midnight(day) + timedelta(minutes=15 * slot)
    return AnalysisInterval(start, start + timedelta(minutes=15))


# ============================================================
# THE PAGE
# ============================================================

def build_trends(stored: dict[date, DayParts], length: int, day_type: str) -> dict:
    """
    The page's data for the last `length` days up to the latest stored
    day and one day type. stored maps each stored day to its DayParts.
    When the period has too few days, the result has available False
    and the reason; the page shows it instead of any value.
    """

    if length not in PERIOD_LENGTHS:
        raise ValueError(f"period must be one of {PERIOD_LENGTHS} days, got {length}")
    if not stored:
        raise ValueError("no day is stored")

    last_day = max(stored)
    expected = expected_days(last_day, length, day_type)
    used, reason = check_coverage(expected, set(stored))
    period = {
        "start": (last_day - timedelta(days=length - 1)).isoformat(),
        "end": last_day.isoformat(),
        "dayType": day_type,
        "daysExpected": len(expected),
        "daysUsed": len(used),
        "missingDays": [d.isoformat() for d in expected if d not in stored],
        "intervalCount": len(used) * SLOTS_PER_DAY,
        "runsPerInterval": 1,
    }

    if reason:
        return {"available": False, "reason": reason, "period": period}

    days = [stored[d] for d in used]
    model = days[0].calculation
    results = _Results(days)
    interval = _whole_days(used)
    values = period_values(days)
    approaches = [_approach(a, model) for a in model.approach_ids]

    elements = [(ALL_ELEMENTS, KpiLevel.INTERSECTION, model.intersection_id)] + [
        (a["approach_id"], KpiLevel.APPROACH, a["approach_id"]) for a in approaches
    ]
    slot_delays = [period_values(days, frozenset({s}), DELAY_ONLY) for s in range(SLOTS_PER_DAY)]
    daily = {d: period_values([stored[d]]) for d in used}

    views = {
        name: {
            "summary": _summary(level, element_id, values, slot_delays, results, interval, model, approaches),
            "trend": _trend(level, element_id, expected, daily, stored, results),
            "weekdayWeekend": _weekday_weekend(level, element_id, last_day, length, stored),
            "heatmap": _heatmap(level, element_id, days, day_type, results),
        }
        for name, level, element_id in elements
    }

    return {
        "available": True,
        "reason": None,
        "period": period,
        "approaches": approaches,
        "views": views,
        "losDistribution": _los_distribution(elements, days, model, approaches),
        "breakdownWindows": [{"id": WHOLE_DAY, "label": "Whole day", "default": True}] + [
            {"id": f"hour-{h:02d}", "label": f"{h:02d}:00–{(h + 1) % 24:02d}:00", "default": False}
            for h in range(24)
        ],
        "breakdown": {
            window_id: _breakdown(window_id, label, slots, days, results, interval, model, approaches)
            for window_id, label, slots in _windows()
        },
    }


def _approach(approach_id: str, model) -> dict:
    side = approach_id.removeprefix("APP_")
    names = {"E": "East", "W": "West", "N": "North", "S": "South"}
    return {"approach_id": approach_id, "label": names.get(side, approach_id)}


def _movement_label(movement_id: str, model) -> str:
    attributes = model.attributes[movement_id]
    if attributes.movement_type == MovementType.RIGHT:
        return "Right (slip lane)" if attributes.control == MovementControl.UNCONTROLLED else "Right"
    return "Left" if attributes.movement_type == MovementType.LEFT else "Through"


def _movements_of(approach_id: str, model) -> list[str]:
    return [m for m in model.movement_ids if model.movements[m].approach_id == approach_id]


# ---------------- summary

def _summary(level, element_id, values, slot_delays, results, interval, model, approaches):
    def get(kpi, unit):
        return _dump(results.result(kpi, unit, level, element_id, values[(kpi, unit, level, element_id)], interval))

    movements = (
        model.movement_ids if level == KpiLevel.INTERSECTION else _movements_of(element_id, model)
    )
    return {
        "control_delay": {"current": get(DELAY, S_VEH)},
        "level_of_service": {"current": get(LOS, GRADE)},
        "throughput": {"current": get(THROUGHPUT, VEH_H)},
        "volume_to_capacity_ratio": {"current": get(VC, RATIO)},
        "queue_length": _worst_queue(movements, values, results, interval, level, element_id, model, approaches),
        "peakWindow": _peak_window(level, element_id, slot_delays, interval),
    }


def _worst_queue(movements, values, results, interval, level, element_id, model, approaches):
    """The movement with the longest 95th-percentile queue; unknown when any movement's queue is unavailable."""

    queues = {m: values[(QUEUE, METRES, KpiLevel.MOVEMENT, m)] for m in movements}
    unavailable = [m for m, q in queues.items() if q.status == KpiStatus.UNAVAILABLE]

    if unavailable:
        reason = f"the queue of {', '.join(unavailable)} is unavailable, so the longest is unknown"
        return {
            "current": _dump(results.missing(QUEUE, METRES, level, element_id, interval, reason)),
            "worst": None,
        }

    usable = {m: q for m, q in queues.items() if q.status == KpiStatus.OK}
    worst = max(usable, key=lambda m: usable[m].value)        # the first one when equal
    labels = {a["approach_id"]: a["label"] for a in approaches}
    return {
        "current": _dump(results.result(QUEUE, METRES, KpiLevel.MOVEMENT, worst, usable[worst], interval)),
        "worst": {
            "movement_id": worst,
            "label": f"{labels[model.movements[worst].approach_id]} {_movement_label(worst, model).lower()}",
            "storageRatio": _dump(results.result(
                STORAGE, RATIO, KpiLevel.MOVEMENT, worst,
                values[(STORAGE, RATIO, KpiLevel.MOVEMENT, worst)], interval,
            )),
        },
    }


def _peak_window(level, element_id, slot_delays, interval):
    delays = [v[(DELAY, S_VEH, level, element_id)] for v in slot_delays]
    unavailable = [s for s, d in enumerate(delays) if d.status == KpiStatus.UNAVAILABLE]

    if unavailable:
        first = _slot_interval(interval.start.date(), unavailable[0]).start
        return {
            "status": "unavailable",
            "reason": f"the delay at {first:%H:%M} is unavailable, so the peak is unknown",
            "interval_start": None, "interval_end": None,
        }

    usable = [(s, d.value) for s, d in enumerate(delays) if d.status == KpiStatus.OK]
    if not usable:
        return {"status": "not_applicable", "reason": "no vehicles in the period",
                "interval_start": None, "interval_end": None}

    slot = max(usable, key=lambda x: x[1])[0]                 # the earliest slot when equal
    window = _slot_interval(interval.start.date(), slot)
    return {"status": "ok", "reason": None,
            "interval_start": window.start.isoformat(), "interval_end": window.end.isoformat()}


# ---------------- trend

def _trend(level, element_id, expected, daily, stored, results):
    series = {kpi.value: [] for kpi, _ in TREND_METRICS}

    for day in expected:
        day_interval = _whole_days([day])
        for kpi, unit in TREND_METRICS:
            if day in daily:
                day_results = _Results([stored[day]])
                result = day_results.result(kpi, unit, level, element_id, daily[day][(kpi, unit, level, element_id)], day_interval)
            else:
                result = results.missing(kpi, unit, level, element_id, day_interval, NOT_STORED_REASON)
            series[kpi.value].append({"date": day.isoformat(), "result": _dump(result)})

    lower = {g.value: limit for limit, g in LOS_THRESHOLDS}
    names = [g.value for _, g in LOS_THRESHOLDS] + ["F"]
    return {
        "metrics": list(series),
        "series": series,
        "referenceLines": {
            DELAY.value: [
                {"value": limit, "label": f"LOS {names[i]}/{names[i + 1]}"}
                for i, (limit, _) in enumerate(LOS_THRESHOLDS)
            ],
            VC.value: [{"value": VOLUME_TO_CAPACITY_LOS_F, "label": "Capacity"}],
        },
        "anomalies": [],
    }


# ---------------- weekdays and weekends

def _weekday_weekend(level, element_id, last_day, length, stored):
    out = {kpi.value: {} for kpi, _ in TREND_METRICS}

    for side in ("weekdays", "weekends"):
        expected = expected_days(last_day, length, side)
        used, reason = check_coverage(expected, set(stored))
        interval = _whole_days(expected)
        if reason:
            for kpi, unit in TREND_METRICS:
                out[kpi.value][side] = _dump(_Results([stored[max(stored)]]).missing(
                    kpi, unit, level, element_id, interval, reason))
            continue

        days = [stored[d] for d in used]
        results = _Results(days)
        values = period_values(days)
        for kpi, unit in TREND_METRICS:
            out[kpi.value][side] = _dump(results.result(
                kpi, unit, level, element_id, values[(kpi, unit, level, element_id)], _whole_days(used)))

    return out


# ---------------- heatmap

def _heatmap(level, element_id, days, day_type, results):
    cells = []
    by_weekday = {}
    for d in days:
        by_weekday.setdefault(page_weekday(d.day), []).append(d)

    for weekday in range(7):
        group = by_weekday.get(weekday, [])
        in_type = any(matches_day_type(day, day_type) for day in _weekday_dates(weekday))
        for hour in range(24):
            if not in_type or not group:
                anchor = days[0].day
                interval = _slot_interval(anchor, hour * 4)
                reason = OTHER_DAY_TYPE_REASON if not in_type else NOT_STORED_REASON
                cells.append({
                    "day": weekday, "hour": hour,
                    "result": _dump(results.missing(LOS, GRADE, level, element_id, interval, reason)),
                    "delay": _dump(results.missing(DELAY, S_VEH, level, element_id, interval, reason)),
                })
                continue

            values = period_values(group, hour_slots(hour), DELAY_ONLY)
            first = _slot_interval(group[0].day, hour * 4).start
            interval = AnalysisInterval(first, _slot_interval(group[-1].day, hour * 4 + 3).end)
            group_results = _Results(group)
            cells.append({
                "day": weekday, "hour": hour,
                "result": _dump(group_results.result(LOS, GRADE, level, element_id, values[(LOS, GRADE, level, element_id)], interval)),
                "delay": _dump(group_results.result(DELAY, S_VEH, level, element_id, values[(DELAY, S_VEH, level, element_id)], interval)),
            })

    return cells


def _weekday_dates(weekday: int) -> list[date]:
    """One date with the page weekday (any week will do: day types depend only on the weekday)."""

    sunday = date(2026, 11, 1)          # a Sunday
    return [sunday + timedelta(days=weekday)]


# ---------------- LOS distribution

def _los_distribution(elements, days, model, approaches):
    labels = {a["approach_id"]: a["label"] for a in approaches}
    rows = []

    for name, level, element_id in elements:
        counts = {g: 0 for g in GRADES}
        counts["unavailable"] = 0
        for d in days:
            for interval in d.calculation.intervals:
                result = d.measured_los[(level, element_id, interval)]
                if result.status == KpiStatus.OK:
                    counts[result.los_grade.value] += 1
                elif result.status == KpiStatus.UNAVAILABLE:
                    counts["unavailable"] += 1

        total = sum(counts.values())
        shares = {g: (round(n / total, 3) if total else None) for g, n in counts.items()}
        rows.append({
            "element": {"level": level.value, "id": element_id,
                        "label": "Intersection" if level == KpiLevel.INTERSECTION else labels[element_id]},
            "intervals": total,
            "shares": shares,
        })

    return rows


# ---------------- breakdown

def _windows():
    yield WHOLE_DAY, "Whole day", ALL_SLOTS
    for h in range(24):
        yield f"hour-{h:02d}", f"{h:02d}:00–{(h + 1) % 24:02d}:00", hour_slots(h)


def _breakdown(window_id, label, slots, days, results, interval, model, approaches):
    values = period_values(days, slots)

    def results_of(level, element_id):
        return {
            kpi.value: _dump(results.result(kpi, unit, level, element_id, values[(kpi, unit, level, element_id)], interval))
            for kpi, unit in BREAKDOWN_KPIS
            if (kpi, unit, level, element_id) in values
        }

    return {
        "window": {"id": window_id, "label": label},
        "approaches": [
            {
                "approach_id": a["approach_id"],
                "label": a["label"],
                "results": results_of(KpiLevel.APPROACH, a["approach_id"]),
                "movements": [
                    {"movement_id": m, "label": _movement_label(m, model),
                     "results": results_of(KpiLevel.MOVEMENT, m)}
                    for m in _movements_of(a["approach_id"], model)
                ],
            }
            for a in approaches
        ],
        "intersection": {"results": results_of(KpiLevel.INTERSECTION, model.intersection_id)},
    }


# ============================================================
# WRITING
# ============================================================

def trends_file_name(length: int, day_type: str) -> str:
    """e.g. trends_30d_weekdays.json"""

    return f"trends_{length}d_{day_type}.json"


def is_result(item) -> bool:
    """True for a dumped KpiResult inside the page's data."""

    return isinstance(item, dict) and {"kpi", "status", "interval_start"} <= item.keys()


def compact_trends(payload: dict) -> dict:
    """
    The compact form of build_trends' output (see the module notes):
    resultDefaults once at the top; in each result, null fields and
    fields equal to their default left out.
    """

    if not payload.get("available"):
        return payload

    days = payload["period"]
    defaults = {
        "scenario_id": HISTORY_SCENARIO_ID,
        "run_combination": RunCombination.DAYS.value,
        "run_ids": _period_run_ids(payload),
    }

    def pack(item):
        if is_result(item):
            return {
                k: v for k, v in item.items()
                if v is not None and not (k in defaults and v == defaults[k])
            }
        if isinstance(item, dict):
            return {k: pack(v) for k, v in item.items()}
        if isinstance(item, list):
            return [pack(v) for v in item]
        return item

    packed = pack(payload)
    packed["resultDefaults"] = defaults
    packed["period"] = days
    return packed


def expand_result(packed: dict, defaults: dict) -> dict:
    """A compact result back in full: defaults, then its own fields; anything missing is null."""

    full = {**defaults, **packed}
    return KpiResult.model_validate(
        {k: v for k, v in full.items() if k not in _COMPUTED_FIELDS}
    ).model_dump(mode="json")


_COMPUTED_FIELDS = {"value_computation", "replication_count", "is_shared_value"}


def _period_run_ids(payload: dict) -> list[str]:
    """The run_ids of the summary's delay: every day the period used."""

    return payload["views"][ALL_ELEMENTS]["summary"]["control_delay"]["current"]["run_ids"]


def write_trends(stored: dict[date, DayParts], folder: str | Path) -> list[Path]:
    """
    Write the page's data for every period and day type (9 files) into
    folder, as compact JSON, and return the files.
    """

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []

    for length in PERIOD_LENGTHS:
        for day_type in DAY_TYPES:
            path = folder / trends_file_name(length, day_type)
            payload = compact_trends(build_trends(stored, length, day_type))
            path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            paths.append(path)

    return paths


def load_stored_days(history_dir: str | Path = HISTORY_DIR) -> dict[date, DayParts]:
    """Every stored day, run through the engine once (a few seconds a day)."""

    return {day: prepare_day(day, load_day(day, history_dir)) for day in stored_days(history_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the Trends page data from the stored days.")
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--out", type=Path, help="folder; default: frontend/public/data/<intersection>/history/")
    args = parser.parse_args()

    started = time.monotonic()
    stored = load_stored_days(args.history_dir)
    if not stored:
        raise SystemExit(f"No day is stored in {args.history_dir}; run simulation/scripts/run_history.py first.")
    print(f"{len(stored)} stored days ({min(stored)} to {max(stored)}) loaded "
          f"in {time.monotonic() - started:.0f} s")

    intersection_id = next(iter(stored.values())).calculation.intersection_id
    out = args.out or FRONTEND_DATA_DIR / intersection_id / "history"
    for path in write_trends(stored, out):
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = "ok" if payload["available"] else payload["reason"]
        print(f"Written: {path} ({path.stat().st_size / 1e6:.1f} MB, {state})")
    print(f"Done in {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()

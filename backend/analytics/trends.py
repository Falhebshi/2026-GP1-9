"""
The historical analysis: KPI values over many stored days
(docs/kpi_engine.md, section 17).

Each stored day is turned into its per-interval parts by the same engine
calls that make a run's published results (RunCalculation.parts). This
module combines the parts of any selection of days and times of day (a
whole month, the 17:00 hour of every weekday, one heatmap cell) into one
value per KPI and element.

Rules applied, and why (decisions of section 17):

- Control delay and queue duration: the mean over every vehicle that
  arrived in the selection, i.e. the interval means weighted by their
  vehicles; approach and intersection values are the engine's roll-up
  of the movement values. A plain mean of interval values would let a
  quiet interval count as much as a busy one.
- Level of service: graded from the combined delay, never averaged as
  letters.
- Throughput: the mean hourly flow of the selected intervals (all are
  15 minutes long), summed over movements for approaches and the
  intersection.
- Queue length and storage ratio: the 95th-percentile cycle queue of
  all the selected cycles pooled, with the engine's rule: unavailable
  only when the cycle at the percentile's rank was cut off, because the
  cut-off cycles are the longest and cannot change a lower rank.
- Volume-to-capacity ratio: the highest single 15-minute value, with
  its interval; v/c is never averaged.
- Unavailable is strict for delay, level of service, queue duration and
  throughput: one unavailable interval makes the selection unavailable,
  with that interval's reason. A missing interval's delay could be
  anything, so a value without it could be wrong, most likely too good.
- Not applicable (no vehicles) intervals are left out: an empty
  interval is not missing data.

Which days a selection may use (coverage), and how values become
KpiResults for the page, are decided by the callers.
"""

from datetime import date, datetime, timedelta
from typing import NamedTuple

from backend.analytics.kpi.delay import MovementDelay, blocks_over_period, merge_blocks
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.parameters import ANALYSIS_INTERVAL_S, level_of_service
from backend.analytics.kpi.queue import (
    cycles_by_interval,
    pooled_percentile_queues,
    zone_end_approaches,
)
from backend.analytics.kpi.rollup import (
    Part,
    combine_weighted_mean,
    measured_delay_rollup,
    queue_rollup,
    storage_ratio_rollup,
    throughput_rollup,
)
from backend.analytics.service import (
    DEFAULT_MAPPING_PATH,
    DEFAULT_NETWORK_PATH,
    IntervalParts,
    RunCalculation,
    RunMeasurements,
    prepare_calculation,
)
from jaadah.models.kpis import (
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiStatus,
    KpiUnit,
    LevelOfServiceGrade,
    UncontrolledMovements,
)


SLOTS_PER_DAY = 24 * 3600 // ANALYSIS_INTERVAL_S          # 96
ALL_SLOTS = frozenset(range(SLOTS_PER_DAY))

DELAY = KpiName.CONTROL_DELAY
LOS = KpiName.LEVEL_OF_SERVICE
QUEUE_DURATION = KpiName.QUEUE_DURATION
THROUGHPUT = KpiName.THROUGHPUT
QUEUE = KpiName.QUEUE_LENGTH
STORAGE = KpiName.QUEUE_STORAGE_RATIO
VC = KpiName.VOLUME_TO_CAPACITY_RATIO

ELEMENT_LEVELS = (KpiLevel.LANE, KpiLevel.MOVEMENT, KpiLevel.APPROACH, KpiLevel.INTERSECTION)
ALL_MEASURES = frozenset({"delay", "throughput", "queue", "volume_to_capacity"})


class DayParts(NamedTuple):
    """
    One stored day, ready to combine: its engine calculation, its
    per-interval parts, its cycle records grouped by interval, and its
    HCM volume-to-capacity and measured level-of-service results per
    (level, element_id, interval).
    """

    day: date
    calculation: RunCalculation
    parts: IntervalParts
    lane_cycles: dict
    approach_cycles: dict
    volume_to_capacity: dict
    measured_los: dict


class PeriodValue(NamedTuple):
    """
    One KPI of one element over a selection.

    value is None unless status is OK; reason then says why.
    los_grade is set for level of service, peak_interval for the
    volume-to-capacity ratio (the 15 minutes the highest value was in),
    measured_on_lane_id / is_shared for queues and storage ratios.
    """

    status: KpiStatus
    value: float | None = None
    reason: str | None = None
    los_grade: LevelOfServiceGrade | None = None
    peak_interval: AnalysisInterval | None = None
    measured_on_lane_id: str | None = None
    is_shared: bool = False
    uncontrolled_movements: UncontrolledMovements | None = None


# Keys of period_values: (kpi, unit, level, element_id)
Key = tuple[KpiName, KpiUnit, KpiLevel, str]


def prepare_day(
    day: date,
    measurements: RunMeasurements,
    mapping_path=DEFAULT_MAPPING_PATH,
    network_path=DEFAULT_NETWORK_PATH,
) -> DayParts:
    """Run the engine once on one stored day (a few seconds)."""

    calculation = prepare_calculation(measurements, mapping_path, network_path)
    run_id = measurements.run.run_id
    intervals = calculation.intervals
    signal_approaches = sorted({q.approach_id for q in calculation.queues.approaches})

    results = calculation.results()

    def by_element(kpi, method):
        return {
            (r.level, getattr(r, f"{r.level.value}_id"), AnalysisInterval(r.interval_start, r.interval_end)): r
            for r in results
            if r.kpi == kpi and r.method == method
            and r.level in (KpiLevel.MOVEMENT, KpiLevel.APPROACH, KpiLevel.INTERSECTION)
            and r.interval_end - r.interval_start == timedelta(seconds=ANALYSIS_INTERVAL_S)
        }

    return DayParts(
        day=day,
        calculation=calculation,
        parts=calculation.parts(),
        lane_cycles=cycles_by_interval(
            run_id, [lane.lane_id for lane in calculation.lanes], intervals,
            calculation.queues.lanes, "lane_id",
        ),
        approach_cycles=cycles_by_interval(
            run_id, signal_approaches, intervals, calculation.queues.approaches, "approach_id",
        ),
        volume_to_capacity=by_element(VC, KpiMethod.HCM),
        measured_los=by_element(LOS, KpiMethod.SIMULATION),
    )


def slot_of(moment: datetime) -> int:
    """The 15-minute slot of the day a moment falls in: 00:00 is 0, 07:30 is 30, 23:45 is 95."""

    return (moment.hour * 3600 + moment.minute * 60 + moment.second) // ANALYSIS_INTERVAL_S


def hour_slots(hour: int) -> frozenset[int]:
    """The four 15-minute slots of one hour, e.g. 17 -> {68, 69, 70, 71}."""

    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0 to 23, got {hour}")

    per_hour = 3600 // ANALYSIS_INTERVAL_S
    return frozenset(range(hour * per_hour, (hour + 1) * per_hour))


def period_values(
    days: list[DayParts],
    slots: frozenset[int] = ALL_SLOTS,
    measures: frozenset[str] = ALL_MEASURES,
) -> dict[Key, PeriodValue]:
    """
    Combine the selected 15-minute slots of the given days into one value
    per KPI and element (see the module rules). measures limits the work
    to some of "delay" (with level of service and queue duration),
    "throughput", "queue" (with storage ratio) and "volume_to_capacity".
    Raises ValueError when no day or no slot is given.
    """

    if not days:
        raise ValueError("at least one day is needed")
    if not slots:
        raise ValueError("at least one slot is needed")

    days = sorted(days, key=lambda d: d.day)
    selected = {
        d.day: [i for i in d.calculation.intervals if slot_of(i.start) in slots]
        for d in days
    }
    every_interval = [i for d in days for i in selected[d.day]]
    period = AnalysisInterval(every_interval[0].start, every_interval[-1].end)
    model = days[0].calculation

    out: dict[Key, PeriodValue] = {}
    if "delay" in measures:
        _delays(out, days, selected, period, model)
    if "throughput" in measures:
        _throughput(out, days, selected, period, model)
    if "queue" in measures:
        _queues(out, days, selected, every_interval, period, model)
    if "volume_to_capacity" in measures:
        _volume_to_capacity(out, days, selected)
    return out


# ============================================================
# DELAY, LEVEL OF SERVICE, QUEUE DURATION
# ============================================================

def _delays(out, days, selected, period, model):
    combined = {}

    for m in model.movement_ids:
        delays = [d.parts.delays[(m, i)] for d in days for i in selected[d.day]]
        control = combine_weighted_mean(
            [Part(x.status, x.mean_control_delay_s, x.completed_vehicles, reason=x.reason) for x in delays]
        )
        stopped = combine_weighted_mean(
            [Part(x.status, x.mean_queue_duration_s, x.completed_vehicles, reason=x.reason) for x in delays]
        )
        vehicles = sum(x.completed_vehicles for x in delays if x.status == KpiStatus.OK)
        combined[(m, period)] = MovementDelay(
            control.status, vehicles, 0, control.value, stopped.value, control.reason,
        )
        _put_delay(out, KpiLevel.MOVEMENT, m, control, stopped, None)

    for quantity, kpi in (("control_delay", DELAY), ("queue_duration", QUEUE_DURATION)):
        rolled = measured_delay_rollup(model.movements, model.attributes, combined, period, quantity)
        for (level, element_id), r in rolled.items():
            unit = KpiUnit.SECONDS_PER_VEHICLE if kpi == DELAY else KpiUnit.SECONDS
            out[(kpi, unit, KpiLevel(level), element_id)] = PeriodValue(
                r.status, r.value, r.reason, uncontrolled_movements=r.uncontrolled_movements,
            )
            if kpi == DELAY:
                out[(LOS, KpiUnit.GRADE, KpiLevel(level), element_id)] = _graded(r)


def _put_delay(out, level, element_id, control, stopped, uncontrolled):
    out[(DELAY, KpiUnit.SECONDS_PER_VEHICLE, level, element_id)] = PeriodValue(
        control.status, control.value, control.reason, uncontrolled_movements=uncontrolled,
    )
    out[(QUEUE_DURATION, KpiUnit.SECONDS, level, element_id)] = PeriodValue(
        stopped.status, stopped.value, stopped.reason, uncontrolled_movements=uncontrolled,
    )
    out[(LOS, KpiUnit.GRADE, level, element_id)] = _graded(control)


def _graded(delay) -> PeriodValue:
    """Level of service from a combined delay (from delay alone, like the measured LOS)."""

    if delay.status != KpiStatus.OK:
        return PeriodValue(delay.status, reason=delay.reason,
                           uncontrolled_movements=getattr(delay, "uncontrolled_movements", None))

    return PeriodValue(KpiStatus.OK, los_grade=level_of_service(delay.value),
                       uncontrolled_movements=getattr(delay, "uncontrolled_movements", None))


# ============================================================
# THROUGHPUT
# ============================================================

def _throughput(out, days, selected, period, model):
    flows, blocked = {}, {}

    for m in model.movement_ids:
        r = combine_weighted_mean([
            Part(t.status, t.value_veh_h, 1.0, reason=t.reason)
            for d in days for i in selected[d.day]
            for t in (d.parts.throughput[(m, i)],)
        ])
        out[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, KpiLevel.MOVEMENT, m)] = PeriodValue(r.status, r.value, r.reason)
        flows[(m, period)] = r.value or 0.0
        if r.status == KpiStatus.UNAVAILABLE:
            blocked[(m, period)] = r.reason

    for (level, element_id), r in throughput_rollup(
        model.movements, model.attributes, flows, period, blocked=blocked,
    ).items():
        out[(THROUGHPUT, KpiUnit.VEHICLES_PER_HOUR, KpiLevel(level), element_id)] = PeriodValue(
            r.status, r.value, r.reason, uncontrolled_movements=r.uncontrolled_movements,
        )


# ============================================================
# QUEUE LENGTH AND STORAGE RATIO
# ============================================================

def _queues(out, days, selected, every_interval, period, model):
    lane_ids = [lane.lane_id for lane in model.lanes]
    signal_approaches = sorted({key for d in days for (key, _) in d.approach_cycles})

    def pooled(attribute, keys, flag):
        cycles = {
            (key, i): getattr(d, attribute)[(key, i)]
            for d in days for i in selected[d.day] for key in keys
        }
        return {
            (key, period): queue
            for key, queue in pooled_percentile_queues(keys, every_interval, cycles, flag).items()
        }

    lane_queues = pooled("lane_cycles", lane_ids, "reaches_section_end")
    approach_queues = pooled("approach_cycles", signal_approaches, "reaches_zone_end")
    all_approaches = {(a, period): approach_queues.get((a, period)) for a in model.approach_ids}

    uninserted = {
        key: reason
        for d in days for key, reason in d.parts.uninserted.items()
        if key[1] in selected[d.day]
    }
    blocked = merge_blocks(
        blocks_over_period(uninserted, every_interval),
        zone_end_approaches(approach_queues),
    )

    for unit, name in ((KpiUnit.METRES, "m"), (KpiUnit.VEHICLES, "veh")):
        rolled = queue_rollup(
            model.lanes, model.movements, lane_queues, period,
            approach_queues=all_approaches, slip_lane_ids=model.slip_lane_ids,
            blocked=blocked, unit=name,
        )
        _put_queues(out, QUEUE, unit, rolled, model)

    rolled = storage_ratio_rollup(model.lanes, model.movements, lane_queues, period, blocked=blocked)
    _put_queues(out, STORAGE, KpiUnit.RATIO, rolled, model)


def _put_queues(out, kpi, unit, rolled, model):
    for (level, element_id), r in rolled.items():
        level = KpiLevel(level)
        shared = level == KpiLevel.MOVEMENT and r.is_shared
        out[(kpi, unit, level, element_id)] = PeriodValue(
            r.status, r.value, r.reason,
            measured_on_lane_id=r.measured_on_lane_id if shared else None,
            is_shared=shared,
            uncontrolled_movements=r.uncontrolled_movements or model._slip_note(level, element_id),
        )


# ============================================================
# VOLUME-TO-CAPACITY RATIO
# ============================================================

def _volume_to_capacity(out, days, selected):
    elements = {(level, element_id) for d in days for (level, element_id, _) in d.volume_to_capacity}

    for level, element_id in sorted(elements, key=lambda e: (ELEMENT_LEVELS.index(e[0]), e[1])):
        results = [
            d.volume_to_capacity[(level, element_id, i)]
            for d in days for i in selected[d.day]
        ]
        unavailable = [r for r in results if r.status == KpiStatus.UNAVAILABLE]
        usable = [r for r in results if r.status == KpiStatus.OK]
        key = (VC, KpiUnit.RATIO, level, element_id)

        if unavailable:
            out[key] = PeriodValue(KpiStatus.UNAVAILABLE, reason=unavailable[0].reason)
        elif not usable:
            out[key] = PeriodValue(KpiStatus.NOT_APPLICABLE, reason=results[0].reason)
        else:
            peak = max(usable, key=lambda r: r.value)      # the first one when equal
            out[key] = PeriodValue(
                KpiStatus.OK, peak.value,
                peak_interval=AnalysisInterval(peak.interval_start, peak.interval_end),
            )

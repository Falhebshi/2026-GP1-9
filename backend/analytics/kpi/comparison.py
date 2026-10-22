"""
Combining runs and comparing scenarios (docs/kpi_engine.md section 12).

- Seeds of one scenario are combined into a KpiResult: the mean over
  the runs that have a value, with the sample standard deviation
  (n - 1). If any run is unavailable, the result is unavailable; runs
  without a value because nothing happened (not applicable) are left
  out.
- Queue lengths and storage ratios are combined per lane first; a
  movement, approach or intersection then takes its longest lane.
- A baseline and an intervention are compared pair by pair (matched
  seeds): the mean of the per-pair differences, with their standard
  deviation, as a KpiComparison.
- Before comparing, the runs of the ReplicationSet are checked.
- input_origins are read from the demand records (their source and
  whether they are allocated or imputed) and the signal-program
  source.
"""

import statistics
from typing import NamedTuple

from backend.analytics.kpi.capacity import signal_timing_origin
from backend.analytics.kpi.intervals import AnalysisInterval
from backend.analytics.kpi.parameters import (
    GEOMETRY_INPUT_ORIGIN,
    HCM_DEFAULTS_INPUT_ORIGIN,
    level_of_service,
)
from backend.analytics.kpi.rollup import Part, combine_highest
from jaadah.models.kpis import (
    InputOrigin,
    KpiComparison,
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    UncontrolledMovements,
)
from jaadah.models.network import ApproachLane, Movement
from jaadah.models.scenario import (
    ReplicationPair,
    ReplicationSet,
    Scenario,
    SimulationRun,
    SimulationRunStatus,
)
from jaadah.models.signals import SignalProgram
from jaadah.models.traffic import SimulationDemand, SimulationDemandSource


NO_RUN_VALUE_REASON = "no run has a value for this element"
NO_PAIR_VALUE_REASON = "no pair has a value on both sides"
PART_UNAVAILABLE_REASON = "a part of this element has no result"

# Order in which origins are listed, so equal sets look the same.
_ORIGIN_ORDER = [
    InputOrigin.OBSERVED,
    InputOrigin.MODELLED_ASSUMPTION,
    InputOrigin.SIMULATED,
]


# ============================================================
# INPUTS
# ============================================================

class RunValue(NamedTuple):
    """One run's value of one KPI for one element and interval."""

    status: KpiStatus
    value: float | None
    reason: str | None = None


class KpiSpec(NamedTuple):
    """
    What a KpiResult describes; everything except its value.

    A movement value taken from a shared lane names it in
    measured_on_lane_id (queues), or from a shared lane group in
    measured_on_lane_group_id (HCM values); at most one of the two.
    """

    kpi: KpiName
    level: KpiLevel
    element_id: str
    unit: KpiUnit
    method: KpiMethod
    interval: AnalysisInterval
    scenario_id: str
    input_origins: list[InputOrigin]
    measured_on_lane_id: str | None = None
    measured_on_lane_group_id: str | None = None
    uncontrolled_movements: UncontrolledMovements | None = None


class ComparisonSpec(NamedTuple):
    """What a KpiComparison describes; everything except its change."""

    kpi: KpiName
    level: KpiLevel
    element_id: str
    unit: KpiUnit
    method: KpiMethod
    interval: AnalysisInterval
    baseline_scenario_id: str
    intervention_scenario_id: str
    input_origins: list[InputOrigin]
    replication_set_id: str | None = None
    uncontrolled_movements: UncontrolledMovements | None = None


# ============================================================
# INPUT ORIGINS
# ============================================================

def input_origins(
    method: KpiMethod,
    demands: list[SimulationDemand],
    program: SignalProgram,
    movements: dict[str, Movement],
    interval: AnalysisInterval,
    approach_id: str | None = None,
) -> list[InputOrigin]:
    """
    Where a result's inputs come from (section 12.5).

    The demand records used are those of the result's approach
    (approach_id; None for the intersection, which uses every
    approach) whose interval overlaps the result's interval:
    - RCRC demand is observed; synthetic and forecast demand are
      modelled assumptions;
    - demand that is allocated (split from a shared-lane detector) or
      imputed (estimated for a detector that did not report) is also a
      modelled assumption, whatever its source.
    Signal timing comes from SignalProgram.source and lane geometry is
    a modelled assumption (GEOMETRY_INPUT_ORIGIN). Simulation results
    add simulated; HCM results add the HCM default factors, a modelled
    assumption.

    Raises ValueError for a demand record whose movement is unknown.
    """

    origins = {GEOMETRY_INPUT_ORIGIN, signal_timing_origin(program)}

    for demand in _demands_for(demands, movements, interval, approach_id):
        origins.add(
            InputOrigin.OBSERVED
            if demand.source == SimulationDemandSource.RCRC
            else InputOrigin.MODELLED_ASSUMPTION
        )

        if demand.is_allocated or demand.is_imputed:
            origins.add(InputOrigin.MODELLED_ASSUMPTION)

    if method == KpiMethod.SIMULATION:
        origins.add(InputOrigin.SIMULATED)
    else:
        origins.add(HCM_DEFAULTS_INPUT_ORIGIN)

    return _ordered(origins)


def _demands_for(
    demands: list[SimulationDemand],
    movements: dict[str, Movement],
    interval: AnalysisInterval,
    approach_id: str | None,
) -> list[SimulationDemand]:
    """The demand records of one approach (or all) overlapping an interval."""

    selected = []

    for demand in demands:
        if demand.movement_id not in movements:
            raise ValueError(
                f"demand {demand.demand_id} uses unknown movement "
                f"{demand.movement_id}"
            )

        overlaps = (
            demand.interval_start < interval.end
            and interval.start < demand.interval_end
        )
        on_approach = (
            approach_id is None
            or movements[demand.movement_id].approach_id == approach_id
        )

        if overlaps and on_approach:
            selected.append(demand)

    return selected


def _ordered(origins) -> list[InputOrigin]:
    return [o for o in _ORIGIN_ORDER if o in origins]


# ============================================================
# COMBINING THE RUNS OF ONE SCENARIO
# ============================================================

def combine_runs(spec: KpiSpec, values: dict[str, RunValue]) -> KpiResult:
    """
    Combine the runs of one scenario (run ID -> value) into one
    KpiResult: the mean over the runs with a value and, with two or
    more such runs, the sample standard deviation. run_ids lists the
    runs behind the value; a result without a value lists every run
    that was looked at.
    """

    if not values:
        raise ValueError("at least one run is needed")

    unavailable = [r for r, v in values.items() if v.status == KpiStatus.UNAVAILABLE]

    if unavailable:
        return _result(
            spec,
            KpiStatus.UNAVAILABLE,
            reason=f"unavailable in {len(unavailable)} of {len(values)} runs",
            run_ids=list(values),
        )

    ok = {r: v.value for r, v in values.items() if v.status == KpiStatus.OK}

    if not ok:
        reasons = {v.reason for v in values.values() if v.reason}
        reason = reasons.pop() if len(reasons) == 1 else NO_RUN_VALUE_REASON
        return _result(
            spec, KpiStatus.NOT_APPLICABLE, reason=reason, run_ids=list(values)
        )

    mean = statistics.fmean(ok.values())
    deviation = statistics.stdev(ok.values()) if len(ok) > 1 else None

    return _result(
        spec,
        KpiStatus.OK,
        value=mean,
        standard_deviation=deviation,
        run_ids=list(ok),
    )


def measured_level_of_service(spec: KpiSpec, delay: KpiResult) -> KpiResult:
    """
    Simulation-based level of service, graded from the delay combined
    over the runs (section 7.6), from delay alone.
    """

    if spec.kpi != KpiName.LEVEL_OF_SERVICE:
        raise ValueError("the spec must describe level_of_service")

    if delay.status != KpiStatus.OK:
        return _result(spec, delay.status, reason=delay.reason, run_ids=delay.run_ids)

    return _result(
        spec,
        KpiStatus.OK,
        los_grade=level_of_service(delay.value),
        run_ids=delay.run_ids,
    )


def single_result(
    spec: KpiSpec,
    status: KpiStatus,
    value: float | None,
    reason: str | None = None,
    run_ids: list[str] | None = None,
) -> KpiResult:
    """A result that needs no combining, e.g. an HCM value (no runs)."""

    return _result(spec, status, value=value, reason=reason, run_ids=run_ids or [])


def _result(
    spec: KpiSpec,
    status: KpiStatus,
    value: float | None = None,
    reason: str | None = None,
    standard_deviation: float | None = None,
    run_ids: list[str] | None = None,
    los_grade=None,
) -> KpiResult:
    ok = status == KpiStatus.OK

    return KpiResult(
        kpi=spec.kpi,
        level=spec.level,
        **_element_fields(spec.level, spec.element_id),
        measured_on_lane_id=spec.measured_on_lane_id if ok else None,
        measured_on_lane_group_id=spec.measured_on_lane_group_id if ok else None,
        uncontrolled_movements=spec.uncontrolled_movements if ok else None,
        interval_start=spec.interval.start,
        interval_end=spec.interval.end,
        value=value if ok else None,
        los_grade=los_grade if ok else None,
        unit=spec.unit,
        status=status,
        reason=reason,
        method=spec.method,
        input_origins=spec.input_origins if ok else [],
        scenario_id=spec.scenario_id,
        run_ids=run_ids if run_ids is not None else [],
        standard_deviation=standard_deviation,
    )


def _element_fields(level: KpiLevel, element_id: str) -> dict:
    return {f"{level.value}_id": element_id}


# ============================================================
# QUEUES: LANES FIRST, THEN THE LONGEST LANE (section 12.3)
# ============================================================

class LaneChoice(NamedTuple):
    """
    A movement, approach or intersection queue value and the lane it
    was taken from (None when it is not ok).
    """

    result: KpiResult
    lane_id: str | None


def queue_from_lanes(
    lane_results: dict[str, KpiResult],
    lanes: list[ApproachLane],
    movements: dict[str, Movement],
    uncontrolled_by_approach: set[str] = frozenset(),
) -> dict[tuple[str, str], LaneChoice]:
    """
    Movement, approach and intersection values of a queue length or
    storage ratio from the lane results, already combined over the
    runs: the longest (highest) lane, with that lane's mean, standard
    deviation and runs. Keys are ("movement", id), ("approach", id)
    and ("intersection", id).

    A movement value names its lane in measured_on_lane_id only when
    the lane is shared. uncontrolled_by_approach lists the approaches
    with an uncontrolled slip; their results, and the intersection's,
    are tagged as including uncontrolled movements.
    """

    first = next(iter(lane_results.values()))
    by_lane = {lane.lane_id: lane for lane in lanes}

    intersection_ids = {
        movements[m].intersection_id for lane in lanes for m in lane.served_movement_ids
    }

    if len(intersection_ids) != 1:
        raise ValueError("the lanes must belong to exactly one intersection")

    def choose(level, element_id, own_lanes, tagged):
        parts = [
            Part(
                lane_results[lane.lane_id].status,
                lane_results[lane.lane_id].value,
                lane_id=lane.lane_id,
            )
            for lane in own_lanes
        ]
        rolled = combine_highest(parts)

        shared = False
        if rolled.status == KpiStatus.OK:
            shared = len(by_lane[rolled.measured_on_lane_id].served_movement_ids) > 1

        spec = KpiSpec(
            kpi=first.kpi,
            level=level,
            element_id=element_id,
            unit=first.unit,
            method=first.method,
            interval=AnalysisInterval(first.interval_start, first.interval_end),
            scenario_id=first.scenario_id,
            input_origins=first.input_origins,
            measured_on_lane_id=(
                rolled.measured_on_lane_id
                if level == KpiLevel.MOVEMENT and shared
                else None
            ),
            uncontrolled_movements=UncontrolledMovements.INCLUDED if tagged else None,
        )

        if rolled.status != KpiStatus.OK:
            looked_at = list(
                dict.fromkeys(
                    r for lane in own_lanes for r in lane_results[lane.lane_id].run_ids
                )
            )
            return LaneChoice(
                _result(
                    spec, rolled.status, reason=PART_UNAVAILABLE_REASON,
                    run_ids=looked_at,
                ),
                None,
            )

        source = lane_results[rolled.measured_on_lane_id]

        return LaneChoice(
            _result(
                spec._replace(input_origins=source.input_origins),
                KpiStatus.OK,
                value=source.value,
                standard_deviation=source.standard_deviation,
                run_ids=source.run_ids,
            ),
            rolled.measured_on_lane_id,
        )

    results = {}

    for movement_id in sorted({m for lane in lanes for m in lane.served_movement_ids}):
        own = [lane for lane in lanes if movement_id in lane.served_movement_ids]
        results[("movement", movement_id)] = choose(
            KpiLevel.MOVEMENT, movement_id, own, tagged=False
        )

    for approach_id in sorted({lane.approach_id for lane in lanes}):
        own = [lane for lane in lanes if lane.approach_id == approach_id]
        results[("approach", approach_id)] = choose(
            KpiLevel.APPROACH,
            approach_id,
            own,
            tagged=approach_id in uncontrolled_by_approach,
        )

    intersection_id = intersection_ids.pop()
    results[("intersection", intersection_id)] = choose(
        KpiLevel.INTERSECTION,
        intersection_id,
        lanes,
        tagged=bool(uncontrolled_by_approach),
    )

    return results


# ============================================================
# CHECKING THE RUNS OF A REPLICATION SET (section 12.6)
# ============================================================

def check_replication_set(
    replication_set: ReplicationSet,
    runs: dict[str, SimulationRun],
    scenarios: dict[str, Scenario],
) -> None:
    """
    Raise ValueError unless each pair differs only in the
    intervention:
    - the two scenarios cover the same time window (start_time,
      end_time, time_context) and the intervention references the
      baseline;
    - every run is completed and in its scenario;
    - same seed and same route file within a pair (the same planned
      departures), a different seed in each pair;
    - the same network version, SUMO version, step length, mapping
      version and demand for every run.
    """

    baseline_id = replication_set.baseline_scenario_id
    intervention_id = replication_set.intervention_scenario_id

    for scenario_id in (baseline_id, intervention_id):
        if scenario_id not in scenarios:
            raise ValueError(f"scenario {scenario_id} is missing")

    if scenarios[intervention_id].reference_scenario_id != baseline_id:
        raise ValueError(
            f"intervention scenario {intervention_id} does not reference "
            f"baseline scenario {baseline_id}"
        )

    for field in ("start_time", "end_time", "time_context"):
        baseline_value = getattr(scenarios[baseline_id], field)
        intervention_value = getattr(scenarios[intervention_id], field)

        if baseline_value != intervention_value:
            raise ValueError(
                f"the scenarios differ in {field}: baseline "
                f"{baseline_value}, intervention {intervention_value}"
            )

    seeds = []

    for number, pair in enumerate(replication_set.pairs, start=1):
        for run_id, scenario_id in (
            (pair.baseline_run_id, baseline_id),
            (pair.intervention_run_id, intervention_id),
        ):
            if run_id not in runs:
                raise ValueError(f"run {run_id} is missing")

            run = runs[run_id]

            if run.scenario_id != scenario_id:
                raise ValueError(
                    f"run {run_id} belongs to scenario {run.scenario_id}, "
                    f"not {scenario_id}"
                )

            if run.status != SimulationRunStatus.COMPLETED:
                raise ValueError(f"run {run_id} is {run.status.value}, not completed")

        baseline = runs[pair.baseline_run_id]
        intervention = runs[pair.intervention_run_id]

        if baseline.random_seed != intervention.random_seed:
            raise ValueError(
                f"pair {number} used seeds {baseline.random_seed} and "
                f"{intervention.random_seed}"
            )

        if baseline.route_file_sha256 != intervention.route_file_sha256:
            raise ValueError(
                f"pair {number} used different route files, so its "
                "departures were not planned the same way"
            )

        seeds.append(baseline.random_seed)

    if len(seeds) != len(set(seeds)):
        raise ValueError("each pair must use a different seed")

    all_runs = [
        runs[run_id]
        for pair in replication_set.pairs
        for run_id in (pair.baseline_run_id, pair.intervention_run_id)
    ]

    for field in (
        "network_version",
        "sumo_version",
        "step_length_s",
        "mapping_version",
        "demand_sha256",
    ):
        if len({getattr(run, field) for run in all_runs}) != 1:
            raise ValueError(f"the runs do not all have the same {field}")


# ============================================================
# COMPARING BASELINE AND INTERVENTION (section 12.4)
# ============================================================

def compare_runs(
    spec: ComparisonSpec,
    replication_set: ReplicationSet,
    baseline: dict[str, RunValue],
    intervention: dict[str, RunValue],
) -> KpiComparison:
    """
    Compare matched pairs: for each pair, intervention minus baseline;
    the change is the mean of these differences, with their sample
    standard deviation. If either run of any pair is unavailable, the
    comparison is unavailable; pairs where a side is not applicable
    are left out.

    baseline and intervention map run IDs to the values behind the
    reported results. For a queue, these are the per-run values of
    the lane each scenario's result was taken from, so the change
    equals the difference between the two reported values.
    """

    if spec.method != KpiMethod.SIMULATION:
        raise ValueError("compare_runs is for simulation results")

    _check_labels(
        spec,
        replication_set.baseline_scenario_id,
        replication_set.intervention_scenario_id,
        replication_set.replication_set_id,
        "set",
    )

    pairs = replication_set.pairs

    for pair in pairs:
        if pair.baseline_run_id not in baseline or pair.intervention_run_id not in intervention:
            raise ValueError("every pair needs a value on both sides")

    unavailable = [
        pair
        for pair in pairs
        if KpiStatus.UNAVAILABLE
        in (baseline[pair.baseline_run_id].status, intervention[pair.intervention_run_id].status)
    ]

    if unavailable:
        return _comparison(
            spec,
            KpiStatus.UNAVAILABLE,
            reason=f"unavailable in {len(unavailable)} of {len(pairs)} pairs",
            pair_count=len(pairs),
        )

    used = [
        pair
        for pair in pairs
        if baseline[pair.baseline_run_id].status == KpiStatus.OK
        and intervention[pair.intervention_run_id].status == KpiStatus.OK
    ]

    if not used:
        return _comparison(
            spec,
            KpiStatus.NOT_APPLICABLE,
            reason=NO_PAIR_VALUE_REASON,
            pair_count=len(pairs),
        )

    differences = [
        intervention[p.intervention_run_id].value - baseline[p.baseline_run_id].value
        for p in used
    ]

    return _comparison(
        spec,
        KpiStatus.OK,
        used_pairs=used,
        pair_count=len(pairs),
        mean_change=statistics.fmean(differences),
        standard_deviation=statistics.stdev(differences) if len(used) > 1 else None,
        baseline_mean=statistics.fmean(baseline[p.baseline_run_id].value for p in used),
    )


def compare_single(
    spec: ComparisonSpec,
    baseline: RunValue,
    intervention: RunValue,
) -> KpiComparison:
    """Compare two HCM values (no runs): the plain difference."""

    if spec.method != KpiMethod.HCM:
        raise ValueError("compare_single is for HCM results")

    statuses = (baseline.status, intervention.status)

    if KpiStatus.UNAVAILABLE in statuses:
        return _comparison(spec, KpiStatus.UNAVAILABLE, reason=PART_UNAVAILABLE_REASON)

    if statuses != (KpiStatus.OK, KpiStatus.OK):
        return _comparison(spec, KpiStatus.NOT_APPLICABLE, reason=NO_PAIR_VALUE_REASON)

    return _comparison(
        spec,
        KpiStatus.OK,
        mean_change=intervention.value - baseline.value,
        baseline_mean=baseline.value,
    )


def compare_level_of_service(
    spec: ComparisonSpec,
    delay: KpiComparison,
) -> KpiComparison:
    """
    Compare simulation-based level of service, graded from the delay
    comparison of the same element and interval (section 12.4): the
    baseline grade from its baseline mean, the intervention grade from
    baseline mean + change. Both grades therefore come from the same
    matched pairs as the delay change and never contradict it.
    """

    if spec.method != KpiMethod.SIMULATION or spec.kpi != KpiName.LEVEL_OF_SERVICE:
        raise ValueError("compare_level_of_service is for simulation level of service")

    if (
        delay.kpi != KpiName.CONTROL_DELAY
        or delay.method != KpiMethod.SIMULATION
        or delay.level != spec.level
        or getattr(delay, f"{spec.level.value}_id") != spec.element_id
        or (delay.interval_start, delay.interval_end) != (spec.interval.start, spec.interval.end)
    ):
        raise ValueError(
            "the delay comparison must be the simulation control delay "
            "of the same element and interval"
        )

    _check_labels(
        spec,
        delay.baseline_scenario_id,
        delay.intervention_scenario_id,
        delay.replication_set_id,
        "delay comparison",
    )

    if delay.status != KpiStatus.OK:
        return _comparison(
            spec, delay.status, reason=delay.reason, pair_count=delay.pair_count
        )

    intervention_mean = max(0.0, delay.baseline_mean + delay.mean_change)

    return _comparison(
        spec,
        KpiStatus.OK,
        used_pairs=delay.used_pairs,
        pair_count=delay.pair_count,
        baseline_los_grade=level_of_service(delay.baseline_mean),
        intervention_los_grade=level_of_service(intervention_mean),
    )


def compare_hcm_level_of_service(
    spec: ComparisonSpec,
    baseline: KpiResult,
    intervention: KpiResult,
) -> KpiComparison:
    """
    Compare two HCM level-of-service results: the two grades, e.g.
    D -> C. HCM results have no runs, so both grades are kept as
    graded (including the v/c > 1 override at lane-group and movement
    level).
    """

    if spec.method != KpiMethod.HCM or spec.kpi != KpiName.LEVEL_OF_SERVICE:
        raise ValueError("compare_hcm_level_of_service is for HCM level of service")

    for side, result, scenario_id in (
        ("baseline", baseline, spec.baseline_scenario_id),
        ("intervention", intervention, spec.intervention_scenario_id),
    ):
        mismatches = [
            f"{name}: expected {expected}, got {actual}"
            for name, expected, actual in (
                ("scenario_id", scenario_id, result.scenario_id),
                ("kpi", spec.kpi, result.kpi),
                ("method", spec.method, result.method),
                ("level", spec.level, result.level),
                ("element_id", spec.element_id, getattr(result, f"{spec.level.value}_id")),
                ("interval_start", spec.interval.start, result.interval_start),
                ("interval_end", spec.interval.end, result.interval_end),
                ("unit", spec.unit, result.unit),
            )
            if expected != actual
        ]
        if mismatches:
            raise ValueError(
                f"{side} HCM level-of-service result does not match the "
                f"comparison: {', '.join(mismatches)}"
            )

    statuses = (baseline.status, intervention.status)

    if KpiStatus.UNAVAILABLE in statuses:
        return _comparison(spec, KpiStatus.UNAVAILABLE, reason=PART_UNAVAILABLE_REASON)

    if statuses != (KpiStatus.OK, KpiStatus.OK):
        return _comparison(spec, KpiStatus.NOT_APPLICABLE, reason=NO_PAIR_VALUE_REASON)

    return _comparison(
        spec,
        KpiStatus.OK,
        baseline_los_grade=baseline.los_grade,
        intervention_los_grade=intervention.los_grade,
    )


def _check_labels(
    spec: ComparisonSpec,
    baseline_scenario_id: str,
    intervention_scenario_id: str,
    replication_set_id: str | None,
    source: str,
) -> None:
    """
    Raise ValueError unless the spec's scenario and replication-set IDs
    are those of the data the comparison is calculated from, so a
    result can never carry the labels of another experiment.
    """

    mismatches = [
        f"{name}: spec says {expected}, {source} is {actual}"
        for name, expected, actual in (
            ("baseline_scenario_id", spec.baseline_scenario_id, baseline_scenario_id),
            ("intervention_scenario_id", spec.intervention_scenario_id, intervention_scenario_id),
            ("replication_set_id", spec.replication_set_id, replication_set_id),
        )
        if expected != actual
    ]

    if mismatches:
        raise ValueError("labels do not match: " + "; ".join(mismatches))


def _comparison(
    spec: ComparisonSpec,
    status: KpiStatus,
    reason: str | None = None,
    used_pairs: list[ReplicationPair] | None = None,
    pair_count: int | None = None,
    **values,
) -> KpiComparison:
    ok = status == KpiStatus.OK

    return KpiComparison(
        kpi=spec.kpi,
        level=spec.level,
        **_element_fields(spec.level, spec.element_id),
        interval_start=spec.interval.start,
        interval_end=spec.interval.end,
        unit=spec.unit,
        method=spec.method,
        baseline_scenario_id=spec.baseline_scenario_id,
        intervention_scenario_id=spec.intervention_scenario_id,
        replication_set_id=spec.replication_set_id,
        used_pairs=used_pairs or [],
        pair_count=pair_count,
        status=status,
        reason=reason,
        input_origins=spec.input_origins if ok else [],
        uncontrolled_movements=spec.uncontrolled_movements if ok else None,
        **values,
    )


def combined_origins(*origin_lists: list[InputOrigin]) -> list[InputOrigin]:
    """The origins of both scenarios of a comparison, combined."""

    return _ordered({o for origins in origin_lists for o in origins})

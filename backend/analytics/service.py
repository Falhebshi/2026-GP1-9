"""
The KPIs of one finished baseline run (docs/kpi_engine.md, section 16).

Reads the run folder written by simulation/scripts/run_baseline.py,
turns its SUMO outputs into measurement records with jaadah/kpi_inputs,
runs the KPI engine and returns one KpiResult per KPI, element and
15-minute interval of the analysis period:

- simulation: control delay, level of service, queue duration and
  throughput per movement, approach and intersection; queue length (m
  and veh) and queue storage ratio per lane, movement, approach and
  intersection, also over the whole analysis period (95th-percentile
  cycle queue) when it has more than one interval;
- HCM: control delay, level of service and volume-to-capacity ratio per
  movement, approach and intersection; capacity per movement and
  approach; saturation flow rate per movement.

Only a completed run gives KPIs. The engine itself reads no files; this
module does the reading and writing around it.

Usage (from the repository root):
    python -m backend.analytics.service <run folder> [--scenario baseline] [--out kpis.json]

The results are written to frontend/public/data/<intersection>/<scenario>/kpis.json,
next to the run's playback files, unless --out is given.
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from backend.analytics.kpi.capacity import calculate_capacity
from backend.analytics.kpi.comparison import (
    KpiSpec,
    RunValue,
    combine_runs,
    input_origins,
    measured_level_of_service,
    single_result,
)
from backend.analytics.kpi.delay import (
    blocked_movements,
    blocks_over_period,
    merge_blocks,
    movement_delays,
    uninserted_approaches,
)
from backend.analytics.kpi.hcm_delay import calculate_hcm_delays
from backend.analytics.kpi.intervals import AnalysisInterval, analysis_intervals
from backend.analytics.kpi.lane_groups import derive_lane_groups
from backend.analytics.kpi.parameters import ANALYSIS_INTERVAL_S
from backend.analytics.kpi.queue import (
    approach_interval_queues,
    approach_period_percentile_queues,
    interval_queues,
    period_percentile_queues,
    zone_end_approaches,
)
from backend.analytics.kpi.rollup import (
    hcm_rollup,
    measured_delay_rollup,
    queue_rollup,
    storage_ratio_rollup,
    throughput_rollup,
)
from backend.analytics.kpi.throughput import count_served_vehicles, movement_throughput
from jaadah.kpi_inputs.cycle_queues import collect_cycle_queues
from jaadah.kpi_inputs.network_inputs import build_network_inputs
from jaadah.kpi_inputs.signal_program import build_signal_program
from jaadah.kpi_inputs.vehicle_passages import collect_vehicle_passages
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import (
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    UncontrolledMovements,
)
from jaadah.models.network import MovementControl
from jaadah.models.scenario import SimulationRun, SimulationRunStatus
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import RunWindow
from jaadah.sumo_demand.writer import VEHICLE_TYPE


REPO_ROOT = Path(__file__).resolve().parents[2]
NETWORK_DIR = REPO_ROOT / "data" / "processed" / "road_network"
DEFAULT_MAPPING_PATH = NETWORK_DIR / "network_mappings.json"
DEFAULT_NETWORK_PATH = NETWORK_DIR / "jaadah_study_area.net.xml"
FRONTEND_DATA_DIR = REPO_ROOT / "frontend" / "public" / "data"

# The run folder written by run_baseline.py (docs/simulation_integration.md)
SUMMARY_FILE = "summary.json"
FCD_FILE = Path("run") / "raw" / "fcd.xml"
TRIPINFO_FILE = Path("run") / "raw" / "tripinfo.xml"
MANIFEST_FILE = Path("demand") / "demand_manifest.json"
DEMAND_FILE = Path("demand") / "demand_demand.json"

NOT_SIGNALIZED_REASON = "uncontrolled movement; not a signalised-intersection measure"

M, VEH = KpiUnit.METRES, KpiUnit.VEHICLES


class RunFiles(NamedTuple):
    """One finished run: its record, its time window and its files."""

    run: SimulationRun
    window: RunWindow
    fcd_path: Path
    tripinfo_path: Path
    manifest_path: Path
    demand_path: Path


# ============================================================
# READING A RUN FOLDER
# ============================================================

def load_run(run_dir: str | Path) -> RunFiles:
    """
    Read a run folder: summary.json gives the SimulationRun and the run
    window; the SUMO outputs and demand files sit at fixed places in the
    folder.
    """

    run_dir = Path(run_dir)
    summary = json.loads((run_dir / SUMMARY_FILE).read_text(encoding="utf-8"))
    window = summary["run_window"]

    return RunFiles(
        run=SimulationRun.model_validate(summary["simulation_run"]),
        window=RunWindow(
            epoch=datetime.fromisoformat(window["start"]),
            analysis_start=datetime.fromisoformat(window["analysis_start"]),
            analysis_end=datetime.fromisoformat(window["analysis_end"]),
            run_end=datetime.fromisoformat(window["end"]),
        ),
        fcd_path=run_dir / FCD_FILE,
        tripinfo_path=run_dir / TRIPINFO_FILE,
        manifest_path=run_dir / MANIFEST_FILE,
        demand_path=run_dir / DEMAND_FILE,
    )


# ============================================================
# THE KPIS OF ONE RUN
# ============================================================

def calculate_run_kpis(
    files: RunFiles,
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
    network_path: str | Path = DEFAULT_NETWORK_PATH,
) -> list[KpiResult]:
    """
    The KpiResults of one completed run.

    Raises ValueError when the run did not complete, or when it was run
    with another version of the network mapping.
    """

    run = files.run

    if run.status != SimulationRunStatus.COMPLETED:
        raise ValueError(f"run {run.run_id} is {run.status.value}; only a completed run has KPIs")

    config = load_network_mappings(mapping_path)

    if config.mapping_version != run.mapping_version:
        raise ValueError(
            f"run {run.run_id} used mapping {run.mapping_version}, "
            f"not {config.mapping_version}"
        )

    network = build_network_inputs(config)
    program = build_signal_program(
        config, network_path,
        scenario_id=run.scenario_id, signal_program_id=f"SP_{run.run_id}",
    )
    passages = collect_vehicle_passages(
        config, network_path, run_id=run.run_id, window=files.window,
        fcd_path=files.fcd_path, tripinfo_path=files.tripinfo_path,
        manifest_path=files.manifest_path, demand_path=files.demand_path,
        fcd_period_s=run.step_length_s,
    )
    queues = collect_cycle_queues(
        config, network_path, program, files.fcd_path, run_id=run.run_id,
        window=files.window, vehicle_length_m=float(VEHICLE_TYPE["length"]),
    )
    demands = [
        SimulationDemand.model_validate(record)
        for record in json.loads(files.demand_path.read_text(encoding="utf-8"))
    ]

    return _Calculation(run, files.window, network, program, passages, queues, demands).results()


class _Calculation:
    """The engine calls of one run, kept together for their shared inputs."""

    def __init__(self, run, window, network, program, passages, queues, demands):
        self.run = run
        self.program = program
        self.demands = demands
        self.lanes = network.lanes
        self.movements = {
            m: network.movements[m] for m in network.movement_attributes
        }
        self.attributes = network.movement_attributes
        self.movement_ids = list(self.attributes)
        self.approach_ids = sorted({m.approach_id for m in self.movements.values()})
        self.intersection_id = next(iter(self.movements.values())).intersection_id
        self.intervals = analysis_intervals(window.analysis_start, window.analysis_end)
        self.hcm_intervals = analysis_intervals(window.epoch, window.analysis_end)
        self.slips = {
            m for m, a in self.attributes.items() if a.control == MovementControl.UNCONTROLLED
        }
        self.slip_lane_ids = {
            lane.lane_id for lane in self.lanes
            if set(lane.served_movement_ids) <= self.slips
        }
        self.passages = passages
        self.queues = queues
        self.out: list[KpiResult] = []

    def results(self) -> list[KpiResult]:
        run_id = self.run.run_id

        lane_queues = interval_queues(run_id, [l.lane_id for l in self.lanes], self.intervals, self.queues.lanes)
        # Approaches with signalised movements have full-zone queues; an
        # approach without (none in the study area) has only slip lanes.
        signal_approaches = sorted({q.approach_id for q in self.queues.approaches})
        approach_queues = approach_interval_queues(
            run_id, signal_approaches, self.intervals, self.queues.approaches,
        )
        uninserted = uninserted_approaches(run_id, self.movements, self.intervals, self.passages.uninserted)
        zone_end = zone_end_approaches(approach_queues)
        blocked = merge_blocks(uninserted, zone_end)

        delays = movement_delays(
            run_id, self.movement_ids, self.intervals, self.passages.records,
            self.passages.incomplete, blocked=blocked_movements(self.movements, blocked),
        )
        counts = count_served_vehicles(
            run_id, self.movement_ids, self.intervals, self.passages.records, self.passages.incomplete,
        )
        throughput_blocks = blocked_movements(self.movements, uninserted)
        throughput = movement_throughput(counts, throughput_blocks)
        hcm = self._hcm()

        for interval in self.intervals:
            self._simulation(interval, delays, throughput, throughput_blocks)
            self._queues(interval, lane_queues, approach_queues, blocked)
            self._hcm_results(interval, *hcm[interval])

        # With one interval, the period is that interval: its values are
        # already reported, as the interval's largest cycle queue.
        if len(self.intervals) > 1:
            self._period_queues(signal_approaches, uninserted)

        return self.out

    def _period_queues(self, signal_approaches, uninserted):
        """The 95th-percentile cycle queues over the whole analysis period (section 6.4)."""

        run_id = self.run.run_id
        period = AnalysisInterval(self.intervals[0].start, self.intervals[-1].end)
        lane_queues = {
            (lane_id, period): queue
            for lane_id, queue in period_percentile_queues(
                run_id, [l.lane_id for l in self.lanes], self.intervals, self.queues.lanes,
            ).items()
        }
        approach_queues = {
            (approach_id, period): queue
            for approach_id, queue in approach_period_percentile_queues(
                run_id, signal_approaches, self.intervals, self.queues.approaches,
            ).items()
        }
        blocked = merge_blocks(
            blocks_over_period(uninserted, self.intervals),
            zone_end_approaches(approach_queues),
        )
        self._queues(period, lane_queues, approach_queues, blocked)

    # ---------------- simulation: delay, LOS, queue duration, throughput

    def _simulation(self, interval, delays, throughput, throughput_blocks):
        for quantity, kpi, unit in (
            ("control_delay", KpiName.CONTROL_DELAY, KpiUnit.SECONDS_PER_VEHICLE),
            ("queue_duration", KpiName.QUEUE_DURATION, KpiUnit.SECONDS),
        ):
            field = "mean_control_delay_s" if quantity == "control_delay" else "mean_queue_duration_s"

            for m in self.movement_ids:
                d = delays[(m, interval)]
                result = self._run_result(kpi, KpiLevel.MOVEMENT, m, unit, interval,
                                          RunValue(d.status, getattr(d, field), d.reason))
                if kpi == KpiName.CONTROL_DELAY:
                    self._measured_los(result)

            rolled = measured_delay_rollup(self.movements, self.attributes, delays, interval, quantity)
            for (level, element_id), r in rolled.items():
                result = self._run_result(kpi, KpiLevel(level), element_id, unit, interval,
                                          RunValue(r.status, r.value, r.reason),
                                          uncontrolled=r.uncontrolled_movements)
                if kpi == KpiName.CONTROL_DELAY:
                    self._measured_los(result)

        for m in self.movement_ids:
            t = throughput[(m, interval)]
            self._run_result(KpiName.THROUGHPUT, KpiLevel.MOVEMENT, m, KpiUnit.VEHICLES_PER_HOUR,
                             interval, RunValue(t.status, t.value_veh_h, t.reason))

        flows = {k: v.value_veh_h or 0.0 for k, v in throughput.items()}
        for (level, element_id), r in throughput_rollup(
            self.movements, self.attributes, flows, interval, blocked=throughput_blocks,
        ).items():
            self._run_result(KpiName.THROUGHPUT, KpiLevel(level), element_id,
                             KpiUnit.VEHICLES_PER_HOUR, interval,
                             RunValue(r.status, r.value, r.reason),
                             uncontrolled=r.uncontrolled_movements)

    def _measured_los(self, delay: KpiResult) -> None:
        spec = self._spec(KpiName.LEVEL_OF_SERVICE, delay.level, _element_id(delay),
                          KpiUnit.GRADE, KpiMethod.SIMULATION,
                          AnalysisInterval(delay.interval_start, delay.interval_end),
                          uncontrolled=delay.uncontrolled_movements)
        self.out.append(measured_level_of_service(spec, delay))

    # ---------------- simulation: queue length and storage ratio

    def _queues(self, interval, lane_queues, approach_queues, blocked):
        all_approaches = {(a, interval): approach_queues.get((a, interval)) for a in self.approach_ids}

        for unit in (M, VEH):
            rolled = queue_rollup(
                self.lanes, self.movements, lane_queues, interval,
                approach_queues=all_approaches, slip_lane_ids=self.slip_lane_ids,
                blocked=blocked, unit="m" if unit == M else "veh",
            )
            self._queue_results(KpiName.QUEUE_LENGTH, unit, interval, rolled)

        rolled = storage_ratio_rollup(self.lanes, self.movements, lane_queues, interval, blocked=blocked)
        self._queue_results(KpiName.QUEUE_STORAGE_RATIO, KpiUnit.RATIO, interval, rolled)

    def _queue_results(self, kpi, unit, interval, rolled):
        for (level, element_id), r in rolled.items():
            level = KpiLevel(level)
            shared_lane = r.measured_on_lane_id if level == KpiLevel.MOVEMENT and r.is_shared else None
            self._run_result(kpi, level, element_id, unit, interval,
                             RunValue(r.status, r.value, r.reason),
                             measured_on_lane_id=shared_lane,
                             uncontrolled=(r.uncontrolled_movements
                                           or self._slip_note(level, element_id)))

    def _slip_note(self, level, element_id):
        """Queue results of an element with a slip include it (section 11.3)."""

        if level == KpiLevel.INTERSECTION and self.slips:
            return UncontrolledMovements.INCLUDED
        if level == KpiLevel.APPROACH and any(
            self.movements[m].approach_id == element_id for m in self.slips
        ):
            return UncontrolledMovements.INCLUDED
        return None

    # ---------------- HCM

    def _hcm(self):
        """Capacity and HCM delay of every interval from the warm-up start (section 13.4)."""

        groups = derive_lane_groups(self.lanes, list(self.attributes.values()))
        lanes_by_id = {lane.lane_id: lane for lane in self.lanes}
        per_hour = 3600 / ANALYSIS_INTERVAL_S
        capacity_by_interval = []

        for interval in self.hcm_intervals:
            demand = {
                d.movement_id: d.vehicle_count * per_hour
                for d in self.demands
                if d.interval_start == interval.start and d.movement_id in self.attributes
            }
            capacity_by_interval.append((interval, calculate_capacity(
                groups, lanes_by_id, self.movements, self.attributes, self.program, demand,
            )))

        delays = calculate_hcm_delays(capacity_by_interval, self.program)

        return {
            interval: (groups, capacity, delay)
            for (interval, capacity), delay in zip(capacity_by_interval, delays)
            if interval in self.intervals
        }

    def _hcm_results(self, interval, groups, capacity, hcm):
        for m in self.movement_ids:
            if m in self.slips:
                for kpi, unit in _HCM_MOVEMENT_KPIS:
                    self._hcm_result(kpi, KpiLevel.MOVEMENT, m, unit, interval,
                                     KpiStatus.NOT_APPLICABLE, None, NOT_SIGNALIZED_REASON)
                continue

            c = capacity.movements[m]
            d = hcm.movements[m]
            shared = c.shared_lane_group_id
            self._hcm_result(KpiName.CONTROL_DELAY, KpiLevel.MOVEMENT, m, KpiUnit.SECONDS_PER_VEHICLE,
                             interval, d.status, d.control_delay_s, d.reason, shared)
            self._hcm_result(KpiName.LEVEL_OF_SERVICE, KpiLevel.MOVEMENT, m, KpiUnit.GRADE,
                             interval, d.status, None, d.reason, shared, los=d.los_grade)
            for kpi, field, unit in (
                (KpiName.VOLUME_TO_CAPACITY_RATIO, "volume_to_capacity", KpiUnit.RATIO),
                (KpiName.CAPACITY, "capacity_veh_h", KpiUnit.VEHICLES_PER_HOUR),
                (KpiName.SATURATION_FLOW_RATE, "saturation_flow_veh_h", KpiUnit.VEHICLES_PER_HOUR),
            ):
                self._hcm_result(kpi, KpiLevel.MOVEMENT, m, unit, interval,
                                 c.status, getattr(c, field), c.reason, shared)

        rolled = hcm_rollup(groups, self.movements, self.attributes, capacity, hcm)
        for (kpi, level, element_id), r in rolled.items():
            level = KpiLevel(level)
            if kpi == "control_delay":
                self._hcm_result(KpiName.CONTROL_DELAY, level, element_id, KpiUnit.SECONDS_PER_VEHICLE,
                                 interval, r.status, r.value, r.reason,
                                 uncontrolled=r.uncontrolled_movements)
                self._hcm_result(KpiName.LEVEL_OF_SERVICE, level, element_id, KpiUnit.GRADE,
                                 interval, r.status, None, r.reason,
                                 uncontrolled=r.uncontrolled_movements, los=r.los_grade)
            elif kpi == "volume_to_capacity":
                self._hcm_result(KpiName.VOLUME_TO_CAPACITY_RATIO, level, element_id, KpiUnit.RATIO,
                                 interval, r.status, r.value, r.reason)
            else:
                self._hcm_result(KpiName.CAPACITY, level, element_id, KpiUnit.VEHICLES_PER_HOUR,
                                 interval, r.status, r.value, r.reason)

        self._hcm_result(KpiName.VOLUME_TO_CAPACITY_RATIO, KpiLevel.INTERSECTION, self.intersection_id,
                         KpiUnit.RATIO, interval, capacity.critical_status,
                         capacity.critical_volume_to_capacity, capacity.critical_reason)

    # ---------------- building results

    def _approach_of(self, level, element_id):
        if level == KpiLevel.MOVEMENT:
            return self.movements[element_id].approach_id
        if level == KpiLevel.LANE:
            return next(l.approach_id for l in self.lanes if l.lane_id == element_id)
        if level == KpiLevel.APPROACH:
            return element_id
        return None

    def _spec(self, kpi, level, element_id, unit, method, interval, *,
              measured_on_lane_id=None, measured_on_lane_group_id=None, uncontrolled=None):
        return KpiSpec(
            kpi=kpi, level=level, element_id=element_id, unit=unit, method=method,
            interval=interval, scenario_id=self.run.scenario_id,
            input_origins=input_origins(method, self.demands, self.program, self.movements,
                                        interval, self._approach_of(level, element_id)),
            measured_on_lane_id=measured_on_lane_id,
            measured_on_lane_group_id=measured_on_lane_group_id,
            uncontrolled_movements=uncontrolled,
        )

    def _run_result(self, kpi, level, element_id, unit, interval, value, *,
                    measured_on_lane_id=None, uncontrolled=None) -> KpiResult:
        spec = self._spec(kpi, level, element_id, unit, KpiMethod.SIMULATION, interval,
                          measured_on_lane_id=measured_on_lane_id, uncontrolled=uncontrolled)
        result = combine_runs(spec, {self.run.run_id: value})
        self.out.append(result)
        return result

    def _hcm_result(self, kpi, level, element_id, unit, interval, status, value, reason,
                    shared_group=None, *, uncontrolled=None, los=None) -> None:
        spec = self._spec(kpi, level, element_id, unit, KpiMethod.HCM, interval,
                          measured_on_lane_group_id=shared_group, uncontrolled=uncontrolled)
        self.out.append(single_result(spec, status, value, reason, los_grade=los))


_HCM_MOVEMENT_KPIS = [
    (KpiName.CONTROL_DELAY, KpiUnit.SECONDS_PER_VEHICLE),
    (KpiName.LEVEL_OF_SERVICE, KpiUnit.GRADE),
    (KpiName.VOLUME_TO_CAPACITY_RATIO, KpiUnit.RATIO),
    (KpiName.CAPACITY, KpiUnit.VEHICLES_PER_HOUR),
    (KpiName.SATURATION_FLOW_RATE, KpiUnit.VEHICLES_PER_HOUR),
]


def _element_id(result: KpiResult) -> str:
    return getattr(result, f"{result.level.value}_id")


# ============================================================
# WRITING
# ============================================================

def write_kpis(results: list[KpiResult], path: str | Path, run: SimulationRun) -> Path:
    """
    Write the results as JSON in the dashboard form (data_models.md
    section 6.8: with the computed fields), with the run they belong to.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run.run_id,
        "scenario_id": run.scenario_id,
        "results": [r.model_dump(mode="json") for r in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--scenario", default="baseline")
    parser.add_argument("--out", type=Path, help="default: frontend/public/data/<intersection>/<scenario>/kpis.json")
    args = parser.parse_args()

    files = load_run(args.run_dir)
    results = calculate_run_kpis(files)
    intersection_id = next(r.intersection_id for r in results if r.intersection_id)
    out = args.out or FRONTEND_DATA_DIR / intersection_id / args.scenario / "kpis.json"
    write_kpis(results, out, files.run)

    counts = {status: sum(r.status == status for r in results) for status in KpiStatus}
    print(f"{len(results)} results: " + ", ".join(f"{s.value} {n}" for s, n in counts.items()))
    print(f"Written: {out}")


if __name__ == "__main__":
    main()

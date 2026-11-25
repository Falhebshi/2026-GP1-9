"""
One update of a live chain: simulate the interval the traffic source has
just delivered, continuing from the last saved state.

Steps, in order:

1. plan the departures of the chain's whole demand so far, with the
   chain's seed and second 0 (jaadah/sumo_demand/planner.py);
2. check that the departures already simulated are exactly those planned
   now, so the saved state and the demand files cannot disagree;
3. write and check the chain's SUMO demand files
   (jaadah/sumo_demand/writer.py and checks.py), as every run does;
4. run the new segment with the departures after the previous segment's
   end, up to the new end;
5. save the chain's demand and its record.

Nothing in the record changes until the segment has finished, so an
update that fails or is stopped leaves the chain as it was, and the loop
simply runs it again. A segment folder left by such an update is not in
the record and is removed first. The demand is saved just before the
record: if the loop stops between the two, the demand file holds one
interval more than the record, and load_demand leaves it out.
"""

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.checks import check_generated_demand
from jaadah.sumo_demand.planner import (
    DemandPlan,
    demand_movement_ids,
    movement_routes,
    plan_departures,
)
from jaadah.sumo_demand.writer import GeneratedDemand, write_sumo_demand
from simulation.live.chain import (
    ChainError,
    ChainRecord,
    EstimatedInterval,
    SegmentRecord,
    save_record,
    segment_end_s,
    segment_route_xml,
)
from simulation.live.demand import save_demand
from simulation.live.publish import chain_window
from simulation.live.segments import run_segment

DEMAND_DIR = "demand"
SEGMENTS_DIR = "segments"


@dataclass
class UpdateResult:
    """What one update produced."""

    segment: SegmentRecord
    generated: GeneratedDemand


def departures_fingerprint(plan: DemandPlan, up_to_s: float) -> str:
    """SHA-256 of the planned departures up to and including up_to_s."""

    rows = [
        f"{item.vehicle_id}|{item.demand_id}|{item.depart_s:.2f}"
        for item in plan.departures
        if item.depart_s <= up_to_s
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def segment_folder_name(number: int, interval_end: datetime) -> str:
    """e.g. 007_0430: the 8th segment, for the interval ending at 04:30."""

    return f"{number:03d}_{interval_end:%H%M}"


def remove_unrecorded_segments(record: ChainRecord, work_dir: Path) -> list[Path]:
    """Remove segment folders the record does not list: left by an update that did not finish."""

    folder = work_dir / SEGMENTS_DIR
    if not folder.is_dir():
        return []

    recorded = {Path(item.folder).name for item in record.segments}
    removed = []
    for path in sorted(folder.iterdir()):
        if path.is_dir() and path.name not in recorded:
            shutil.rmtree(path)
            removed.append(path)
    return removed


def run_update(
    record: ChainRecord,
    work_dir: Path,
    chain_demand: list[SimulationDemand],
    new_demand: list[SimulationDemand],
    estimated: EstimatedInterval | None,
    *,
    mapping: NetworkMappingConfig,
    network_path: str | Path,
    free_flow_s: dict[str, float],
    sumo_bin: str = "sumo",
) -> UpdateResult:
    """
    Simulate the chain's next interval with its new demand, and save the
    chain. chain_demand is the demand of the intervals already simulated,
    new_demand that of the next interval.

    Raises ChainError when the departures already simulated would change,
    and the errors of the demand writer, the demand checks and the
    segment when those fail; the record is then unchanged.
    """

    work_dir = Path(work_dir)
    interval_end = record.next_interval_end()
    begin_s = record.last_end_s
    end_s = segment_end_s(record.epoch_time, interval_end)

    if any(item.interval_end != interval_end for item in new_demand):
        raise ChainError(f"the new demand is not all for the interval ending {interval_end.isoformat()}")

    demands = chain_demand + new_demand
    window = chain_window(record, interval_end)
    plan = plan_departures(
        demands,
        window=window,
        routes=movement_routes(mapping),
        expected_movements=demand_movement_ids(mapping),
        free_flow_s=free_flow_s,
        seed=record.seed,
    )

    if record.segments and departures_fingerprint(plan, begin_s) != record.departures_sha256:
        raise ChainError(
            "the departures already simulated would change: the chain's demand or the "
            "planner differs from the one the chain was simulated with"
        )

    demand_dir = work_dir / DEMAND_DIR
    generated = write_sumo_demand(plan, demands, mapping, demand_dir)
    check_generated_demand(demand_dir, mapping, network_path, window=window, seed=record.seed)

    remove_unrecorded_segments(record, work_dir)
    number = len(record.segments)
    folder = Path(SEGMENTS_DIR) / segment_folder_name(number, interval_end)
    previous_state = (
        work_dir / record.segments[-1].folder / "state.xml.gz" if record.segments else None
    )
    run_segment(
        work_dir / folder,
        segment_route_xml(generated.route_file.read_bytes(), begin_s, end_s),
        begin_s=begin_s,
        end_s=end_s,
        network_path=network_path,
        seed=record.seed,
        step_length_s=record.step_length_s,
        load_state=previous_state,
        sumo_bin=sumo_bin,
    )

    segment = SegmentRecord(
        number=number,
        interval_end=interval_end.isoformat(),
        begin_s=begin_s,
        end_s=end_s,
        folder=str(folder),
    )
    save_demand(demands, work_dir)
    record.segments.append(segment)
    if estimated is not None:
        record.estimated_intervals.append(estimated)
    record.departures_sha256 = departures_fingerprint(plan, end_s)
    save_record(record, work_dir)

    return UpdateResult(segment=segment, generated=generated)


def generated_demand_of(work_dir: Path) -> GeneratedDemand:
    """The chain's current demand files, with their fingerprints, for publishing."""

    folder = Path(work_dir) / DEMAND_DIR
    prefix = folder.name
    paths = {
        "route_file": folder / f"{prefix}_routes.rou.xml",
        "manifest_file": folder / f"{prefix}_manifest.json",
        "demand_file": folder / f"{prefix}_demand.json",
    }
    return GeneratedDemand(
        **paths,
        route_file_sha256=hashlib.sha256(paths["route_file"].read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(paths["manifest_file"].read_bytes()).hexdigest(),
        demand_sha256=hashlib.sha256(paths["demand_file"].read_bytes()).hexdigest(),
    )

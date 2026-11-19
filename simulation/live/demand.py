"""
The demand of a live chain, built one interval at a time and then kept
unchanged.

Each update builds the movement demand of the newest interval only,
with the same transformation as every Jaadah run
(backend/demand/service.py): the interval's observations, plus the
source's earlier observations as history for estimating detectors that
did not report. The records are added to the chain's demand file and
never rebuilt.

Rules applied, and why:

- Built once, kept unchanged: the intervals already simulated must keep
  exactly the demand they were simulated with, or the vehicles of the
  saved state and the demand file would disagree. Demand IDs and each
  record's departures do not depend on other intervals (they are seeded
  by movement and interval), so adding an interval changes nothing
  before it.
- History: the HISTORY_DAYS whole days before the interval's day, plus
  that day up to the interval, fetched again at every update (about
  40,000 rows, about a second). Whole days give every time slot of the
  day the same days behind it; cutting the history exactly 35 days
  before the interval would drop the first day's earlier slots, and the
  time-slot average of such a slot can then have too few values (it
  needs 3 of the same day type). The history holds the chain's own
  earlier intervals, so a gap is counted back from now, as the live
  rule requires (PBI 8, Decision 12).
- Long gaps: the live loop estimates a silent detector for up to
  LIVE_FALLBACK_GAP_INTERVALS (8, two hours), with the plain time-slot
  average after the 5th interval (backend/demand/imputation.py). A
  longer gap leaves the interval without demand, and the loop pauses
  (simulation/live/loop.py).
- Rejected source rows are left out and reported, as in ingestion
  everywhere; their detectors count as not reported for that interval,
  so they are estimated and the interval is marked as estimated.
- Estimated intervals: an interval in which any count was estimated for
  a detector that did not report. The page shows "No sensor data" for
  it (team decision, option 3), so it is recorded with the approaches
  and estimation methods involved.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from backend.demand.imputation import LIVE_FALLBACK_GAP_INTERVALS
from backend.demand.service import build_simulation_demand
from backend.ingestion.service import (
    ingest_rcrc_observations,
    ingest_synthetic_observations,
)
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import SimulationDemand
from simulation.live.chain import INTERVAL, EstimatedInterval

HISTORY_DAYS = 35
DEMAND_FILE = "live_demand.json"
INGESTERS = {
    "rcrc": ingest_rcrc_observations,
    "synthetic": ingest_synthetic_observations,
}


@dataclass
class IntervalDemand:
    """The demand of one new interval, or why it could not be built."""

    interval_end: datetime
    demands: list[SimulationDemand]
    problems: list[str]
    rejected_rows: int

    @property
    def complete(self) -> bool:
        return not self.problems


def build_interval_demand(
    client,
    interval_end: datetime,
    *,
    source: str,
    mapping_path: str | Path,
    available_until: datetime,
    history_days: int = HISTORY_DAYS,
) -> IntervalDemand:
    """
    Build the movement demand of the interval ending at interval_end.
    Problems (a movement without demand, for example after a gap longer
    than the live limit) are returned, not raised: the loop decides what
    to do.
    """

    ingest = INGESTERS[source]
    start = interval_end - INTERVAL
    first_day = (start - timedelta(days=history_days)).date()
    history_start = datetime.combine(first_day, time(0), start.tzinfo)
    batch = ingest(client, start=start, end=interval_end)
    history = ingest(client, start=history_start, end=start).observations

    transformation = build_simulation_demand(
        batch.observations,
        mapping_path=mapping_path,
        history=history,
        window_start=start,
        window_end=interval_end,
        available_until=available_until,
        fallback_gap_intervals=LIVE_FALLBACK_GAP_INTERVALS,
    )
    problems = [
        " ".join(part for part in (
            error.movement_id or "",
            f"detector {error.detector_id}" if error.detector_id else "",
            error.message,
        ) if part)
        for error in transformation.errors
    ]

    return IntervalDemand(
        interval_end=interval_end,
        demands=transformation.demands,
        problems=problems,
        rejected_rows=len(batch.errors),
    )


def estimated_interval(
    demands: list[SimulationDemand],
    mapping: NetworkMappingConfig,
) -> EstimatedInterval | None:
    """
    The estimated-interval entry for one interval's demand, or None when
    every detector reported. Allocated shared-lane counts and the slip
    and bypass shares are modelled assumptions of every interval, not
    missing data, so they do not count.
    """

    approach_of = {item.movement_id: item.approach_id for item in mapping.movement_mappings}
    imputed = [demand for demand in demands if demand.is_imputed]

    if not imputed:
        return None

    return EstimatedInterval(
        interval_start=imputed[0].interval_start.isoformat(),
        interval_end=imputed[0].interval_end.isoformat(),
        approach_ids=sorted({approach_of.get(item.movement_id) or "unknown" for item in imputed}),
        methods=sorted({
            detector.method.value
            for item in imputed
            for detector in item.imputed_detectors
        }),
    )


def load_demand(folder: str | Path) -> list[SimulationDemand]:
    """The chain's demand so far, oldest interval first."""

    path = Path(folder) / DEMAND_FILE

    if not path.is_file():
        return []

    return [
        SimulationDemand.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def save_demand(demands: list[SimulationDemand], folder: str | Path) -> Path:
    """Write the chain's demand whole: under a temporary name, then renamed."""

    path = Path(folder) / DEMAND_FILE
    temporary = path.with_name(path.name + ".tmp")
    payload = [
        demand.model_dump(mode="json", exclude={"is_allocated", "is_imputed", "is_share_estimated"})
        for demand in demands
    ]
    temporary.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path

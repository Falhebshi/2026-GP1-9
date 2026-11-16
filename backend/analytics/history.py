"""
The measurement store of the historical analysis (docs/kpi_engine.md,
section 17).

A day's simulation leaves a 4 GB FCD file, but the KPIs need only what
collect_measurements reads from it: one record per vehicle passage, one
per lane and per approach per signal cycle, the vehicles that could not
enter the network, and the demand. These are kept, one compressed file
per day, and the FCD is deleted. Any period's KPIs are then calculated
from the stored days with the engine's own functions, so a day, a week
and a 15-minute interval follow the same rules.

Rules applied, and why:

- One file per whole day, 00:00-24:00 Riyadh time: a stored day is a
  calendar day, so periods and day types (weekdays, weekends) are made
  of whole days.
- Only measurements are stored, never KPI results: the results are
  calculated from the measurements, so storing both would keep two
  copies of the same facts.
- A file is written under a temporary name and renamed when complete,
  so a run that stops half-way never leaves a partial day behind.
- Every file carries a format version; a file of another version is
  refused rather than read wrongly.

The folder is data/history/ in the repository, ignored by git: the
files are large and can be rebuilt, since each day's run has a fixed
seed.
"""

import gzip
import json
import os
from datetime import date, timedelta
from pathlib import Path

from backend.analytics.service import REPO_ROOT, RunMeasurements
from jaadah.kpi_inputs.cycle_queues import CycleQueues
from jaadah.kpi_inputs.vehicle_passages import VehiclePassages
from jaadah.models.outputs import (
    ApproachCycleQueueRecord,
    CycleQueueRecord,
    IncompletePassage,
    UninsertedVehicle,
    VehicleDelayRecord,
)
from jaadah.models.scenario import SimulationRun
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import RunWindow


HISTORY_DIR = REPO_ROOT / "data" / "history"
FORMAT_VERSION = 1
SUFFIX = ".json.gz"

RIYADH_OFFSET = timedelta(hours=3)
ONE_DAY = timedelta(days=1)

# Computed fields of SimulationDemand: in its dump, not accepted back
DEMAND_COMPUTED_FIELDS = {"is_allocated", "is_imputed"}


class HistoryError(ValueError):
    """Raised when a day cannot be stored or a stored day cannot be read."""


def day_file(day: date, folder: str | Path = HISTORY_DIR) -> Path:
    """The file of one stored day, e.g. data/history/2026-10-22.json.gz."""

    return Path(folder) / f"{day.isoformat()}{SUFFIX}"


def stored_days(folder: str | Path = HISTORY_DIR) -> list[date]:
    """The days stored in the folder, oldest first; other files are ignored."""

    folder = Path(folder)
    if not folder.is_dir():
        return []

    days = []
    for path in folder.glob(f"*{SUFFIX}"):
        try:
            days.append(date.fromisoformat(path.name.removesuffix(SUFFIX)))
        except ValueError:
            continue

    return sorted(days)


def save_day(measurements: RunMeasurements, folder: str | Path = HISTORY_DIR) -> Path:
    """
    Store one whole day's measurements and return the file.

    Raises HistoryError when the run's analysis period is not one whole
    day (00:00-24:00 Riyadh time), and FileExistsError when the day is
    already stored (delete the file first to replace it).
    """

    day = whole_day_of(measurements.window)
    path = day_file(day, folder)

    if path.exists():
        raise FileExistsError(f"{day} is already stored: {path}")

    payload = {
        "format_version": FORMAT_VERSION,
        "run": measurements.run.model_dump(mode="json"),
        "window": measurements.window.model_dump(mode="json"),
        "vehicle_records": _dump(measurements.passages.records),
        "incomplete_passages": _dump(measurements.passages.incomplete),
        "uninserted_vehicles": _dump(measurements.passages.uninserted),
        "lane_cycle_queues": _dump(measurements.queues.lanes),
        "approach_cycle_queues": _dump(measurements.queues.approaches),
        "demands": [
            d.model_dump(mode="json", exclude=DEMAND_COMPUTED_FIELDS)
            for d in measurements.demands
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")

    with gzip.open(partial, "wt", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False)

    os.replace(partial, path)
    return path


def load_day(day: date, folder: str | Path = HISTORY_DIR) -> RunMeasurements:
    """
    Read one stored day back into the measurements it was saved from.

    Raises HistoryError when the day is not stored, the file has another
    format version, or it holds another day.
    """

    path = day_file(day, folder)

    if not path.exists():
        raise HistoryError(f"{day} is not stored ({path})")

    with gzip.open(path, "rt", encoding="utf-8") as file:
        payload = json.load(file)

    version = payload.get("format_version")
    if version != FORMAT_VERSION:
        raise HistoryError(
            f"{path.name} has format version {version}; "
            f"this version of Jaadah reads version {FORMAT_VERSION}"
        )

    window = RunWindow.model_validate(payload["window"])
    if whole_day_of(window) != day:
        raise HistoryError(f"{path.name} holds {whole_day_of(window)}, not {day}")

    return RunMeasurements(
        run=SimulationRun.model_validate(payload["run"]),
        window=window,
        passages=VehiclePassages(
            records=[VehicleDelayRecord.model_validate(r) for r in payload["vehicle_records"]],
            incomplete=[IncompletePassage.model_validate(r) for r in payload["incomplete_passages"]],
            uninserted=[UninsertedVehicle.model_validate(r) for r in payload["uninserted_vehicles"]],
        ),
        queues=CycleQueues(
            lanes=[CycleQueueRecord.model_validate(r) for r in payload["lane_cycle_queues"]],
            approaches=[ApproachCycleQueueRecord.model_validate(r) for r in payload["approach_cycle_queues"]],
        ),
        demands=[SimulationDemand.model_validate(d) for d in payload["demands"]],
    )


def whole_day_of(window: RunWindow) -> date:
    """
    The day a run's analysis period covers. Raises HistoryError when the
    period is not exactly one day from midnight, Riyadh time.
    """

    start, end = window.analysis_start, window.analysis_end

    if start.utcoffset() != RIYADH_OFFSET:
        raise HistoryError(f"analysis start {start.isoformat()} is not in Riyadh time (+03:00)")

    if (start.hour, start.minute, start.second, start.microsecond) != (0, 0, 0, 0) or end - start != ONE_DAY:
        raise HistoryError(
            f"analysis period {start.isoformat()} to {end.isoformat()} "
            "is not one whole day (00:00-24:00)"
        )

    return start.date()


def _dump(records) -> list[dict]:
    return [r.model_dump(mode="json") for r in records]

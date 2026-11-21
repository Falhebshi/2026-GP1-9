"""
Read the output of the calibration induction loops (E1) of one run.

SUMO writes one <interval> per loop and period, in seconds of
simulation time. Each becomes a DetectorInterval in Riyadh time,
labelled like the source: by the interval end.

Values used:
- nVehContrib: vehicles whose front passed the loop in the interval
  (the count; SUMO's nVehEntered is not used);
- occupancy: percent of the interval the loop was covered.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from .detectors import loop_id
from ..models.mappings import DetectorMapping


@dataclass(frozen=True)
class DetectorInterval:
    """What one simulated detector measured in one interval."""

    detector_id: str
    interval_end: datetime
    vehicle_count: int
    occupancy_percent: float


def read_e1_intervals(
    output_path: str | Path,
    detectors: list[DetectorMapping],
    run_start: datetime,
) -> list[DetectorInterval]:
    """
    Return every interval of the given detectors' loops.

    run_start is the wall-clock time of simulation second 0 (the start
    of the warm-up). It must be timezone-aware.
    """

    if run_start.tzinfo is None or run_start.utcoffset() is None:
        raise ValueError("run_start must be timezone-aware")

    by_loop = {loop_id(item): item.detector_id for item in detectors}
    intervals = []

    for element in ET.parse(output_path).getroot().iter("interval"):
        detector_id = by_loop.get(element.get("id"))
        if detector_id is None:
            continue

        end_s = float(element.get("end"))
        intervals.append(
            DetectorInterval(
                detector_id=detector_id,
                interval_end=run_start + timedelta(seconds=end_s),
                vehicle_count=round(float(element.get("nVehContrib"))),
                occupancy_percent=float(element.get("occupancy")),
            )
        )

    return intervals

"""
Place SUMO induction loops (E1 detectors) where the source detectors are.

An E1 detector is SUMO's version of a loop detector buried in the road:
it sits at one point of one lane and, every period, writes how many
vehicles passed over it and the share of time it was occupied. Placing
one at each mapped RCRC detector position lets the simulation be
measured the same way the real intersection was.

Positions come only from the mapping (DetectorMapping.sumo_lane_id and
sumo_position_m); this module never chooses a position itself.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

from ..models.mappings import DetectorMapping, NetworkMappingConfig
from .parameters import E1_PERIOD_S


class CalibrationDetectorError(ValueError):
    """The mapping cannot place a detector needed for calibration."""


def loop_id(detector: DetectorMapping) -> str:
    """SUMO ID of the loop for a source detector: E1_<site>_<detector>."""

    return f"E1_{detector.site_id}_{detector.detector_id}"


def calibration_detectors(
    config: NetworkMappingConfig,
    *,
    source: str,
    site_id: str,
) -> list[DetectorMapping]:
    """
    Return the source's detectors at one site, in mapping order.

    Every one must have a SUMO lane and position: a detector that cannot
    be placed cannot be compared, so it is an error, not a skip.
    """

    detectors = [
        item
        for item in config.detector_mappings
        if item.source == source and item.site_id == site_id
    ]

    if not detectors:
        raise CalibrationDetectorError(f"no {source} detectors mapped at site {site_id}")

    unplaced = [item.detector_id for item in detectors if item.sumo_lane_id is None]
    if unplaced:
        raise CalibrationDetectorError(
            f"detectors without a SUMO position: {', '.join(unplaced)}"
        )

    return detectors


def write_e1_additional(
    detectors: list[DetectorMapping],
    additional_path: str | Path,
    output_path: str | Path,
    *,
    period_s: int = E1_PERIOD_S,
) -> Path:
    """
    Write a SUMO additional file with one induction loop per detector.

    All loops write to output_path. Aggregation intervals start at
    simulation time 0, so a run that starts on a 15-minute boundary
    (as every Jaadah run does) gets intervals aligned with the source.
    """

    if period_s <= 0:
        raise ValueError("period_s must be positive")

    root = ET.Element("additional")
    for detector in detectors:
        ET.SubElement(
            root,
            "inductionLoop",
            id=loop_id(detector),
            lane=detector.sumo_lane_id,
            pos=f"{detector.sumo_position_m:g}",
            period=str(period_s),
            file=str(output_path),
        )

    ET.indent(root)
    path = Path(additional_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return path

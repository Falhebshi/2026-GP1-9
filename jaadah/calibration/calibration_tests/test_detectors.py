from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from jaadah.calibration.detectors import (
    CalibrationDetectorError,
    calibration_detectors,
    loop_id,
    write_e1_additional,
)
from jaadah.mapping.loader import load_network_mappings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"


@pytest.fixture(scope="module")
def config():
    return load_network_mappings(MAPPING_PATH)


def test_every_rcrc_detector_at_site_1444_can_be_placed(config):
    detectors = calibration_detectors(config, source="rcrc", site_id="1444")
    assert len(detectors) == 12
    assert all(item.sumo_lane_id and item.sumo_position_m is not None for item in detectors)


def test_unknown_site_is_an_error(config):
    with pytest.raises(CalibrationDetectorError, match="no rcrc detectors"):
        calibration_detectors(config, source="rcrc", site_id="0000")


def test_a_detector_without_a_position_is_an_error(config):
    unplaced = config.model_copy(deep=True)
    first = next(item for item in unplaced.detector_mappings if item.source == "rcrc")
    object.__setattr__(first, "sumo_lane_id", None)
    object.__setattr__(first, "sumo_position_m", None)
    with pytest.raises(CalibrationDetectorError, match=first.detector_id):
        calibration_detectors(unplaced, source="rcrc", site_id="1444")


def test_additional_file_has_one_loop_per_detector(config, tmp_path):
    detectors = calibration_detectors(config, source="rcrc", site_id="1444")
    path = write_e1_additional(detectors, tmp_path / "e1.add.xml", tmp_path / "e1_out.xml")

    loops = ET.parse(path).getroot().findall("inductionLoop")
    assert [loop.get("id") for loop in loops] == [loop_id(item) for item in detectors]
    for loop, item in zip(loops, detectors):
        assert loop.get("lane") == item.sumo_lane_id
        assert float(loop.get("pos")) == pytest.approx(item.sumo_position_m)
        assert loop.get("period") == "900"
        assert loop.get("file") == str(tmp_path / "e1_out.xml")


def test_loop_ids_name_site_and_detector(config):
    first = calibration_detectors(config, source="rcrc", site_id="1444")[0]
    assert loop_id(first) == f"E1_1444_{first.detector_id}"

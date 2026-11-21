from datetime import datetime, timedelta, timezone

import pytest

from jaadah.calibration.e1_output import read_e1_intervals
from jaadah.models.mappings import DetectorMapping

RIYADH = timezone(timedelta(hours=3))
RUN_START = datetime(2026, 9, 1, 6, 45, tzinfo=RIYADH)

DETECTORS = [
    DetectorMapping(source="rcrc", site_id="9999", detector_id=detector_id,
                    intersection_id="INT_001", mapping_status="usable", movement_ids=["MOV_X"],
                    sumo_lane_id="lane_0", sumo_position_m=10.0)
    for detector_id in ("A", "B")
]

# Invented values in SUMO's E1 output format.
OUTPUT = """<?xml version="1.0" encoding="UTF-8"?>
<detector>
    <interval begin="0.00" end="900.00" id="E1_9999_A" nVehContrib="40" flow="160.00" occupancy="3.20" speed="12.00" harmonicMeanSpeed="11.0" length="5.00" nVehEntered="41"/>
    <interval begin="0.00" end="900.00" id="E1_9999_B" nVehContrib="0" flow="0.00" occupancy="0.00" speed="-1.00" harmonicMeanSpeed="-1.00" length="-1.00" nVehEntered="0"/>
    <interval begin="0.00" end="900.00" id="other_loop" nVehContrib="7" flow="28.00" occupancy="1.00" speed="9.00" harmonicMeanSpeed="9.0" length="5.00" nVehEntered="7"/>
    <interval begin="900.00" end="1800.00" id="E1_9999_A" nVehContrib="55" flow="220.00" occupancy="21.75" speed="4.00" harmonicMeanSpeed="3.0" length="5.00" nVehEntered="55"/>
</detector>
"""


@pytest.fixture
def output_file(tmp_path):
    path = tmp_path / "e1_out.xml"
    path.write_text(OUTPUT, encoding="utf-8")
    return path


def test_intervals_are_labelled_by_their_end_in_riyadh_time(output_file):
    intervals = read_e1_intervals(output_file, DETECTORS, RUN_START)
    assert [(i.detector_id, i.interval_end.strftime("%H:%M")) for i in intervals] == [
        ("A", "07:00"), ("B", "07:00"), ("A", "07:15"),
    ]
    assert intervals[0].interval_end.utcoffset() == timedelta(hours=3)


def test_count_and_occupancy_are_read(output_file):
    first, empty, second = read_e1_intervals(output_file, DETECTORS, RUN_START)
    assert (first.vehicle_count, first.occupancy_percent) == (40, 3.2)
    assert (empty.vehicle_count, empty.occupancy_percent) == (0, 0.0)
    assert (second.vehicle_count, second.occupancy_percent) == (55, 21.75)


def test_loops_of_other_detectors_are_ignored(output_file):
    intervals = read_e1_intervals(output_file, DETECTORS[:1], RUN_START)
    assert {i.detector_id for i in intervals} == {"A"}


def test_run_start_must_be_timezone_aware(output_file):
    with pytest.raises(ValueError, match="timezone"):
        read_e1_intervals(output_file, DETECTORS, datetime(2026, 9, 1, 6, 45))

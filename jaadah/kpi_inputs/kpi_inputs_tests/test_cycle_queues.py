"""
Test network: one canonical lane whose section is a_0 (100 m), the
junction lane :m_0 (20 m) that joins it to c_0, and c_0 (30 m), ending at
the stop line: 150 m. Distances below are from the stop line. Cars are
5 m long; FCD rows are 0.4 s apart; the signal cycle is 60 s.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jaadah.kpi_inputs.cycle_queues import (
    CycleQueueError,
    anchored_queue,
    collect_cycle_queues,
    lane_sections,
)
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.signals import SignalProgram
from jaadah.sumo_demand.planner import RunWindow

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
NETWORK_PATH = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
RIYADH = timezone(timedelta(hours=3))
EPOCH = datetime(2026, 10, 20, 7, 45, tzinfo=RIYADH)
WINDOW = RunWindow(epoch=EPOCH, analysis_start=EPOCH + timedelta(seconds=60),
                   analysis_end=EPOCH + timedelta(seconds=120), run_end=EPOCH + timedelta(seconds=180))
PROGRAM = SignalProgram(
    signal_program_id="P", scenario_id="S", control_type="fixed_time", cycle_length_s=60,
    source="baseline_model",
    phases=[{"phase_id": "P1", "sequence_order": 0, "served_movement_ids": ["MOV_A"],
             "green_time_s": 55, "yellow_time_s": 3, "all_red_time_s": 2}],
)


def network(offset=0):
    return f"""<net>
  <edge id="a"><lane id="a_0" index="0" length="100" speed="10"/></edge>
  <edge id=":m" function="internal"><lane id=":m_0" index="0" length="20" speed="10"/></edge>
  <edge id="c"><lane id="c_0" index="0" length="30" speed="10"/></edge>
  <connection from="a" to="c" fromLane="0" toLane="0" via=":m_0"/>
  <connection from=":m" to="c" fromLane="0" toLane="0"/>
  <tlLogic id="tls" type="static" programID="0" offset="{offset}"><phase duration="60" state="G"/></tlLogic>
</net>"""


CONFIG = NetworkMappingConfig.model_validate({
    "schema_version": "2.0", "mapping_version": "test",
    "network": {"version": "test", "path": "test.net.xml", "sha256": "a" * 64},
    "intersection_mapping": {"intersection_id": "INT_001", "sumo_tls_id": "tls"},
    "approach_mappings": [{"approach_id": "APP_A", "intersection_id": "INT_001", "approach_side": "west"}],
    "approach_lanes": [{"lane_id": "LANE_A", "approach_id": "APP_A", "lane_index": 1,
                        "served_movement_ids": ["MOV_A"], "lane_width_m": 3.5}],
    "lane_mappings": [{"lane_id": "LANE_A", "sumo_lane_ids": ["a_0", "c_0"]}],
    "movement_mappings": [{"movement_id": "MOV_A", "intersection_id": "INT_001", "approach_id": "APP_A",
                           "sumo_route_edge_ids": ["a", "c"], "signal_controlled": False}],
})


def place(distance):
    """SUMO lane and pos of a car front at a distance from the stop line."""
    if distance <= 30:
        return "c_0", 30 - distance
    if distance <= 50:
        return ":m_0", 50 - distance
    return "a_0", 150 - distance


def collect(tmp_path, cars, offset=0, until=180.0):
    """cars: {vehicle_id: [(start_s, end_s, distance_m, speed_mps), ...]}, one row every 0.4 s."""
    (tmp_path / "net.xml").write_text(network(offset), encoding="utf-8")
    steps = []
    for number in range(int(round(until / 0.4))):
        t = round(number * 0.4, 1)
        rows = ""
        for vehicle_id, spans in cars.items():
            for start, end, distance, speed in spans:
                if start <= t < end:
                    lane, pos = place(distance)
                    rows += f'<vehicle id="{vehicle_id}" speed="{speed}" pos="{pos}" lane="{lane}"/>'
        steps.append(f'<timestep time="{t}">{rows}</timestep>')
    (tmp_path / "fcd.xml").write_text("<fcd-export>" + "".join(steps) + "</fcd-export>", encoding="utf-8")
    return collect_cycle_queues(CONFIG, tmp_path / "net.xml", PROGRAM, tmp_path / "fcd.xml",
                                run_id="RUN", window=WINDOW, vehicle_length_m=5.0)


def stopped(*distances, start=0.0, end=30.0):
    return {f"V{i}": [(start, end, d, 0.0)] for i, d in enumerate(distances)}


# ============================================================
# SECTIONS
# ============================================================

def test_section_includes_the_junction_lane_between_segments(tmp_path):
    (tmp_path / "net.xml").write_text(network(), encoding="utf-8")
    section = lane_sections(CONFIG, tmp_path / "net.xml")["LANE_A"]

    assert section.length_m == 150
    assert section.to_stop_line_m == {"c_0": 0, ":m_0": 30, "a_0": 50}


def test_study_area_sections():
    """South lanes 1 and 2 include a 32.6 m junction lane."""
    sections = lane_sections(load_network_mappings(MAPPING_PATH), NETWORK_PATH)

    assert {lane: round(s.length_m, 1) for lane, s in sections.items()} == {
        "LANE_E_1": 394.8, "LANE_E_2": 394.8, "LANE_E_3": 394.8, "LANE_E_4": 394.8,
        "LANE_S_1": 118.9, "LANE_S_2": 118.9, "LANE_S_3": 207.2, "LANE_S_4": 207.2,
        "LANE_W_1": 95.0, "LANE_W_2": 95.0, "LANE_W_3": 95.0, "LANE_W_4": 110.8,
        "LANE_N_1": 84.8, "LANE_N_2": 84.8, "LANE_N_3": 84.8, "LANE_N_4": 115.3,
    }


# ============================================================
# ONE MOMENT
# ============================================================

def test_queue_is_anchored_at_the_stop_line():
    """
    8 cars every 7.5 m from 1 m: the last one's back is at 1 + 7 x 7.5 + 5 = 58.5 m.
    A group at 75-95 m is more than 10 m behind it and is not part of the queue.
    """
    fronts = [1 + 7.5 * i for i in range(8)] + [75, 82.5, 90]

    assert anchored_queue(fronts, 150, 5.0) == (58.5, 8, False)


def test_no_queue_when_no_queued_car_is_near_the_stop_line():
    assert anchored_queue([30, 37.5], 150, 5.0) == (0.0, 0, False)


def test_queue_reaching_the_section_start_is_capped_and_flagged():
    """The back of the last car at 152.5 m, beyond the 150 m section."""
    fronts = [1 + 7.5 * i for i in range(21)]

    assert anchored_queue(fronts, 150, 5.0) == (150, 21, True)


def test_queue_ending_within_10_m_of_the_section_start_is_flagged():
    """The back at 143.5 m: a car further back could continue the queue."""
    fronts = [1 + 7.5 * i for i in range(19)] + [138.5]

    assert anchored_queue(fronts, 150, 5.0).reaches_section_end


# ============================================================
# CYCLES
# ============================================================

def test_cars_stopped_at_the_line_form_the_cycle_queue(tmp_path):
    first = collect(tmp_path, stopped(1, 8.5, 16))[0]

    assert (first.lane_id, first.cycle_start, first.cycle_end) == ("LANE_A", EPOCH, EPOCH + timedelta(seconds=60))
    assert (first.max_queue_length_m, first.max_queue_vehicles, first.reaches_section_end) == (21.0, 3, False)


def test_a_car_on_the_junction_lane_is_part_of_the_section(tmp_path):
    """Cars at 1 to 38.5 m: the last two are on the junction lane :m_0."""
    record = collect(tmp_path, stopped(*[1 + 7.5 * i for i in range(6)]))[0]

    assert (record.max_queue_length_m, record.max_queue_vehicles) == (43.5, 6)


def test_a_car_slow_for_less_than_1_s_is_not_queued(tmp_path):
    record = collect(tmp_path, {"V": [(10.0, 10.8, 1, 0.0)]})[0]

    assert record.max_queue_length_m == 0


def test_every_lane_and_whole_cycle_has_a_record(tmp_path):
    """The run is 180 s: three 60 s cycles, the last two without a queue."""
    records = collect(tmp_path, stopped(1))

    assert [r.cycle_start for r in records] == [EPOCH + timedelta(seconds=s) for s in (0, 60, 120)]
    assert [r.max_queue_vehicles for r in records] == [1, 0, 0]


def test_offset_that_is_not_whole_cycles_rejected(tmp_path):
    with pytest.raises(CycleQueueError, match="signal offset \\[30.0\\] is not a whole number of 60 s"):
        collect(tmp_path, {}, offset=30)

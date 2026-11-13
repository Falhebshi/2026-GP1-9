"""
Test network along the route u -> a -> c, ending at the signal stop line:

    u_0 (100 m) | junction :k_0 (10 m) | a_0 (100 m) | junction :m_0 (20 m) | c_0 (30 m)

The canonical lane's section is a_0, :m_0 and c_0: 150 m. The approach's
upstream zone is 240 m, so its path also takes in :k_0 and u_0. Distances
below are from the stop line: c_0 0-30 m, :m_0 30-50 m, a_0 50-150 m,
:k_0 150-160 m, u_0 160-260 m. Cars are 5 m long; FCD rows are 0.4 s
apart; the signal cycle is 60 s.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jaadah.kpi_inputs.cycle_queues import (
    CycleQueueError,
    anchored_queue,
    approach_paths,
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
PATH = [("u_0", 100), (":k_0", 10), ("a_0", 100), (":m_0", 20), ("c_0", 30)]


def network(offset=0):
    return f"""<net>
  <edge id="u"><lane id="u_0" index="0" length="100" speed="10"/></edge>
  <edge id=":k" function="internal"><lane id=":k_0" index="0" length="10" speed="10"/></edge>
  <edge id="a"><lane id="a_0" index="0" length="100" speed="10"/></edge>
  <edge id=":m" function="internal"><lane id=":m_0" index="0" length="20" speed="10"/></edge>
  <edge id="c"><lane id="c_0" index="0" length="30" speed="10"/></edge>
  <edge id="d"><lane id="d_0" index="0" length="50" speed="10"/></edge>
  <connection from="u" to="a" fromLane="0" toLane="0" via=":k_0"/>
  <connection from=":k" to="a" fromLane="0" toLane="0"/>
  <connection from="a" to="c" fromLane="0" toLane="0" via=":m_0"/>
  <connection from=":m" to="c" fromLane="0" toLane="0"/>
  <connection from="c" to="d" fromLane="0" toLane="0" tl="tls" linkIndex="0"/>
  <tlLogic id="tls" type="static" programID="0" offset="{offset}"><phase duration="60" state="G"/></tlLogic>
</net>"""


CONFIG = NetworkMappingConfig.model_validate({
    "schema_version": "2.0", "mapping_version": "test",
    "network": {"version": "test", "path": "test.net.xml", "sha256": "a" * 64},
    "intersection_mapping": {"intersection_id": "INT_001", "sumo_tls_id": "tls"},
    "approach_mappings": [{"approach_id": "APP_A", "intersection_id": "INT_001", "approach_side": "west",
                           "zone_upstream_m": 240, "zone_downstream_m": 20}],
    "approach_lanes": [{"lane_id": "LANE_A", "approach_id": "APP_A", "lane_index": 1,
                        "served_movement_ids": ["MOV_A"], "lane_width_m": 3.5}],
    "lane_mappings": [{"lane_id": "LANE_A", "sumo_lane_ids": ["a_0", "c_0"]}],
    "movement_mappings": [{
        "movement_id": "MOV_A", "intersection_id": "INT_001", "approach_id": "APP_A",
        "sumo_route_edge_ids": ["u", "a", "c", "d"], "signal_controlled": True, "sumo_tls_id": "tls",
        "signal_crossings": [{"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": [0]}],
    }],
    "movement_attributes": [{"movement_id": "MOV_A", "movement_type": "through", "control": "signalized"}],
})


def lane_and_pos(distance):
    """SUMO lane and pos of a car front at a distance from the stop line."""
    remaining = distance
    for lane, length in reversed(PATH):
        if remaining <= length:
            return lane, length - remaining
        remaining -= length
    return PATH[0][0], 0.0


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
                    lane, pos = lane_and_pos(distance)
                    rows += f'<vehicle id="{vehicle_id}" speed="{speed}" pos="{pos}" lane="{lane}"/>'
        steps.append(f'<timestep time="{t}">{rows}</timestep>')
    (tmp_path / "fcd.xml").write_text("<fcd-export>" + "".join(steps) + "</fcd-export>", encoding="utf-8")
    return collect_cycle_queues(CONFIG, tmp_path / "net.xml", PROGRAM, tmp_path / "fcd.xml",
                                run_id="RUN", window=WINDOW, vehicle_length_m=5.0)


def stopped(*distances, start=0.0, end=30.0):
    return {f"V{i}": [(start, end, d, 0.0)] for i, d in enumerate(distances)}


def queue_of(count, first=1.0, spacing=7.5):
    return [first + spacing * i for i in range(count)]


# ============================================================
# SECTIONS AND APPROACH PATHS
# ============================================================

def test_section_includes_the_junction_lane_between_segments(tmp_path):
    (tmp_path / "net.xml").write_text(network(), encoding="utf-8")
    section = lane_sections(CONFIG, tmp_path / "net.xml")["LANE_A"]

    assert section.length_m == 150
    assert section.to_stop_line_m == {"c_0": 0, ":m_0": 30, "a_0": 50}


def test_approach_path_continues_behind_the_section(tmp_path):
    """u_0 ends 160 m and the junction lane :k_0 150 m before the stop line."""
    (tmp_path / "net.xml").write_text(network(), encoding="utf-8")
    path = approach_paths(CONFIG, tmp_path / "net.xml", lane_sections(CONFIG, tmp_path / "net.xml"))["APP_A"]

    assert path.length_m == 240
    assert path.to_stop_line_m == {"c_0": 0, ":m_0": 30, "a_0": 50, ":k_0": 150, "u_0": 160}


def test_study_area_sections():
    """South lanes 1 and 2 include a 32.6 m junction lane."""
    sections = lane_sections(load_network_mappings(MAPPING_PATH), NETWORK_PATH)

    assert {lane: round(s.length_m, 1) for lane, s in sections.items()} == {
        "LANE_E_1": 394.8, "LANE_E_2": 394.8, "LANE_E_3": 394.8, "LANE_E_4": 394.8,
        "LANE_S_1": 118.9, "LANE_S_2": 118.9, "LANE_S_3": 207.2, "LANE_S_4": 207.2,
        "LANE_W_1": 95.0, "LANE_W_2": 95.0, "LANE_W_3": 95.0, "LANE_W_4": 110.8,
        "LANE_N_1": 84.8, "LANE_N_2": 84.8, "LANE_N_3": 84.8, "LANE_N_4": 115.3,
    }


def test_study_area_signal_paths_leave_out_slip_lanes():
    """South: the signal lanes and the shared road behind them, not the bypass lanes."""
    config = load_network_mappings(MAPPING_PATH)
    sections = lane_sections(config, NETWORK_PATH)
    paths = approach_paths(config, NETWORK_PATH, sections)
    south = paths["APP_S"].to_stop_line_m

    assert set(paths) == {
        "APP_E", "APP_N", "APP_S", "APP_W",
        "APP_N/MOV_N_W_SLIP", "APP_S/MOV_S_E_BYPASS", "APP_W/MOV_W_S_SLIP",
    }
    assert {key: p.length_m for key, p in paths.items()} == {
        "APP_E": 388, "APP_W": 450, "APP_N": 500, "APP_S": 500,
        "APP_N/MOV_N_W_SLIP": 500, "APP_S/MOV_S_E_BYPASS": 500, "APP_W/MOV_W_S_SLIP": 450,
    }
    assert set(sections["LANE_S_1"].to_stop_line_m) <= set(south)
    assert not set(sections["LANE_S_3"].to_stop_line_m) & set(south)
    assert not set(sections["LANE_W_4"].to_stop_line_m) & set(paths["APP_W"].to_stop_line_m)
    assert "E3_0" in south


def test_study_area_slip_paths_continue_onto_the_shared_road():
    """
    The bypass path: its own lanes from the bypass end, then the shared
    road behind them, without the signal lanes. The shared road's lanes
    are measured from the bypass end, not from the signal stop line.
    """
    config = load_network_mappings(MAPPING_PATH)
    sections = lane_sections(config, NETWORK_PATH)
    paths = approach_paths(config, NETWORK_PATH, sections)
    bypass = paths["APP_S/MOV_S_E_BYPASS"]

    assert bypass.approach_id == "APP_S"
    assert set(sections["LANE_S_3"].to_stop_line_m) <= set(bypass.to_stop_line_m)
    assert not set(sections["LANE_S_1"].to_stop_line_m) & set(bypass.to_stop_line_m)
    assert "E3_0" in bypass.to_stop_line_m
    assert bypass.to_stop_line_m["E3_0"] != paths["APP_S"].to_stop_line_m["E3_0"]


# ============================================================
# ONE MOMENT
# ============================================================

def test_queue_is_anchored_at_the_stop_line():
    """
    8 cars every 7.5 m from 1 m: the last one's back is at 1 + 7 x 7.5 + 5 = 58.5 m.
    A group at 75-95 m is more than 10 m behind it and is not part of the queue.
    """
    assert anchored_queue(queue_of(8) + [75, 82.5, 90], 150, 5.0) == (58.5, 8, False)


def test_no_queue_when_no_queued_car_is_near_the_stop_line():
    assert anchored_queue([30, 37.5], 150, 5.0) == (0.0, 0, False)


def test_queue_reaching_the_section_start_is_capped_and_flagged():
    """
    21 cars every 7.5 m from 1 m: the 21st car's front is at 151 m, past
    the 150 m section. The queue is the whole section long, and only the
    20 cars within it are counted.
    """
    assert anchored_queue(queue_of(21), 150, 5.0) == (150, 20, True)


def test_count_stops_at_the_boundary_like_the_length():
    """A car whose front is past the boundary is not counted, even when its back is not."""
    queue = anchored_queue(queue_of(20) + [151.0, 158.5], 150, 5.0)

    assert (queue.length_m, queue.vehicles, queue.reaches_section_end) == (150, 20, True)


def test_queue_ending_within_10_m_of_the_section_start_is_flagged():
    """The back at 143.5 m: a car further back could continue the queue."""
    assert anchored_queue(queue_of(19) + [138.5], 150, 5.0).reaches_section_end


# ============================================================
# CYCLES
# ============================================================

def test_cars_stopped_at_the_line_form_the_cycle_queue(tmp_path):
    first = collect(tmp_path, stopped(1, 8.5, 16)).lanes[0]

    assert (first.lane_id, first.cycle_start, first.cycle_end) == ("LANE_A", EPOCH, EPOCH + timedelta(seconds=60))
    assert (first.max_queue_length_m, first.max_queue_vehicles, first.reaches_section_end) == (21.0, 3, False)


def test_a_car_on_the_junction_lane_is_part_of_the_section(tmp_path):
    """Cars at 1 to 38.5 m: the last two are on the junction lane :m_0."""
    record = collect(tmp_path, stopped(*queue_of(6))).lanes[0]

    assert (record.max_queue_length_m, record.max_queue_vehicles) == (43.5, 6)


def test_a_car_slow_for_less_than_1_s_is_not_queued(tmp_path):
    record = collect(tmp_path, {"V": [(10.0, 10.8, 1, 0.0)]}).lanes[0]

    assert record.max_queue_length_m == 0


def test_every_lane_approach_and_whole_cycle_has_a_record(tmp_path):
    """The run is 180 s: three 60 s cycles, the last two without a queue."""
    queues = collect(tmp_path, stopped(1))

    assert [r.cycle_start for r in queues.lanes] == [EPOCH + timedelta(seconds=s) for s in (0, 60, 120)]
    assert [r.max_queue_vehicles for r in queues.lanes] == [1, 0, 0]
    assert [(r.approach_id, r.max_queue_vehicles) for r in queues.approaches] == [
        ("APP_A", 1), ("APP_A", 0), ("APP_A", 0)]


def test_approach_queue_continues_behind_the_lane_section(tmp_path):
    """
    26 cars from 1 m back: the last one's back at 1 + 25 x 7.5 + 5 = 193.5 m, on u_0.
    The lane sees the 20 cars whose fronts are on its section (the 20th at 143.5 m,
    its back at 148.5 m, within 10 m of the section start, so flagged); the
    approach sees the whole 193.5 m.
    """
    queues = collect(tmp_path, stopped(*queue_of(26)))

    lane, approach = queues.lanes[0], queues.approaches[0]
    assert (lane.max_queue_length_m, lane.max_queue_vehicles, lane.reaches_section_end) == (148.5, 20, True)
    assert (approach.max_queue_length_m, approach.max_queue_vehicles, approach.reaches_zone_end) == (193.5, 26, False)


def test_approach_queue_reaching_the_zone_end_is_capped_and_flagged(tmp_path):
    """33 cars: the back at 1 + 32 x 7.5 + 5 = 246 m, beyond the 240 m zone."""
    approach = collect(tmp_path, stopped(*queue_of(33))).approaches[0]

    assert (approach.max_queue_length_m, approach.reaches_zone_end) == (240, True)


def test_offset_that_is_not_whole_cycles_rejected(tmp_path):
    with pytest.raises(CycleQueueError, match="signal offset \\[30.0\\] is not a whole number of 60 s"):
        collect(tmp_path, {}, offset=30)


# ============================================================
# A SLIP LANE ON THE APPROACH
# ============================================================

def slip_network():
    """
    The signal lane a -> c as in network(), plus a slip lane b leaving
    the shared road u through the junction lane :s:

        u 100 m -> :s 10 m -> b 60 m (slip end) -> e
    """
    return network().replace("</net>", """  <edge id=":s" function="internal"><lane id=":s_0" index="0" length="10" speed="10"/></edge>
  <edge id="b"><lane id="b_0" index="0" length="60" speed="10"/></edge>
  <edge id="e"><lane id="e_0" index="0" length="50" speed="10"/></edge>
  <connection from="u" to="b" fromLane="0" toLane="0" via=":s_0"/>
  <connection from=":s" to="b" fromLane="0" toLane="0"/>
  <connection from="b" to="e" fromLane="0" toLane="0"/>
</net>""")


SLIP_CONFIG = NetworkMappingConfig.model_validate({
    **CONFIG.model_dump(mode="json"),
    "approach_lanes": [
        {"lane_id": "LANE_A", "approach_id": "APP_A", "lane_index": 1,
         "served_movement_ids": ["MOV_A"], "lane_width_m": 3.5},
        {"lane_id": "LANE_B", "approach_id": "APP_A", "lane_index": 2,
         "served_movement_ids": ["MOV_B"], "lane_width_m": 3.5},
    ],
    "lane_mappings": [{"lane_id": "LANE_A", "sumo_lane_ids": ["a_0", "c_0"]},
                      {"lane_id": "LANE_B", "sumo_lane_ids": ["b_0"]}],
    "movement_mappings": CONFIG.model_dump(mode="json")["movement_mappings"] + [{
        "movement_id": "MOV_B", "intersection_id": "INT_001", "approach_id": "APP_A",
        "sumo_route_edge_ids": ["u", "b", "e"], "signal_controlled": False,
    }],
    "movement_attributes": [
        {"movement_id": "MOV_A", "movement_type": "through", "control": "signalized"},
        {"movement_id": "MOV_B", "movement_type": "right", "control": "uncontrolled"},
    ],
})

SLIP_PATH = [("u_0", 100), (":s_0", 10), ("b_0", 60)]


def slip_position(distance):
    """SUMO lane and pos of a car front at a distance from the slip end."""
    remaining = distance
    for lane, length in reversed(SLIP_PATH):
        if remaining <= length:
            return lane, length - remaining
        remaining -= length
    return SLIP_PATH[0][0], 0.0


def test_slip_queue_that_fills_its_lane_continues_onto_the_shared_road(tmp_path):
    """
    15 cars stopped every 7.5 m from 1 m before the slip end: the last
    back at 1 + 14 x 7.5 + 5 = 111 m, 41 m back on the shared road u.
    The slip lane sees only the cars on its 60 m section (the last back
    at 58.5 m) and is flagged near its end; the approach queue follows
    the queue onto the shared road to 111 m, inside the 240 m zone, so
    it is measured.
    """
    (tmp_path / "net.xml").write_text(slip_network(), encoding="utf-8")
    rows = ""
    for i, distance in enumerate(queue_of(15)):
        lane, pos = slip_position(distance)
        rows += f'<vehicle id="V{i}" speed="0" pos="{pos}" lane="{lane}"/>'
    steps = "".join(f'<timestep time="{round(n * 0.4, 1)}">{rows if n * 0.4 < 30 else ""}</timestep>'
                    for n in range(450))
    (tmp_path / "fcd.xml").write_text(f"<fcd-export>{steps}</fcd-export>", encoding="utf-8")

    queues = collect_cycle_queues(SLIP_CONFIG, tmp_path / "net.xml", PROGRAM, tmp_path / "fcd.xml",
                                  run_id="RUN", window=WINDOW, vehicle_length_m=5.0)
    slip_lane = next(q for q in queues.lanes if q.lane_id == "LANE_B" and q.cycle_start == EPOCH)
    approach = next(q for q in queues.approaches if q.cycle_start == EPOCH)

    assert (slip_lane.max_queue_length_m, slip_lane.reaches_section_end) == (58.5, True)
    assert approach.approach_id == "APP_A"
    assert (approach.max_queue_length_m, approach.max_queue_vehicles, approach.reaches_zone_end) == (111, 15, False)

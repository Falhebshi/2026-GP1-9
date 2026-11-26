"""
One live segment, and two chained segments against one uninterrupted
run, with SUMO on the study network (simulation/live/segments.py).
Skipped when SUMO is not installed.
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from jaadah.mapping.loader import load_network_mappings
from simulation.live.chain import segment_route_xml
from simulation.live.outputs import combine_fcd, combine_tls_states, combine_tripinfo
from simulation.live.segments import (
    SegmentError,
    check_times,
    run_segment,
    segment_files,
    sumo_command,
)

ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "data" / "processed" / "road_network" / "jaadah_study_area.net.xml"
MAPPING = ROOT / "data" / "processed" / "road_network" / "network_mappings.json"
needs_sumo = pytest.mark.skipif(shutil.which("sumo") is None, reason="SUMO is not installed")


def routes() -> bytes:
    """Three movements, a vehicle every 6 s on each for 4 minutes."""
    mapping = load_network_mappings(MAPPING, network_path=NETWORK)
    edges = {m.movement_id: " ".join(m.sumo_route_edge_ids) for m in mapping.movement_mappings}
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", length="5.0", minGap="2.5",
                  accel="2.6", decel="4.5", sigma="0.5", speedDev="0.1")
    for movement in ("MOV_E_W", "MOV_N_E", "MOV_S_W"):
        ET.SubElement(root, "route", id=movement, edges=edges[movement])
    departures = sorted(
        (t + offset, movement)
        for offset, movement in enumerate(("MOV_E_W", "MOV_N_E", "MOV_S_W"))
        for t in range(0, 240, 6)
    )
    for number, (t, movement) in enumerate(departures):
        ET.SubElement(root, "vehicle", id=f"{movement}_{number}", type="car", route=movement,
                      depart=f"{t:.2f}", departLane="best", departSpeed="max")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def test_times_must_be_on_the_step_grid():
    check_times(0, 840, 0.4)

    with pytest.raises(SegmentError, match="not a whole number of 0.4 s steps"):
        check_times(0, 840.1, 0.4)
    with pytest.raises(SegmentError, match="must run forward"):
        check_times(840, 840, 0.4)


def test_the_command_saves_the_state_and_its_random_numbers_at_the_end(tmp_path):
    files = segment_files(tmp_path / "s", 840, 1740)
    command = sumo_command(tmp_path / "s.sumocfg", files, sumo_bin="sumo", seed=42,
                           step_length_s=0.4, load_state=tmp_path / "prev.xml.gz")

    def value(option):
        return command[command.index(option) + 1]

    assert value("--begin") == "840"
    assert value("--end") == "1740.4"  # one step past the state time, or SUMO saves no state
    assert value("--save-state.times") == "1740"
    assert value("--save-state.rng") == "true"
    assert value("--save-state.precision") == "8"
    assert value("--load-state") == str(tmp_path / "prev.xml.gz")
    assert value("--random") == "false"


def test_an_existing_folder_is_never_reused(tmp_path):
    (tmp_path / "s").mkdir()

    with pytest.raises(SegmentError, match="already exists"):
        run_segment(tmp_path / "s", b"<routes/>", begin_s=0, end_s=8, network_path=NETWORK,
                    seed=42, step_length_s=0.4, load_state=None)


def test_a_later_segment_needs_a_saved_state(tmp_path):
    with pytest.raises(SegmentError, match="only a segment that starts at 0"):
        run_segment(tmp_path / "s", b"<routes/>", begin_s=8, end_s=16, network_path=NETWORK,
                    seed=42, step_length_s=0.4, load_state=None)
    with pytest.raises(SegmentError, match="saved state not found"):
        run_segment(tmp_path / "t", b"<routes/>", begin_s=8, end_s=16, network_path=NETWORK,
                    seed=42, step_length_s=0.4, load_state=tmp_path / "missing.xml.gz")


def timesteps(path):
    return {
        step.get("time"): sorted((v.get("id"), v.get("x"), v.get("y"), v.get("speed")) for v in step)
        for step in ET.parse(path).getroot()
    }


@needs_sumo
def test_two_chained_segments_continue_one_run(tmp_path):
    """
    0-120 s, then 120-300 s from the saved state, against one run 0-300 s:
    the same timesteps, no repeat at the boundary, the same vehicles, and
    every vehicle position identical up to the boundary.
    """
    xml = routes()
    whole = run_segment(tmp_path / "whole", segment_route_xml(xml, 0, 300), begin_s=0, end_s=300,
                        network_path=NETWORK, seed=42, step_length_s=0.4, load_state=None)
    first = run_segment(tmp_path / "a", segment_route_xml(xml, 0, 120), begin_s=0, end_s=120,
                        network_path=NETWORK, seed=42, step_length_s=0.4, load_state=None)
    second = run_segment(tmp_path / "b", segment_route_xml(xml, 120, 300), begin_s=120, end_s=300,
                         network_path=NETWORK, seed=42, step_length_s=0.4, load_state=first.state_file)

    assert first.state_file.is_file() and second.state_file.is_file()
    combine_fcd([first.fcd_file, second.fcd_file], tmp_path / "fcd.xml")
    combine_tripinfo([first.tripinfo_file, second.tripinfo_file], tmp_path / "trip.xml")
    combine_tls_states([first.tls_states_file, second.tls_states_file], [0, 120], tmp_path / "tls.xml")

    chained, uninterrupted = timesteps(tmp_path / "fcd.xml"), timesteps(whole.fcd_file)
    assert list(chained) == list(uninterrupted)
    assert all(chained[t] == uninterrupted[t] for t in uninterrupted if float(t) <= 120)

    trips = {t.get("id") for t in ET.parse(tmp_path / "trip.xml").getroot()}
    assert trips == {t.get("id") for t in ET.parse(whole.tripinfo_file).getroot()}

    switches = [float(r.get("time")) for r in ET.parse(tmp_path / "tls.xml").getroot()]
    assert switches == sorted(set(switches))

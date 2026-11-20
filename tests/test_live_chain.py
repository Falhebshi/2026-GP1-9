"""
The timeline and record of a live chain, and the joining of segment
outputs (simulation/live/chain.py, simulation/live/outputs.py).
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import pytest

from simulation.live.chain import (
    LAG_S,
    RIYADH,
    ChainError,
    ChainRecord,
    EstimatedInterval,
    SegmentRecord,
    chain_day,
    check_lag,
    day_epoch,
    load_record,
    run_id_of,
    save_record,
    segment_end_s,
    segment_route_xml,
)
from simulation.live.outputs import (
    SegmentOutputError,
    combine_fcd,
    combine_tls_states,
    combine_tripinfo,
)

EPOCH = datetime(2026, 8, 19, 2, 45, tzinfo=RIYADH)


# ============================================================
# TIMES
# ============================================================

def test_a_chain_day_runs_from_03_00_to_03_00():
    assert chain_day(datetime(2026, 8, 20, 1, 0, tzinfo=RIYADH)) == date(2026, 8, 19)
    assert chain_day(datetime(2026, 8, 20, 2, 59, tzinfo=RIYADH)) == date(2026, 8, 19)
    assert chain_day(datetime(2026, 8, 20, 3, 0, tzinfo=RIYADH)) == date(2026, 8, 20)


def test_a_day_chain_starts_its_warm_up_at_02_45():
    assert day_epoch(date(2026, 8, 19)) == EPOCH


def test_run_id_names_the_start_and_the_seed():
    assert run_id_of(EPOCH, 42) == "RUN_LIVE_20260819T0245_S42"


def test_a_segment_stops_one_lag_before_its_interval_ends():
    """The interval 03:00-03:15 ends 1800 s after 02:45."""
    assert segment_end_s(EPOCH, EPOCH + timedelta(minutes=30)) == 1800 - LAG_S


def test_the_lag_must_cover_the_longest_departure_shift():
    check_lag({"MOV_A": 57.3, "MOV_B": 12.0})

    with pytest.raises(ChainError, match="not below the 60 s lag"):
        check_lag({"MOV_A": 60.0})


ROUTES = b"""<?xml version='1.0' encoding='utf-8'?>
<routes>
    <vType id="car"/>
    <route id="MOV_A" edges="a b"/>
    <vehicle id="v0" type="car" route="MOV_A" depart="0.00"/>
    <vehicle id="v1" type="car" route="MOV_A" depart="839.60"/>
    <vehicle id="v2" type="car" route="MOV_A" depart="840.00"/>
    <vehicle id="v3" type="car" route="MOV_A" depart="840.40"/>
    <vehicle id="v4" type="car" route="MOV_A" depart="1740.00"/>
    <vehicle id="v5" type="car" route="MOV_A" depart="1740.40"/>
</routes>
"""


def vehicles(xml: bytes) -> list[str]:
    return [element.get("id") for element in ET.fromstring(xml) if element.tag == "vehicle"]


def test_the_first_segment_inserts_its_departures_from_0_up_to_its_end():
    assert vehicles(segment_route_xml(ROUTES, 0, 840)) == ["v0", "v1", "v2"]


def test_a_later_segment_inserts_the_departures_after_its_begin_up_to_its_end():
    """v2 departs at 840 s: the segment ending at 840 s inserts it, not the next one."""
    assert vehicles(segment_route_xml(ROUTES, 840, 1740)) == ["v3", "v4"]


def test_a_segment_keeps_the_vehicle_type_and_routes():
    xml = segment_route_xml(ROUTES, 840, 1740)

    assert b'<vType id="car"' in xml and b'<route id="MOV_A"' in xml


# ============================================================
# THE RECORD
# ============================================================

def make_record() -> ChainRecord:
    return ChainRecord(
        run_id="RUN_LIVE_20260819T0245_S42", scenario_id="SCN_LIVE_20260819T0245",
        epoch=EPOCH.isoformat(), seed=42, step_length_s=0.4, sumo_version="1.27.1",
        network_version="test", mapping_version="test", started_at=EPOCH.isoformat(),
    )


def test_a_new_chain_simulates_its_warm_up_first():
    record = make_record()

    assert record.last_interval_end is None
    assert record.last_end_s == 0
    assert record.next_interval_end() == EPOCH + timedelta(minutes=15)


def test_the_record_is_saved_and_read_back(tmp_path):
    record = make_record()
    record.segments.append(SegmentRecord(0, (EPOCH + timedelta(minutes=15)).isoformat(), 0, 840, "segments/000_0300"))
    record.estimated_intervals.append(EstimatedInterval(
        EPOCH.isoformat(), (EPOCH + timedelta(minutes=15)).isoformat(), ["APP_E"], ["historical_average"]))

    save_record(record, tmp_path)
    loaded = load_record(tmp_path)

    assert loaded == record
    assert loaded.next_interval_end() == EPOCH + timedelta(minutes=30)
    assert not (tmp_path / "chain.json.tmp").exists()


def test_no_record_gives_none(tmp_path):
    assert load_record(tmp_path) is None


def test_a_record_of_another_format_is_refused(tmp_path):
    (tmp_path / "chain.json").write_text('{"format_version": 99}', encoding="utf-8")

    with pytest.raises(ChainError, match="format version 99"):
        load_record(tmp_path)


# ============================================================
# JOINING SEGMENT OUTPUTS
# ============================================================

def fcd(times, vehicle="v"):
    steps = "".join(
        f'    <timestep time="{t:.3f}">\n        <vehicle id="{vehicle}" x="{t}"/>\n    </timestep>\n'
        for t in times
    )
    return f'<?xml version="1.0"?>\n<!-- generated -->\n<fcd-export xmlns:xsi="x">\n{steps}</fcd-export>\n'


def test_fcd_keeps_the_earlier_copy_of_the_boundary_timestep(tmp_path):
    """The second segment repeats 0.8 s, the first segment's last timestep."""
    (tmp_path / "a.xml").write_text(fcd([0.0, 0.4, 0.8], "first"), encoding="utf-8")
    (tmp_path / "b.xml").write_text(fcd([0.8, 1.2]), encoding="utf-8")

    combine_fcd([tmp_path / "a.xml", tmp_path / "b.xml"], tmp_path / "out.xml")

    steps = ET.parse(tmp_path / "out.xml").getroot()
    assert [step.get("time") for step in steps] == ["0.000", "0.400", "0.800", "1.200"]
    assert steps[2][0].get("id") == "first"


def test_fcd_keeps_an_empty_timestep(tmp_path):
    (tmp_path / "a.xml").write_text(
        '<fcd-export>\n    <timestep time="0.000"/>\n    <timestep time="0.400">\n'
        '        <vehicle id="v"/>\n    </timestep>\n</fcd-export>\n', encoding="utf-8")

    combine_fcd([tmp_path / "a.xml"], tmp_path / "out.xml")

    assert [s.get("time") for s in ET.parse(tmp_path / "out.xml").getroot()] == ["0.000", "0.400"]


def test_an_unfinished_fcd_file_is_refused(tmp_path):
    (tmp_path / "a.xml").write_text('<fcd-export>\n    <timestep time="0.000">\n', encoding="utf-8")

    with pytest.raises(SegmentOutputError, match="ends before its root element closes"):
        combine_fcd([tmp_path / "a.xml"], tmp_path / "out.xml")


def test_signal_records_at_a_later_segments_begin_are_dropped(tmp_path):
    """The second segment, from 20 s, first writes the state it loaded."""
    record = '    <tlsState time="{}" id="J" programID="0" phase="{}" state="{}"/>\n'
    (tmp_path / "a.xml").write_text(
        "<tlsStates>\n" + record.format("0.000", 0, "G") + record.format("20.000", 1, "y") + "</tlsStates>\n",
        encoding="utf-8")
    (tmp_path / "b.xml").write_text(
        "<tlsStates>\n" + record.format("20.000", 1, "y") + record.format("23.200", 2, "r") + "</tlsStates>\n",
        encoding="utf-8")

    combine_tls_states([tmp_path / "a.xml", tmp_path / "b.xml"], [0, 20], tmp_path / "out.xml")

    assert [(r.get("time"), r.get("phase")) for r in ET.parse(tmp_path / "out.xml").getroot()] == [
        ("0.000", "0"), ("20.000", "1"), ("23.200", "2")]


def test_tripinfo_keeps_each_vehicles_newest_record(tmp_path):
    """v1 was still driving at the end of the first segment and finished in the second."""
    (tmp_path / "a.xml").write_text(
        '<tripinfos>\n<tripinfo id="v0" arrival="10.0"/>\n<tripinfo id="v1" arrival="-1" vaporized="end"/>\n</tripinfos>',
        encoding="utf-8")
    (tmp_path / "b.xml").write_text('<tripinfos>\n<tripinfo id="v1" arrival="31.2"/>\n</tripinfos>', encoding="utf-8")

    combine_tripinfo([tmp_path / "a.xml", tmp_path / "b.xml"], tmp_path / "out.xml")

    trips = {t.get("id"): t.attrib for t in ET.parse(tmp_path / "out.xml").getroot()}
    assert trips == {"v0": {"id": "v0", "arrival": "10.0"}, "v1": {"id": "v1", "arrival": "31.2"}}


def test_a_record_saved_before_the_warm_up_setting_loads_with_15_minutes(tmp_path):
    import json
    from simulation.live.chain import ChainRecord, load_record, save_record

    record = ChainRecord(
        run_id="RUN_LIVE_20260806T1145_S42", scenario_id="SCN_LIVE_20260806T1145",
        epoch="2026-08-06T11:45:00+03:00", seed=42, step_length_s=0.4, sumo_version="1.27.1",
        network_version="test", mapping_version="test", started_at="2026-08-06T12:00:00+03:00",
    )
    path = save_record(record, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["warmup_s"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_record(tmp_path)
    assert loaded.warmup_s == 900
    assert loaded.analysis_start_time.isoformat() == "2026-08-06T12:00:00+03:00"

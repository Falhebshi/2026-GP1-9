"""
Test network, along the route u -> a -> b (odometer from the start of u):

    u 0-50 m | junction :k 50-52 m | a 52-152 m | junction :j 152-162 m | b 162-262 m

The stop line is the end of a (152 m) and the junction exit the start of
b (162 m). With a 50 m upstream and 20 m downstream zone, the zone runs
from 102 m to 182 m: 80 m. Every lane's speed limit is 10 m/s, except in
the free-flow tests. FCD rows are 1 s apart.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from jaadah.kpi_inputs.vehicle_passages import (
    Row,
    VehiclePassageError,
    collect_vehicle_passages,
    free_flow_time,
    movement_zones,
    time_at,
)
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.sumo_demand.planner import RunWindow

RIYADH = timezone(timedelta(hours=3))
EPOCH = datetime(2026, 10, 20, 7, 45, tzinfo=RIYADH)
PATH = [("u_0", 50), (":k_0", 2), ("a_0", 100), (":j_0", 10), ("b_0", 100)]

NETWORK = """<net>
  <edge id="u"><lane id="u_0" index="0" length="50" speed="10"/></edge>
  <edge id=":k" function="internal"><lane id=":k_0" index="0" length="2" speed="10"/></edge>
  <edge id="a"><lane id="a_0" index="0" length="100" speed="10"/></edge>
  <edge id=":j" function="internal"><lane id=":j_0" index="0" length="10" speed="10"/></edge>
  <edge id="b"><lane id="b_0" index="0" length="100" speed="10"/></edge>
  <connection from="u" to="a" fromLane="0" toLane="0" via=":k_0"/>
  <connection from=":k" to="a" fromLane="0" toLane="0"/>
  <connection from="a" to="b" fromLane="0" toLane="0" via=":j_0"/>
  <connection from=":j" to="b" fromLane="0" toLane="0"/>
</net>"""


# ============================================================
# HELPERS
# ============================================================

def place(odometer):
    """Lane and position at an odometer value along PATH."""
    start = 0.0
    for lane, length in PATH:
        if odometer < start + length or lane == PATH[-1][0]:
            return lane, odometer - start
        start += length


def rows(points):
    """FCD rows from (time, odometer, speed) points."""
    return [Row(t, *place(s), v, s) for t, s, v in points]


def steady(until, start=0):
    """Driving at 10 m/s from odometer 0, one row per second."""
    return [(t, 10.0 * t, 10.0) for t in range(start, until + 1)]


def config_data(upstream=50, downstream=20):
    return {
        "schema_version": "2.0", "mapping_version": "test",
        "network": {"version": "test", "path": "test.net.xml", "sha256": "a" * 64},
        "intersection_mapping": {"intersection_id": "INT_001"},
        "approach_mappings": [{"approach_id": "APP_A", "intersection_id": "INT_001",
                               "approach_side": "west", "zone_upstream_m": upstream,
                               "zone_downstream_m": downstream}],
        "approach_lanes": [{"lane_id": "LANE_A", "approach_id": "APP_A", "lane_index": 1,
                            "served_movement_ids": ["MOV_A"], "lane_width_m": 3.5}],
        "lane_mappings": [{"lane_id": "LANE_A", "sumo_lane_ids": ["a_0"]}],
        "movement_mappings": [
            {"movement_id": "MOV_A", "intersection_id": "INT_001", "approach_id": "APP_A",
             "sumo_route_edge_ids": ["u", "a", "b"], "signal_controlled": False},
            {"movement_id": "MOV_RAMP", "intersection_id": "INT_001", "approach_id": "APP_A",
             "sumo_route_edge_ids": ["u", "a", "b"], "signal_controlled": False},
        ],
        "movement_attributes": [
            {"movement_id": "MOV_A", "movement_type": "through", "control": "uncontrolled"}],
    }


def collect(tmp_path, traces, *, factors=None, movements=None, **zone):
    """traces: {vehicle_id: [(time, odometer, speed), ...]}."""
    (tmp_path / "net.xml").write_text(NETWORK, encoding="utf-8")
    fcd = {}
    for vehicle_id, points in traces.items():
        for t, s, v in points:
            fcd.setdefault(t, []).append((vehicle_id, *place(s), v, s))
    (tmp_path / "fcd.xml").write_text("<fcd-export>" + "".join(
        f'<timestep time="{t}">' + "".join(
            f'<vehicle id="{i}" speed="{v}" pos="{p}" lane="{l}" odometer="{s}"/>'
            for i, l, p, v, s in vehicles) + "</timestep>"
        for t, vehicles in sorted(fcd.items())) + "</fcd-export>", encoding="utf-8")
    factors = factors or {}
    (tmp_path / "trip.xml").write_text("<tripinfos>" + "".join(
        f'<tripinfo id="{i}" speedFactor="{factors.get(i, 1.0)}"/>' for i in traces)
        + "</tripinfos>", encoding="utf-8")
    movements = movements or {}
    (tmp_path / "manifest.json").write_text(json.dumps({"departures": [
        {"vehicle_id": i, "demand_id": f"DEM_{i}", "depart_s": 0} for i in traces]}))
    (tmp_path / "demand.json").write_text(json.dumps([
        {"demand_id": f"DEM_{i}", "movement_id": movements.get(i, "MOV_A")} for i in traces]))

    window = RunWindow(epoch=EPOCH, analysis_start=EPOCH + timedelta(minutes=15),
                       analysis_end=EPOCH + timedelta(minutes=75),
                       run_end=EPOCH + timedelta(minutes=90))
    return collect_vehicle_passages(
        NetworkMappingConfig.model_validate(config_data(**zone)), tmp_path / "net.xml",
        run_id="RUN_TEST", window=window, fcd_path=tmp_path / "fcd.xml",
        tripinfo_path=tmp_path / "trip.xml", manifest_path=tmp_path / "manifest.json",
        demand_path=tmp_path / "demand.json", fcd_period_s=1.0,
    )


def at(seconds):
    return EPOCH + timedelta(seconds=seconds)


# ============================================================
# CROSSING TIMES AND FREE-FLOW TIME
# ============================================================

def test_crossing_time_is_interpolated():
    """394 m before the stop line at 10.0 s and 384 m at 10.4 s: the 388 m point at 10.24 s."""
    trace = [Row(10.0, "x_0", 0, 25, 6.0), Row(10.4, "x_0", 10, 25, 16.0)]

    assert time_at(trace, 12.0) == pytest.approx(10.24)


def test_crossing_time_is_none_when_never_reached():
    assert time_at(rows(steady(3)), 100.0) is None


def test_free_flow_uses_each_lanes_own_speed_and_the_speed_factor():
    """80 m: 50 m of a at 10 m/s, 10 m of :j at 5 m/s, 20 m of b at 10 m/s."""
    speeds = {"u_0": 10, ":k_0": 10, "a_0": 10, ":j_0": 5, "b_0": 10}
    lengths = dict(PATH)
    trace = rows(steady(26))

    assert free_flow_time(trace, 102, 182, lengths, speeds, 1.0) == pytest.approx(5 + 2 + 2)
    assert free_flow_time(trace, 102, 182, lengths, speeds, 1.25) == pytest.approx(9 / 1.25)


# ============================================================
# RECORDS
# ============================================================

def test_zone_of_the_test_network(tmp_path):
    (tmp_path / "net.xml").write_text(NETWORK, encoding="utf-8")
    zone = movement_zones(NetworkMappingConfig.model_validate(config_data()), tmp_path / "net.xml")["MOV_A"]

    assert (zone.stop_edge, zone.exit_edge) == ("a", "b")
    assert zone.to_stop_line_m == {"a": 0.0, "u": 102.0}


def test_free_flowing_vehicle(tmp_path):
    """At 10 m/s: zone entry 102 m at 10.2 s, stop line 152 m at 15.2 s, exit 182 m at 18.2 s."""
    result = collect(tmp_path, {"V": steady(26)})
    record = result.records[0]

    assert (record.zone_entry_time, record.stop_line_time, record.zone_exit_time) == (
        at(10.2), at(15.2), at(18.2))
    assert record.zone_distance_m == pytest.approx(80)
    assert record.free_flow_travel_time_s == pytest.approx(8.0)
    assert record.time_loss_s == pytest.approx(0)
    assert record.halted_time_s == 0
    assert result.incomplete == []


def test_halted_vehicle(tmp_path):
    """Stands at 140 m for the rows at 15, 16 and 17 s: 3 s stopped and 3 s lost."""
    points = steady(14) + [(15, 140, 0), (16, 140, 0), (17, 140, 0)]
    points += [(t, 140 + 10.0 * (t - 17), 10.0) for t in range(18, 30)]
    record = collect(tmp_path, {"W": points}).records[0]

    assert (record.stop_line_time, record.zone_exit_time) == (at(18.2), at(21.2))
    assert record.time_loss_s == pytest.approx(3.0)
    assert record.halted_time_s == 3.0


def test_movement_comes_from_the_manifest_not_the_vehicle_id(tmp_path):
    result = collect(tmp_path, {"MOV_RAMP__001": steady(26)}, movements={"MOV_RAMP__001": "MOV_A"})

    assert result.records[0].movement_id == "MOV_A"


def test_vehicles_of_movements_without_attributes_are_ignored(tmp_path):
    result = collect(tmp_path, {"R": steady(26)}, movements={"R": "MOV_RAMP"})

    assert result == ([], [])


def test_vehicle_that_never_reached_its_zone_gives_no_record(tmp_path):
    assert collect(tmp_path, {"Z": steady(5)}) == ([], [])


# ============================================================
# INCOMPLETE PASSAGES
# ============================================================

def test_vehicle_past_the_stop_line_at_run_end_is_incomplete_and_served(tmp_path):
    """Last seen at 170 m, 12 m short of the zone exit."""
    result = collect(tmp_path, {"X": steady(17)})
    passage = result.incomplete[0]

    assert result.records == []
    assert (passage.zone_entry_time, passage.stop_line_time, passage.last_seen_time) == (
        at(10.2), at(15.2), at(17))
    assert passage.crossed_stop_line


def test_vehicle_still_upstream_at_run_end_is_incomplete(tmp_path):
    """
    Last seen on u at 30 m, before reaching the stop-line edge: its stop line is
    placed at 30 + (50 - 30) + 102 = 152 m. With a 140 m upstream zone it entered
    at 12 m, at 1.2 s.
    """
    passage = collect(tmp_path, {"Y": steady(3)}, upstream=140).incomplete[0]

    assert (passage.zone_entry_time, passage.stop_line_time, passage.last_seen_time) == (
        at(1.2), None, at(3))


# ============================================================
# ROUNDING AND ERRORS
# ============================================================

def test_small_negative_time_loss_is_rounding_and_recorded_as_zero(tmp_path):
    """Speed factor 0.98: free-flow 8.16 s against 8 s in the zone, 0.16 s below zero."""
    record = collect(tmp_path, {"V": steady(26)}, factors={"V": 0.98}).records[0]

    assert record.time_loss_s == 0


def test_large_negative_time_loss_is_an_error(tmp_path):
    """Speed factor 0.5: free-flow 16 s against 8 s in the zone."""
    with pytest.raises(VehiclePassageError, match="time loss -8.00 s is below -1.0 s"):
        collect(tmp_path, {"V": steady(26)}, factors={"V": 0.5})


def test_approach_without_zone_is_an_error(tmp_path):
    data = config_data()
    data["approach_mappings"][0].update(zone_upstream_m=None, zone_downstream_m=None)
    (tmp_path / "net.xml").write_text(NETWORK, encoding="utf-8")

    with pytest.raises(VehiclePassageError, match="MOV_A: its approach has no measurement zone"):
        movement_zones(NetworkMappingConfig.model_validate(data), tmp_path / "net.xml")

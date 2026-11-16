import json

import pytest

from jaadah.network_congestion.segments import (
    build_segments,
    directions,
    fill_defaults,
    parse_lanes,
    parse_speed,
    read_osm,
    road_class_of,
    split_way,
)

BOX = (46.0, 24.0, 47.0, 25.0)


def node(node_id, lon, lat, signal=False):
    """One OSM point, optionally a traffic signal."""

    element = {"type": "node", "id": node_id, "lon": lon, "lat": lat}

    if signal:
        element["tags"] = {"highway": "traffic_signals"}

    return element


def way(way_id, node_ids, **tags):
    """One OSM road."""

    return {"type": "way", "id": way_id, "nodes": node_ids, "tags": tags}


@pytest.fixture
def cross():
    """
    Two roads crossing at point 3: a two-way primary road 1-2-3-4-5
    with a signal at point 4, and a one-way secondary road 6-3-7.
    """

    nodes = {
        1: node(1, 46.50, 24.50),
        2: node(2, 46.51, 24.50),
        3: node(3, 46.52, 24.50),
        4: node(4, 46.53, 24.50, signal=True),
        5: node(5, 46.54, 24.50),
        6: node(6, 46.52, 24.49),
        7: node(7, 46.52, 24.51),
    }
    ways = [
        way(10, [1, 2, 3, 4, 5], highway="primary", lanes="4"),
        way(20, [6, 3, 7], highway="secondary", oneway="yes"),
    ]

    return ways, nodes


def test_lanes_and_speed_are_read_from_tags():
    assert parse_lanes("3") == 3
    assert parse_lanes("3;2") == 3
    assert parse_lanes("0") is None
    assert parse_lanes(None) is None
    assert parse_speed("80") == 80
    assert parse_speed("50 mph") == pytest.approx(80.47, abs=0.01)
    assert parse_speed("none") is None


def test_directions_follow_oneway_motorway_and_roundabout_rules():
    assert directions({"oneway": "yes"}) == ["forward"]
    assert directions({"oneway": "-1"}) == ["backward"]
    assert directions({"highway": "motorway"}) == ["forward"]
    assert directions({"highway": "primary"}) == ["forward", "backward"]
    assert directions(
        {"highway": "primary", "junction": "roundabout"}
    ) == ["forward"]
    assert directions(
        {"highway": "primary", "junction": "roundabout", "oneway": "no"}
    ) == ["forward", "backward"]


def test_road_is_cut_at_cut_points_only():
    assert split_way([1, 2, 3, 4, 5], {3, 4}) == [[1, 2, 3], [3, 4], [4, 5]]
    assert split_way([1, 2, 3], {1, 3}) == [[1, 2, 3]]


def test_roads_are_cut_at_intersections_and_signals(cross):
    ways, nodes = cross

    segments, mappings = build_segments(ways, nodes, box=BOX)

    # primary: 3 pieces x 2 directions; secondary: 2 pieces x 1 direction
    assert len(segments) == 8
    assert [m["segment_id"] for m in mappings] == [
        s["segment_id"] for s in segments
    ]
    assert segments[0]["segment_id"] == "SEG_00001"


def test_two_way_road_halves_its_lanes(cross):
    ways, nodes = cross

    segments, _ = build_segments(ways, nodes, box=BOX)

    primary = [s for s in segments if s["road_class"] == "primary"]
    assert {s["lane_count"] for s in primary} == {2}


def test_signal_at_end_follows_driving_direction(cross):
    ways, nodes = cross

    segments, mappings = build_segments(ways, nodes, box=BOX)

    by_ends = {
        (m["from_node_id"], m["to_node_id"]): s
        for s, m in zip(segments, mappings)
    }
    assert by_ends[(3, 4)]["signal_at_end"] is True
    assert by_ends[(4, 3)]["signal_at_end"] is False


def test_segments_outside_the_box_are_dropped(cross):
    ways, nodes = cross

    segments, _ = build_segments(ways, nodes, box=(40.0, 20.0, 41.0, 21.0))

    assert segments == []


def test_untagged_values_take_the_class_median(cross):
    ways, nodes = cross
    nodes[8] = node(8, 46.53, 24.49)
    nodes[9] = node(9, 46.53, 24.51)
    # a tagged secondary road, so the untagged one is filled from it
    ways[1]["tags"]["maxspeed"] = "70"
    ways.append(
        way(30, [8, 9], highway="secondary", oneway="yes", lanes="2",
            maxspeed="50")
    )
    ways[0]["tags"]["maxspeed"] = "80"

    segments, _ = build_segments(ways, nodes, box=BOX)
    counts = fill_defaults(segments)

    secondary = [s for s in segments if s["road_class"] == "secondary"]
    # way 20 has no lanes: it takes the median of the tagged ones (2)
    assert all(s["lane_count"] == 2 for s in secondary)
    assert {s["free_flow_speed_kmh"] for s in secondary} == {70, 50}
    assert counts["lanes_filled"] == 2
    assert counts["speed_filled"] == 0


def test_class_with_no_tagged_speed_is_reported(cross):
    ways, nodes = cross

    segments, _ = build_segments(ways, nodes, box=BOX)

    with pytest.raises(ValueError, match="no primary road .* speed limit"):
        fill_defaults(segments)


def test_missing_points_are_reported(tmp_path):
    path = tmp_path / "roads.json"
    path.write_text(
        json.dumps(
            {"elements": [way(1, [1, 2], highway="primary")]},
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="2 road points are missing"):
        read_osm(path)


def test_empty_download_is_reported(tmp_path):
    path = tmp_path / "roads.json"
    path.write_text('{"elements": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="no OpenStreetMap elements"):
        read_osm(path)


def test_ramps_keep_their_road_class():
    assert road_class_of("motorway") == ("motorway", False)
    assert road_class_of("motorway_link") == ("motorway", True)
    assert road_class_of("secondary_link") == ("secondary", True)
    assert road_class_of("tertiary") == (None, False)
    assert road_class_of("tertiary_link") == (None, False)
    # a ramp follows its oneway tag only
    assert directions({"highway": "motorway_link"}) == [
        "forward", "backward",
    ]
    assert directions({"highway": "motorway_link", "oneway": "yes"}) == [
        "forward",
    ]


def test_ramp_joins_roads_and_falls_back_on_its_main_road(cross):
    ways, nodes = cross
    nodes[8] = node(8, 46.53, 24.49)
    ways[0]["tags"]["maxspeed"] = "80"
    ways[1]["tags"].update(lanes="2", maxspeed="60")
    # an untagged primary ramp from the signal (4) to point 8
    ways.append(way(30, [4, 8], highway="primary_link", oneway="yes"))

    segments, _ = build_segments(ways, nodes, box=BOX)
    counts = fill_defaults(segments)
    ramps = [s for s in segments if s["is_link"]]

    assert len(ramps) == 1
    assert ramps[0]["road_class"] == "primary"
    # no tagged primary ramp: the primary road's medians are used
    assert ramps[0]["lane_count"] == 2
    assert ramps[0]["free_flow_speed_kmh"] == 80
    assert counts["medians"][("primary", True)] == (2, 80)

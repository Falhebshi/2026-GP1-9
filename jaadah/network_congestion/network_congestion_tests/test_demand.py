import json

import pytest

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.demand import (
    NearestJunction,
    junction_weights,
    read_activities,
    read_population,
    road_graph,
    segment_demand,
)

BOX = (46.0, 24.0, 47.0, 25.0)


def segment(segment_id, start, end, speed=60.0):
    """A one-way segment between two (lon, lat) points."""

    return RoadSegment(
        segment_id=segment_id, road_class="primary", lane_count=2,
        free_flow_speed_kmh=speed, signal_at_end=False,
        geometry=[start, end],
    )


@pytest.fixture
def network():
    """
    Junctions 1 to 4 in a row from west to east, one-way eastbound:
    1 -> 2 -> 3 -> 4, plus a slow direct road 1 -> 4 that the fastest
    routes do not use.
    """

    points = {1: (46.50, 24.5), 2: (46.51, 24.5), 3: (46.52, 24.5),
              4: (46.53, 24.5)}
    segments = [
        segment("SEG_A", points[1], points[2]),
        segment("SEG_B", points[2], points[3]),
        segment("SEG_C", points[3], points[4]),
        segment("SEG_SLOW", points[1], points[4], speed=5.0),
    ]
    mappings = {
        "SEG_A": {"from_node_id": 1, "to_node_id": 2},
        "SEG_B": {"from_node_id": 2, "to_node_id": 3},
        "SEG_C": {"from_node_id": 3, "to_node_id": 4},
        "SEG_SLOW": {"from_node_id": 1, "to_node_id": 4},
    }

    return road_graph(segments, mappings)


def test_trips_follow_the_fastest_route(network):
    graph, _ = network

    # people at junction 1, places at 3 and 4
    demand = segment_demand(graph, {1: 100.0}, {3: 1.0, 4: 1.0})

    # A and B carry trips to both places, C only to junction 4
    assert demand["SEG_A"] == 1.0
    assert demand["SEG_B"] == 1.0
    assert demand["SEG_C"] == pytest.approx(0.5)
    assert "SEG_SLOW" not in demand


def test_more_people_means_more_demand(network):
    graph, _ = network

    demand = segment_demand(graph, {1: 100.0, 2: 300.0}, {3: 1.0})

    # SEG_A carries junction 1's trips, SEG_B both junctions'
    assert demand["SEG_B"] == 1.0
    assert demand["SEG_A"] == pytest.approx(100 / 400)


def test_no_trip_is_reported(network):
    graph, _ = network

    # one-way eastbound: nobody can reach junction 1
    with pytest.raises(ValueError, match="no trip"):
        segment_demand(graph, {4: 100.0}, {1: 1.0})


def test_points_join_their_nearest_junction(network):
    _, positions = network
    nearest = NearestJunction(positions)

    assert nearest.find(46.5101, 24.5001) == 2
    assert junction_weights(
        [(46.5001, 24.5, 50.0), (46.5299, 24.5, 20.0), (46.53, 24.5, 5.0)],
        nearest,
    ) == {1: 50.0, 4: 25.0}


def test_population_and_activities_are_read_inside_the_box(tmp_path):
    population = tmp_path / "population.csv"
    population.write_text(
        "X,Y,Z\n46.5,24.5,1200.5\n46.6,24.6,0\n48.0,24.5,900\n"
    )
    activities = tmp_path / "activities.json"
    activities.write_text(json.dumps({"elements": [
        {"type": "node", "id": 1, "lon": 46.5, "lat": 24.5,
         "tags": {"amenity": "school"}},
        {"type": "way", "id": 2, "center": {"lon": 46.6, "lat": 24.6},
         "tags": {"shop": "mall"}},
        {"type": "node", "id": 3, "lon": 46.6, "lat": 24.6},   # no tags
        {"type": "node", "id": 4, "lon": 48.0, "lat": 24.6,
         "tags": {"office": "yes"}},                          # outside
    ]}))

    # empty cells and cells outside the box are left out
    assert read_population(population, BOX) == [(46.5, 24.5, 1200.5)]
    assert read_activities(activities, BOX) == [(46.5, 24.5), (46.6, 24.6)]

    with pytest.raises(FileNotFoundError):
        read_population(tmp_path / "missing.csv", BOX)

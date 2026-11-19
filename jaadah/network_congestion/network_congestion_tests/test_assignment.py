import numpy as np
import pytest

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.assignment import (
    Network,
    assign,
    bpr_seconds,
    congestion_index,
    connector_weights,
    hourly_on_road,
    load,
    on_local_streets,
    tomtom_calibration,
)
from jaadah.network_congestion.parameters import CIRCUITY, LOCAL_STREETS_KM, ZONE_CONNECTORS

# Artificial network, not from OSM: junctions A, B, C, D on a square,
# A to D either through B (secondary, short) or through C (secondary,
# longer), every road both ways
POINTS = {"A": (46.60, 24.70), "B": (46.61, 24.71), "C": (46.61, 24.69), "D": (46.62, 24.70), "E": (46.64, 24.70)}


def road(sid, a, b, lanes=1, speed=50.0):
    return RoadSegment(
        segment_id=sid, name_en=None, name_ar=None, road_class="secondary", is_link=False,
        lane_count=lanes, free_flow_speed_kmh=speed, signal_at_end=False,
        geometry=[list(POINTS[a]), list(POINTS[b])],
    )


def network(slow_detour=True):
    roads, mappings = [], {}
    links = [("A", "B", 50.0), ("B", "D", 50.0), ("A", "C", 30.0 if slow_detour else 50.0),
             ("C", "D", 30.0 if slow_detour else 50.0), ("D", "E", 50.0)]
    for k, (a, b, speed) in enumerate(links):
        for x, y, tag in ((a, b, "f"), (b, a, "r")):
            sid = f"S{k}{tag}"
            roads.append(road(sid, x, y, speed=speed))
            mappings[sid] = {"segment_id": sid, "from_node_id": x, "to_node_id": y}
    return Network(roads, mappings)


def test_every_zone_shares_its_trips_between_its_connections_without_copying_them():
    net = network()
    zones = [{"lon": 46.605, "lat": 24.70}, {"lon": 46.70, "lat": 24.80}]

    weights = connector_weights(zones, net)

    assert weights.sum(1) == pytest.approx(1)
    assert ((weights > 0).sum(1) <= ZONE_CONNECTORS).all()
    assert (weights[1] > 0).sum() == 1          # far from the network: its nearest junction only


def test_trips_count_in_each_hour_they_spend_on_the_road_and_once_in_total():
    departures = [np.zeros((2, 2)) for _ in range(96)]
    departures[30][0, 1] = 100.0                 # leaving 07:30-07:45, mid-slot 07:37.5
    minutes = np.array([[0.0, 56.0], [56.0, 0.0]])   # 60 minutes with access

    hours = hourly_on_road(departures, minutes)

    assert sum(h.sum() for h in hours) == pytest.approx(100)
    assert hours[7][0, 1] == pytest.approx(100 * 22.5 / 60)
    assert hours[8][0, 1] == pytest.approx(100 * 37.5 / 60)


def test_a_trip_leaving_late_wraps_around_midnight():
    departures = [np.zeros((1, 1)) for _ in range(96)]
    departures[95][0, 0] = 10.0
    hours = hourly_on_road(departures, np.array([[56.0]]))

    assert sum(h.sum() for h in hours) == pytest.approx(10)
    assert hours[0][0, 0] > 0


def test_short_trips_stay_on_local_streets():
    km = np.array([[1.0, (LOCAL_STREETS_KM - 0.1) * CIRCUITY], [(LOCAL_STREETS_KM + 0.1) * CIRCUITY, 1.0]])

    assert on_local_streets(km).tolist() == [[True, True], [False, True]]


def test_loading_keeps_every_trip_on_a_connected_route():
    net = network()
    trips = np.zeros((len(net), len(net)))
    a, e = net.index["A"], net.index["E"]
    trips[a, e] = 100.0

    flow = load(net, trips, net.free_seconds)
    into_e = sum(flow[k] for k, v in enumerate(net.edge_to) if v == e)

    assert into_e == pytest.approx(100)
    # the fast road through B carries it all at free flow
    via_b = flow[net.edge_of[(a, net.index["B"])]]
    assert via_b == pytest.approx(100)


def test_congestion_sends_part_of_the_traffic_to_the_slower_route():
    net = network()
    trips = np.zeros((len(net), len(net)))
    a, d = net.index["A"], net.index["D"]
    trips[a, d] = 3000.0                         # far above one lane's capacity

    flow, seconds = assign(net, trips)
    via_b = flow[net.edge_of[(a, net.index["B"])]]
    via_c = flow[net.edge_of[(a, net.index["C"])]]

    assert via_b + via_c == pytest.approx(3000)
    assert via_c > 0
    assert (seconds >= net.free_seconds).all()
    assert congestion_index(net, flow, seconds) > 0


def test_travel_time_follows_the_bpr_curve():
    net = network()
    flow = net.capacity.copy()                   # v/c = 1

    assert bpr_seconds(net, flow) == pytest.approx(net.free_seconds * 1.15)
    assert congestion_index(net, np.zeros_like(flow), net.free_seconds) == 0


def test_tomtom_calibration_reports_the_factor_for_each_quarter_hour():
    factors = tomtom_calibration([0.2, 0.0, 0.8], [1.4, 1.3, 1.4])

    assert factors == pytest.approx([2.0, 1.0, 0.5])

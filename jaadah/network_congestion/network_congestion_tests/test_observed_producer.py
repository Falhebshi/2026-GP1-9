from datetime import datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.observed import (
    RoadNetwork,
    build_model,
    day_factor,
    day_factors,
    interval_speeds,
    load_road_network,
    slot_of,
    free_flow_10km_s,
    target_index,
    timeline_speed,
    tomtom_index,
    tomtom_travel_index,
    travel_time_index,
)
from jaadah.network_congestion.parameters import DAY_FACTOR_LIMITS
from jaadah.network_congestion.producer import ObservedSpeedProducer
from jaadah.network_congestion.server import MapSource, create_app
from jaadah.network_congestion.storage import (
    RIYADH,
    NetworkSpeedStorage,
    SourceMetadata,
)

# The source's clock: 13 weeks behind 18 Nov 2026 17:00 (a Wednesday)
REPLAY_NOW = datetime(2026, 8, 19, 17, 0, tzinfo=RIYADH)


def road(segment_id, x):
    return RoadSegment(
        segment_id=segment_id, name_en=f"Road {segment_id}", name_ar=None,
        road_class="primary", lane_count=2, free_flow_speed_kmh=60,
        signal_at_end=True, geometry=[[x, 24.7], [x + 0.001, 24.7]],
    )


@pytest.fixture
def network():
    """Three artificial roads: below, at and above the intersection's rank."""

    segments = [road("SEG_00001", 46.60), road("SEG_00002", 46.61), road("SEG_00003", 46.62)]
    offsets = np.array([-0.4, 0.0, 0.4])

    return RoadNetwork(
        segments=segments,
        capacities={s.segment_id: 1000.0 for s in segments},
        capacity_array=np.full(3, 1000.0),
        length_array=np.full(3, 100.0),
        offsets=[offsets] * 96,
    )


def usual_week(level=0.6):
    """Artificial calibration intervals: the same v/c every 15 minutes of a week."""

    start = datetime(2026, 7, 13, tzinfo=RIYADH)       # a Monday
    return {start + timedelta(minutes=15 * i): level for i in range(7 * 96)}


@pytest.fixture
def model(network):
    return build_model(None, network, usual_week(), spread=0.5)


# ============================================================
# THE MODEL
# ============================================================

def test_slot_of():
    assert slot_of(datetime(2026, 8, 19, 0, 0, tzinfo=RIYADH)) == 0
    assert slot_of(datetime(2026, 8, 19, 17, 40, tzinfo=RIYADH)) == 17 * 4 + 2


def test_a_usual_day_follows_tomtom(model):
    moment = datetime(2026, 8, 19, 8, 0, tzinfo=RIYADH)     # Wednesday 08:00

    free_flow = free_flow_10km_s(model.network.segments, model.network.capacity_array, model.network.length_array)

    assert day_factor(model, moment, 0.6) == 1.0
    assert target_index(model, moment, 0.6) == pytest.approx(tomtom_travel_index(moment.date(), free_flow)[32])


def test_the_network_index_reaches_the_target(model):
    moment = datetime(2026, 8, 19, 17, 0, tzinfo=RIYADH)
    target = target_index(model, moment, 0.6)

    speeds, network_speed = interval_speeds(model, moment, 0.6)

    # back from speed to v/c: speed ratio = 1 / (1 + 0.15 (v/c)^4)
    vc = ((100 / np.array(speeds) - 1) / 0.15) ** 0.25
    index = travel_time_index(vc, model.network.capacity_array, model.network.length_array)
    assert index == pytest.approx(target, abs=0.02)
    # the busier-ranked road is slower
    assert speeds[0] > speeds[1] > speeds[2]
    # the timeline shows the speed of the slowest share of the road length
    assert network_speed == timeline_speed(np.array(speeds), model.network.length_array)


def test_a_busier_day_at_the_intersection_darkens_the_city(model):
    moment = datetime(2026, 8, 19, 17, 0, tzinfo=RIYADH)

    usual, _ = interval_speeds(model, moment, 0.6)
    busier, _ = interval_speeds(model, moment, 0.75)
    quieter, _ = interval_speeds(model, moment, 0.45)

    assert all(b <= u <= q for b, u, q in zip(busier, usual, quieter))
    assert busier != usual != quieter


def test_the_day_factor_stays_within_its_limits(model):
    moment = datetime(2026, 8, 19, 17, 0, tzinfo=RIYADH)

    assert day_factor(model, moment, 6.0) == DAY_FACTOR_LIMITS[1]
    assert day_factor(model, moment, 0.0) == DAY_FACTOR_LIMITS[0]


def test_one_factor_for_the_day_so_far(model):
    morning = datetime(2026, 8, 19, 7, 0, tzinfo=RIYADH)
    levels = {morning: 0.9, morning + timedelta(minutes=15): 0.3}

    factors = day_factors(model, levels)

    assert factors[morning] == pytest.approx(DAY_FACTOR_LIMITS[1])       # 0.9 / 0.6 = 1.5, capped
    assert factors[morning + timedelta(minutes=15)] == pytest.approx(1.0)   # (1.5 + 0.5) / 2


def test_a_busy_morning_at_the_intersection_keeps_the_evening_busier(model):
    # Riyadh's TomTom evening is busier than its morning; one busy morning
    # interval at the intersection must not reverse that on the map
    day = datetime(2026, 8, 19, tzinfo=RIYADH)
    levels = {day + timedelta(minutes=15 * i): 0.6 for i in range(96)}
    levels[day + timedelta(hours=8)] = 6.0
    levels[day + timedelta(hours=17)] = 0.0
    factors = day_factors(model, levels)
    morning, evening = day + timedelta(hours=8), day + timedelta(hours=17)

    assert target_index(model, evening, 0.0, factors[evening]) > target_index(model, morning, 6.0, factors[morning])
    morning_speeds, _ = interval_speeds(model, morning, 6.0, factors[morning])
    evening_speeds, _ = interval_speeds(model, evening, 0.0, factors[evening])
    assert np.mean(evening_speeds) < np.mean(morning_speeds)


def test_no_day_factor_can_put_the_morning_above_the_evening():
    network = load_road_network()
    free_flow = free_flow_10km_s(network.segments, network.capacity_array, network.length_array)
    low, high = DAY_FACTOR_LIMITS
    for day in range(7):
        moment = datetime(2026, 8, 16, tzinfo=RIYADH) + timedelta(days=day)
        index = tomtom_travel_index(moment.date(), free_flow)
        morning = max(index[6 * 4:10 * 4]) - 1
        evening = max(index[15 * 4:19 * 4]) - 1
        assert morning * high < evening * low


def test_the_city_is_measured_against_the_map_roads_free_flow():
    network = load_road_network()
    free_flow = free_flow_10km_s(network.segments, network.capacity_array, network.length_array)
    wednesday = tomtom_travel_index(datetime(2026, 9, 16).date(), free_flow)

    # quiet at 04:00, slow at the evening peak: about 40% of free flow
    assert wednesday[4 * 4] < 1.3
    assert 100 / wednesday[17 * 4] == pytest.approx(40, abs=3)
    assert len(tomtom_index(datetime(2026, 9, 16).date())) == 96


def test_the_timeline_bar_is_high_when_enough_road_length_is_high():
    lengths = np.array([10.0, 10.0, 80.0])

    assert timeline_speed(np.array([30, 90, 90]), lengths, share=0.15) == 90
    assert timeline_speed(np.array([30, 30, 90]), lengths, share=0.15) == 30
    assert timeline_speed(np.array([90, 30, 30]), lengths, share=0.15) == 30


def test_without_a_usual_value_the_city_follows_tomtom(network):
    model = build_model(None, network, {}, spread=0.5)
    moment = datetime(2026, 8, 19, 8, 0, tzinfo=RIYADH)

    assert day_factor(model, moment, 2.0) == 1.0


def test_the_usual_value_is_the_mean_for_that_weekday_and_time(network):
    monday = datetime(2026, 7, 13, 8, 0, tzinfo=RIYADH)
    levels = {monday: 0.4, monday + timedelta(weeks=1): 0.8, monday + timedelta(days=1): 0.1}

    model = build_model(None, network, levels, spread=0.5)

    assert model.usual[(0, 32)] == pytest.approx(0.6)
    assert model.usual[(1, 32)] == pytest.approx(0.1)


def test_roads_are_ranked_by_the_trip_model_or_else_the_demand_model(tmp_path):
    import json
    from jaadah.network_congestion.observed import DEFAULT_HOURLY_VC

    trip_model = load_road_network()
    fallback = load_road_network(hourly_vc_path=tmp_path / "missing.json")

    assert DEFAULT_HOURLY_VC.exists()
    assert len(trip_model.offsets) == len(fallback.offsets) == 96
    assert not np.array_equal(trip_model.offsets[17 * 4], fallback.offsets[17 * 4])
    # a quarter hour between two hours blends their ranks
    hourly = json.loads(DEFAULT_HOURLY_VC.read_text(encoding="utf-8"))["segments"]
    assert all(len(values) == 24 for values in hourly.values())
    middle = trip_model.offsets[17 * 4 + 2]
    assert np.allclose(middle, 0.5 * trip_model.offsets[17 * 4] + 0.5 * trip_model.offsets[18 * 4], equal_nan=True)
    # roads the trip model has no data for have no offset (no data), while the demand model ranks every road
    missing = [i for i, s in enumerate(trip_model.segments) if s.segment_id not in hourly]
    assert missing and not np.isnan(fallback.offsets[0]).any()
    assert np.isnan(trip_model.offsets[0]).sum() <= len(missing)


def test_friday_and_saturday_use_the_weekend_profile(tmp_path):
    from jaadah.network_congestion.observed import DEFAULT_WEEKEND_HOURLY_VC

    network = load_road_network()
    without_weekend = load_road_network(weekend_hourly_vc_path=tmp_path / "missing.json")

    assert DEFAULT_WEEKEND_HOURLY_VC.exists()
    assert network.weekend_offsets is not None and len(network.weekend_offsets) == 96
    assert not np.array_equal(network.weekend_offsets[20 * 4], network.offsets[20 * 4])
    for day, weekend in ((13, False), (16, False), (17, False), (18, True), (19, True)):   # Sun, Wed, Thu, Fri, Sat
        moment = datetime(2026, 9, day, 17, 0, tzinfo=RIYADH)
        expected = network.weekend_offsets if weekend else network.offsets
        assert network.offsets_on(moment) is expected
    # without the weekend file every day uses the weekday profile
    assert without_weekend.weekend_offsets is None
    assert without_weekend.offsets_on(datetime(2026, 9, 18, 17, 0, tzinfo=RIYADH)) is without_weekend.offsets


def test_the_weekend_profile_changes_the_weekend_map_and_repeats_exactly(network):
    weekend = RoadNetwork(
        segments=network.segments, capacities=network.capacities,
        capacity_array=network.capacity_array, length_array=network.length_array,
        offsets=network.offsets, weekend_offsets=[np.array([0.4, 0.0, -0.4])] * 96,
    )
    model = build_model(None, weekend, usual_week(), spread=0.5)
    wednesday = datetime(2026, 8, 19, 17, 0, tzinfo=RIYADH)
    friday = datetime(2026, 8, 21, 17, 0, tzinfo=RIYADH)

    weekday_speeds, _ = interval_speeds(model, wednesday, 0.6, 1.0)
    friday_speeds, _ = interval_speeds(model, friday, 0.6, 1.0)

    assert weekday_speeds[0] > weekday_speeds[2]        # weekday ranks: road 3 busiest
    assert friday_speeds[0] < friday_speeds[2]          # weekend ranks: road 1 busiest
    assert interval_speeds(model, friday, 0.6, 1.0) == interval_speeds(model, friday, 0.6, 1.0)


def test_the_real_road_network_has_offsets_for_every_15_minutes():
    network = load_road_network()

    assert len(network.offsets) == 96
    assert all(len(o) == len(network.segments) for o in network.offsets)
    assert len(network.length_array) == len(network.capacity_array) == len(network.segments)
    # morning and evening ranks differ, so the offsets change over the day
    assert not np.array_equal(network.offsets[8 * 4], network.offsets[17 * 4])


# ============================================================
# THE PRODUCER
# ============================================================

@pytest.fixture
def storage(tmp_path):
    result = NetworkSpeedStorage(tmp_path / "network_speeds.db")
    result.initialize()
    return result


def every_interval(start, end):
    """Artificial v/c at the intersection for every interval."""

    levels, moment = {}, start
    while moment < end:
        levels[moment] = 0.5 + 0.3 * (moment.hour >= 16)
        moment += timedelta(minutes=15)
    return levels


def test_the_producer_follows_the_source_clock(model, storage):
    producer = ObservedSpeedProducer(model, storage, lambda: REPLAY_NOW, every_interval)

    added = producer.synchronize()

    # 6 whole days, then 19 Aug 00:00 to 17:00: the data's dates, not the computer's
    assert added == 6 * 96 + 17 * 4
    assert storage.get_days() == [f"2026-08-{day:02d}" for day in range(13, 20)]
    assert storage.get_latest_end() == REPLAY_NOW


def test_an_interval_without_the_intersection_v_c_is_not_stored(model, storage):
    gap = datetime(2026, 8, 19, 9, 0, tzinfo=RIYADH)

    def with_gap(start, end):
        levels = every_interval(start, end)
        levels.pop(gap)
        return levels

    ObservedSpeedProducer(model, storage, lambda: REPLAY_NOW, with_gap).synchronize()

    assert storage.get_interval(gap) is None
    assert storage.get_interval(gap + timedelta(minutes=15)) is not None


def test_later_only_the_new_intervals_are_added(model, storage):
    clock = {"now": REPLAY_NOW}
    asked = []

    def levels(start, end):
        asked.append((start, end))
        return every_interval(start, end)

    producer = ObservedSpeedProducer(model, storage, lambda: clock["now"], levels)
    producer.synchronize()
    clock["now"] = REPLAY_NOW + timedelta(minutes=15)

    assert producer.synchronize() == 1
    # read from the start of the day, for the day factor so far
    assert asked[-1] == (datetime(2026, 8, 19, tzinfo=RIYADH), REPLAY_NOW + timedelta(minutes=15))
    assert producer.synchronize() == 0


def test_a_source_without_data_adds_nothing(model, storage):
    assert ObservedSpeedProducer(model, storage, lambda: None, every_interval).synchronize() == 0


def test_the_speeds_stored_are_the_model_speeds(model, storage):
    ObservedSpeedProducer(model, storage, lambda: REPLAY_NOW, every_interval).synchronize()
    moment = datetime(2026, 8, 19, 16, 30, tzinfo=RIYADH)

    stored = storage.get_interval(moment)
    day = every_interval(datetime(2026, 8, 19, tzinfo=RIYADH), moment + timedelta(minutes=15))

    assert stored.speeds == interval_speeds(model, moment, 0.8, day_factors(model, day)[moment])[0]


# ============================================================
# THE SERVER WITH THE RCRC SOURCE
# ============================================================

def test_the_server_says_where_the_speeds_come_from(model, storage):
    source = MapSource(
        name="rcrc",
        segments=model.network.segments,
        capacities=model.network.capacities,
        metadata=SourceMetadata(seed=0, interval_minutes=15,
                                timezone="Asia/Riyadh", inputs="test"),
        producer=lambda s: ObservedSpeedProducer(model, s, lambda: REPLAY_NOW, every_interval),
    )
    source.producer(storage).synchronize()

    with TestClient(create_app(storage=storage, run_producer=False, source=source)) as client:
        assert client.get("/health").json()["source"] == "rcrc"
        assert client.get("/days").json()["days"][-1] == "2026-08-19"
        assert client.get("/speeds").json()["interval_start"] == "2026-08-19T16:45:00+03:00"
        segment = client.get("/segments").json()["features"][0]
        assert segment["properties"]["source"] == "rcrc"

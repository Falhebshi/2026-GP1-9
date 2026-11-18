from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.observed import (
    MAX_VOLUME_TO_CAPACITY,
    CalibrationSample,
    approach_ranks,
    approach_spread,
    approach_volume_to_capacity,
    bpr_travel_ratio,
    distance_m,
    evaluate,
    fit_level,
    load_site_inputs,
    segment_loads,
    site_capacity,
    split_by_week,
    rank_offsets,
    segment_volume_to_capacity,
    site_levels,
    site_rank,
    site_segments,
    site_volume_to_capacity,
    speed_percent,
    tomtom_index,
    travel_time_index,
)

RIYADH = timezone(timedelta(hours=3))
CENTRE = (46.633641, 24.735316)


def segment(segment_id, end, signal=True, start=None):
    start = start or [end[0] - 0.001, end[1]]
    return RoadSegment(
        segment_id=segment_id, name_en="Test Rd", name_ar=None, road_class="primary",
        lane_count=2, free_flow_speed_kmh=60, signal_at_end=signal,
        geometry=[start, end],
    )


# ============================================================
# 1. THE STUDY INTERSECTION
# ============================================================

@pytest.fixture(scope="module")
def site():
    return load_site_inputs()


def test_light_demand_gives_a_low_critical_ratio(site):
    flows = {movement_id: 100.0 for movement_id in site.attributes}

    ratio = site_volume_to_capacity(site, flows)

    assert ratio is not None and 0 < ratio < 0.5


def test_the_critical_ratio_grows_with_demand(site):
    light = site_volume_to_capacity(site, {m: 100.0 for m in site.attributes})
    heavy = site_volume_to_capacity(site, {m: 400.0 for m in site.attributes})

    # not exactly 4 times: the HCM left-turn adjustment depends on the flow
    assert heavy == pytest.approx(4 * light, rel=0.05)


def test_a_movement_without_demand_leaves_the_ratio_unknown(site):
    flows = {movement_id: 100.0 for movement_id in site.attributes}
    flows.pop(next(iter(flows)))

    assert site_volume_to_capacity(site, flows) is None


def test_each_approach_gets_its_fullest_lane_group(site):
    result = site_capacity(site, {m: 200.0 for m in site.attributes})

    by_approach = approach_volume_to_capacity(site, result)

    assert set(by_approach) == {g.approach_id for g in site.groups}
    for approach_id, ratio in by_approach.items():
        groups = [result.lane_groups[g.lane_group_id].volume_to_capacity
                  for g in site.groups if g.approach_id == approach_id]
        assert ratio == pytest.approx(max(groups))


def test_site_levels_turn_15_minute_counts_into_hourly_flows(site):
    class Demand:
        def __init__(self, movement_id, start, count):
            self.movement_id, self.interval_start, self.vehicle_count = movement_id, start, count

    start = datetime(2026, 8, 18, 17, 0, tzinfo=RIYADH)
    demands = [Demand(m, start, 25) for m in site.attributes]
    demands.append(Demand("MOV_NOT_ANALYSED", start, 999))

    levels = site_levels(site, demands)

    assert list(levels) == [start]
    assert levels[start] == pytest.approx(
        site_volume_to_capacity(site, {m: 100.0 for m in site.attributes})
    )


# ============================================================
# 2. EVERY OTHER ROAD
# ============================================================

def test_distance_is_in_metres():
    one_km_east = [CENTRE[0] + 1000 / (111_320 * np.cos(np.radians(CENTRE[1]))), CENTRE[1]]

    assert distance_m(one_km_east, CENTRE) == pytest.approx(1000, rel=1e-6)


def test_site_segments_end_at_the_signal_near_the_centre():
    near = segment("near", [CENTRE[0] + 0.0005, CENTRE[1]])
    far = segment("far", [CENTRE[0] + 0.01, CENTRE[1]])
    no_signal = segment("free", [CENTRE[0] + 0.0005, CENTRE[1]], signal=False)

    assert [s.segment_id for s in site_segments([near, far, no_signal], CENTRE)] == ["near"]


def test_site_rank_is_length_weighted():
    short = segment("short", [0.001, 0], start=[0.0, 0])
    long = segment("long", [0.003, 0], start=[0.0, 0])
    corridors = {"short": "A", "long": "B"}

    rank = site_rank([short, long], corridors, {"A": 0.0, "B": 1.0})

    assert rank == pytest.approx(0.75, rel=1e-3)


def test_no_site_segment_is_an_error():
    with pytest.raises(ValueError):
        site_rank([], {}, {})


def test_loads_divide_trips_by_capacity():
    narrow, wide = segment("narrow", [0.001, 0]), segment("wide", [0.002, 0])

    loads = segment_loads([narrow, wide], {"narrow": 300, "wide": 600}, {"narrow": 1000, "wide": 4000})

    assert loads == {"narrow": pytest.approx(0.3), "wide": pytest.approx(0.15)}


def test_approach_ranks_follow_the_travel_direction():
    westbound = segment("west", [0.0, 0.0], start=[0.001, 0.0])   # arrives from the east
    northbound = segment("north", [0.0, 0.0], start=[0.0, -0.001])  # arrives from the south
    corridors = {"west": "A", "north": "B"}

    ranks = approach_ranks([westbound, northbound], corridors, {"A": 0.8, "B": 0.2})

    assert ranks == {"APP_E": pytest.approx(0.8), "APP_S": pytest.approx(0.2)}


def test_approach_spread_is_the_slope_of_log_ratio_on_rank():
    ranks = {"APP_E": 0.2, "APP_W": 0.4, "APP_N": 0.6, "APP_S": 0.8}
    ratios = {a: 0.5 * np.exp(2.0 * r) for a, r in ranks.items()}

    assert approach_spread(ratios, ranks) == pytest.approx(2.0)


def test_approach_spread_falls_back_when_the_pattern_is_unclear():
    ranks = {"APP_E": 0.2, "APP_W": 0.4, "APP_N": 0.6}

    # busier-ranked approaches are emptier
    assert approach_spread({"APP_E": 0.9, "APP_W": 0.6, "APP_N": 0.3}, ranks) is None
    # too few approaches
    assert approach_spread({"APP_E": 0.9, "APP_W": 0.6}, ranks) is None
    # all ranks equal
    assert approach_spread({"APP_E": 0.9, "APP_W": 0.6, "APP_N": 0.3},
                           {"APP_E": 0.5, "APP_W": 0.5, "APP_N": 0.5}) is None


def test_offsets_are_relative_to_the_site():
    a, b = segment("a", [0.001, 0]), segment("b", [0.002, 0])

    offsets = rank_offsets([a, b], {"a": "A", "b": "B"}, {"A": 0.2, "B": 0.9}, site=0.4)

    assert offsets == pytest.approx([-0.2, 0.5])


def test_the_level_scales_every_road():
    plain = segment_volume_to_capacity(0.5, np.array([0.0, 0.2]), spread=1.0)
    scaled = segment_volume_to_capacity(0.5, np.array([0.0, 0.2]), spread=1.0, level=1.5)

    assert scaled == pytest.approx(1.5 * plain)


def test_a_corridor_ranked_like_the_site_gets_the_site_ratio():
    ratios = segment_volume_to_capacity(0.8, np.array([0.0, 0.3, -0.3]), spread=2.0)

    assert ratios[0] == pytest.approx(0.8)
    assert ratios[1] > 0.8 > ratios[2]


def test_ratios_stop_at_the_maximum():
    ratios = segment_volume_to_capacity(1.0, np.array([5.0]), spread=5.0)

    assert ratios[0] == MAX_VOLUME_TO_CAPACITY


# ============================================================
# 3. SPEED
# ============================================================

def test_bpr_at_capacity_adds_15_percent():
    assert bpr_travel_ratio(np.array([1.0]))[0] == pytest.approx(1.15)


def test_speed_is_full_with_no_traffic_and_falls_with_v_over_c():
    speeds = speed_percent(np.array([0.0, 1.0, 2.0]))

    assert list(speeds) == [100, 87, 29]


# ============================================================
# 4. TOMTOM: THE LEVEL AND THE TEST
# ============================================================

def test_empty_roads_give_an_index_of_one():
    assert travel_time_index(np.zeros(3), np.ones(3), np.ones(3)) == 1.0


def test_busier_roads_weigh_more_in_the_index():
    vc = np.array([0.5, 2.0])
    lengths = np.ones(2)

    by_vehicle_km = travel_time_index(vc, np.ones(2), lengths)
    plain_mean = float(bpr_travel_ratio(vc).mean())

    assert by_vehicle_km > plain_mean


def samples_with(level_true, spread, offsets, capacities, lengths, start):
    """Artificial samples whose TomTom index the model reproduces exactly at level_true."""

    samples = []
    for day in range(28):
        for site_level in (0.3, 0.6, 0.9):
            moment = start + timedelta(days=day, hours=int(site_level * 10))
            samples.append(CalibrationSample(
                moment=moment, site_level=site_level, offsets=offsets,
                tomtom_index=travel_time_index(
                    segment_volume_to_capacity(site_level, offsets, spread, level_true),
                    capacities, lengths,
                ),
            ))
    return samples


def test_fit_level_recovers_a_known_level():
    offsets = np.linspace(-0.5, 0.5, 21)
    capacities, lengths = np.ones(21), np.ones(21)
    start = datetime(2026, 8, 3, tzinfo=RIYADH)
    samples = samples_with(1.4, 2.0, offsets, capacities, lengths, start)

    level = fit_level(samples, 2.0, capacities, lengths)

    assert level == pytest.approx(1.4, abs=0.005)


def test_fit_level_needs_samples():
    with pytest.raises(ValueError):
        fit_level([], 1.0, np.ones(1), np.ones(1))


def test_split_by_week_keeps_fit_and_test_apart():
    offsets = np.zeros(1)
    start = datetime(2026, 8, 3, tzinfo=RIYADH)       # a Monday, ISO week 32
    samples = samples_with(1.0, 1.0, offsets, np.ones(1), np.ones(1), start)

    fit, test = split_by_week(samples)

    assert fit and test and len(fit) + len(test) == len(samples)
    assert {s.moment.isocalendar().week % 2 for s in fit} == {0}
    assert {s.moment.isocalendar().week % 2 for s in test} == {1}


def test_evaluate_on_unseen_weeks_finds_the_true_level_close():
    offsets = np.linspace(-0.5, 0.5, 21)
    capacities, lengths = np.ones(21), np.ones(21)
    start = datetime(2026, 8, 3, tzinfo=RIYADH)
    fit, test = split_by_week(samples_with(1.4, 2.0, offsets, capacities, lengths, start))

    level = fit_level(fit, 2.0, capacities, lengths)
    result = evaluate(test, 2.0, level, capacities, lengths)

    assert result.samples == len(test)
    assert result.rmse < 0.01
    assert result.shape_correlation > 0.999


def test_evaluate_needs_two_samples():
    with pytest.raises(ValueError):
        evaluate([], 1.0, 1.0, np.ones(1), np.ones(1))


def test_tomtom_index_reads_the_table_on_the_two_hour_marks():
    monday = tomtom_index(date(2026, 11, 16))

    assert len(monday) == 96
    assert monday[16 * 4] == pytest.approx(1.89)    # Monday 16:00, 89 %
    assert monday[4 * 4] == pytest.approx(1.00)     # Monday 04:00, 0 %


def test_tomtom_index_joins_the_marks_with_straight_lines():
    monday = tomtom_index(date(2026, 11, 16))

    # halfway between 16:00 (89 %) and 18:00 (77 %)
    assert monday[17 * 4] == pytest.approx(1.83)


def test_tomtom_index_after_22_runs_to_the_next_midnight():
    friday = tomtom_index(date(2026, 11, 20))

    # Friday 22:00 is 46 %, Saturday 00:00 is 33 %
    assert friday[23 * 4] == pytest.approx(1 + (46 + 33) / 2 / 100)

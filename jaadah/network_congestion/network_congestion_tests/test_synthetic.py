import csv
import json
from datetime import date

import pytest

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.parameters import (
    TOMTOM_FREE_FLOW_10KM_S,
    TOMTOM_TRAVEL_TIME_10KM_S,
    segment_capacity,
)
from jaadah.network_congestion.synthetic import (
    SampleMeasures,
    city_delay,
    corridor_factor,
    corridor_key,
    corridor_ranks,
    corridor_variation,
    day_file,
    day_speeds,
    day_type,
    evening_share,
    heading,
    measure_sample,
    peak_vc_range,
    read_directions,
    read_persistence,
    segments_geojson,
    variation_sd,
)

MONDAY = date(2026, 11, 9)
FRIDAY = date(2026, 11, 6)

# Every RCRC-like file below is artificial, not from RCRC: westbound
# (2 lanes) busiest at slot 28, eastbound (1 lane) at slot 70; every
# slot's SD is 20 % of its mean.
MEASURES = SampleMeasures(
    peak_vc_range=(0.6, 1.2), variation_sd=0.2, persistence=0.5,
)


def write_detector_profile(path):
    """Write an artificial detector_time_of_day_profile.csv."""

    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["detector_id", "description", "slot_index",
                         "mean_volume", "std_volume"])

        for detector, description, peak in (
            (1, "P2-WB-L1-T-STB", 28),
            (2, "P2-WB-L2-T-STB", 28),
            (3, "P6-EB-L1-T-STB", 70),
        ):
            for slot in range(96):
                volume = 100 if slot == peak else 20
                writer.writerow(
                    [detector, description, slot, volume, volume * 0.2]
                )

    return path


def write_summary(path, lag1=0.6):
    """Write an artificial rcrc_profile_summary.json."""

    path.write_text(json.dumps(
        {"temporal_persistence": {"mean_adjusted_lag1_correlation": lag1}}
    ))

    return path


def segment(segment_id="SEG_00001", **changes):
    """A three-lane primary segment heading east, ending at a signal."""

    fields = {
        "segment_id": segment_id,
        "road_class": "primary",
        "lane_count": 3,
        "free_flow_speed_kmh": 80.0,
        "signal_at_end": True,
        "geometry": [(46.600001, 24.700001), (46.61, 24.70)],
    }
    fields.update(changes)

    return RoadSegment(**fields)


# ============================================================
# WHAT IS MEASURED FROM THE RCRC SAMPLE
# ============================================================

def test_directions_add_up_their_lanes(tmp_path):
    directions = read_directions(
        write_detector_profile(tmp_path / "detectors.csv")
    )

    assert set(directions) == {"W", "E"}
    assert directions["W"].lanes == 2
    assert directions["E"].lanes == 1
    assert directions["W"].volumes[28] == 200


def test_peak_range_and_variation_are_measured(tmp_path):
    directions = read_directions(
        write_detector_profile(tmp_path / "detectors.csv")
    )

    # east-west is the main road (green share 0.26):
    #   W  200 cars x 4 / (2 x 1,900 x 0.26), E  100 x 4 / (1,900 x 0.26)
    low, high = peak_vc_range(directions)

    assert low == pytest.approx(800 / 988)
    assert high == pytest.approx(400 / 494)
    assert variation_sd(directions) == pytest.approx(0.2)


def test_persistence_is_read_and_kept_usable(tmp_path):
    assert read_persistence(write_summary(tmp_path / "a.json", 0.6)) == 0.6
    assert read_persistence(write_summary(tmp_path / "b.json", -0.2)) == 0
    assert read_persistence(write_summary(tmp_path / "c.json", 1.0)) == 0.95


def test_missing_private_files_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        measure_sample(tmp_path / "missing.csv", tmp_path / "missing.json")


# ============================================================
# CITY DELAY (TomTom)
# ============================================================

def test_city_delay_follows_the_tomtom_table():
    delays = city_delay(MONDAY)
    monday = TOMTOM_TRAVEL_TIME_10KM_S[0]

    assert len(delays) == 96
    # 08:00 (slot 32) and 16:00 (slot 64) are read straight from it
    assert delays[32] == pytest.approx(monday[4] / TOMTOM_FREE_FLOW_10KM_S - 1)
    assert delays[64] == pytest.approx(monday[8] / TOMTOM_FREE_FLOW_10KM_S - 1)
    # 09:00 is halfway between 08:00 and 10:00
    assert delays[36] == pytest.approx((delays[32] + delays[40]) / 2)
    # the evening rush is the worst time of a workday
    assert max(delays) == delays[64]


def test_friday_is_quieter_than_a_workday():
    assert max(city_delay(FRIDAY)) < max(city_delay(MONDAY))
    assert day_type(FRIDAY) == "friday"
    assert day_type(date(2026, 11, 7)) == "saturday"
    assert day_type(date(2026, 11, 8)) == "workday"


def test_morning_and_evening_demand_blend_around_midday():
    assert evening_share(8 * 4) == 0       # 08:00
    assert evening_share(12 * 4) == 0.5    # 12:00
    assert evening_share(17 * 4) == 1      # 17:00


# ============================================================
# CORRIDORS AND SPEEDS
# ============================================================

def test_segments_of_one_road_and_direction_share_a_corridor():
    north = [(46.6, 24.70), (46.6, 24.71)]
    south = [(46.6, 24.71), (46.6, 24.70)]
    first = segment("SEG_00001", name_en="King Fahd Rd", geometry=north)
    second = segment("SEG_00002", name_en="King Fahd Rd", geometry=north)
    back = segment("SEG_00003", name_en="King Fahd Rd", geometry=south)
    unnamed = segment("SEG_00004", geometry=north)

    assert heading(first) == "N"
    assert heading(back) == "S"
    assert corridor_key(first, 1) == corridor_key(second, 2)
    assert corridor_key(first, 1) != corridor_key(back, 1)
    assert corridor_key(unnamed, 7) != corridor_key(unnamed, 8)


def test_busier_corridors_get_more_of_the_city_delay():
    roads = [
        segment("SEG_00001", name_en="Quiet Rd"),
        segment("SEG_00002", name_en="Main Rd"),
        segment("SEG_00003", name_en="Middle Rd"),
    ]
    corridors = {road.segment_id: corridor_key(road, 1) for road in roads}
    ranks = corridor_ranks(
        roads, corridors, {"SEG_00001": 0.01, "SEG_00002": 1.0,
                           "SEG_00003": 0.3},
    )
    quiet, main, middle = (ranks[corridors[f"SEG_0000{n}"]] for n in "123")

    assert (quiet, middle, main) == (0.0, 0.5, 1.0)
    # range 0.6-1.2: factors 0.67, 1.0, 1.33, so the city average stays
    assert corridor_factor(quiet, MEASURES) == pytest.approx(0.6 / 0.9)
    assert corridor_factor(middle, MEASURES) == pytest.approx(1.0)
    assert corridor_factor(main, MEASURES) == pytest.approx(1.2 / 0.9)


def test_speed_falls_as_the_delay_grows():
    city = city_delay(MONDAY)
    flat = [0.0] * 96
    busy = day_speeds(city, 1.5, 1.5, flat)
    quiet = day_speeds(city, 0.5, 0.5, flat)

    # 04:00 is free flow, 16:00 is the evening rush
    assert busy[16] == quiet[16] == 100
    assert busy[64] < quiet[64] < 100
    # speed = 100 / (1 + delay)
    assert busy[64] == round(100 / (1 + city[64] * 1.5))


def test_corridor_variation_has_the_measured_spread():
    values = [
        value
        for n in range(200)
        for value in corridor_variation(f"road {n}", MONDAY, MEASURES)
    ]
    mean = sum(values) / len(values)
    sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5

    assert abs(mean) < 0.02
    assert sd == pytest.approx(0.2, abs=0.02)
    # the same corridor and day always give the same values
    assert corridor_variation("road 1", MONDAY, MEASURES) == (
        corridor_variation("road 1", MONDAY, MEASURES)
    )


def test_files_hold_only_jaadah_ids():
    roads = [segment("SEG_00001"), segment("SEG_00002", road_class="motorway")]
    capacities = {road.segment_id: segment_capacity(road) for road in roads}
    corridors = {road.segment_id: corridor_key(road, 10) for road in roads}
    factors = {corridor: (1.0, 1.0) for corridor in corridors.values()}

    geojson = segments_geojson(roads, capacities)
    day = day_file(roads, corridors, factors, MEASURES, FRIDAY)

    assert [f["properties"]["id"] for f in geojson["features"]] == [
        "SEG_00001",
        "SEG_00002",
    ]
    assert day["day_type"] == "friday"
    assert set(day["speeds"]) == {"SEG_00001", "SEG_00002"}
    assert len(day["network_speed"]) == 96
    assert all(0 < value <= 100 for value in day["network_speed"])
    assert "osm" not in json.dumps([geojson, day]).lower()

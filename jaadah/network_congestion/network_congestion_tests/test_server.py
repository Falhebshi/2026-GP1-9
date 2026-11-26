from datetime import date, datetime, timedelta, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient

from jaadah.models.network_congestion import RoadSegment
from jaadah.network_congestion.producer import (
    NetworkSpeedProducer,
    latest_completed_interval,
    next_interval_boundary,
    source_metadata,
)
from jaadah.network_congestion.server import create_app
from jaadah.network_congestion.storage import (
    RIYADH,
    IntervalSpeeds,
    NetworkSpeedStorage,
    SourceMetadata,
)
from jaadah.network_congestion.synthetic import (
    City,
    SampleMeasures,
    city_day,
    interval_speeds,
    segment_corridors,
    slot_speed,
)

# Artificial measures and roads, not from RCRC or OSM
MEASURES = SampleMeasures(
    peak_vc_range=(0.6, 1.2), variation_sd=0.2, persistence=0.5,
)
NOW = datetime(2026, 11, 9, 8, 7, tzinfo=RIYADH)     # Monday 08:07


def road(segment_id, name):
    return RoadSegment(
        segment_id=segment_id,
        name_en=name,
        road_class="primary",
        lane_count=3,
        free_flow_speed_kmh=80.0,
        signal_at_end=True,
        geometry=[(46.6, 24.70), (46.61, 24.70)],
    )


@pytest.fixture
def city():
    segments = [road("SEG_00001", "Main Rd"), road("SEG_00002", "Quiet Rd")]
    corridors = segment_corridors(segments, {s.segment_id: 1 for s in segments})
    factors = {
        corridors["SEG_00001"]: (1.3, 1.2),
        corridors["SEG_00002"]: (0.7, 0.8),
    }

    return City(
        segments=segments,
        capacities={s.segment_id: 1482.0 for s in segments},
        corridors=corridors,
        factors=factors,
        measures=MEASURES,
    )


@pytest.fixture
def storage(tmp_path, city):
    result = NetworkSpeedStorage(tmp_path / "network_speeds.db")
    result.initialize()
    result.ensure_source_metadata(source_metadata(city))

    return result


# ============================================================
# ONE INTERVAL AT A TIME
# ============================================================

def test_an_interval_holds_every_segment_and_their_mean(city):
    monday = date(2026, 11, 9)
    today = city_day(city, monday)

    for slot in (0, 32, 64, 95):
        speeds, network = interval_speeds(city, today, slot)
        expected = []

        for road in city.segments:
            corridor = city.corridors[road.segment_id]
            morning, evening = city.factors[corridor]
            expected.append(slot_speed(
                today.delays[slot], morning, evening,
                today.variations[corridor][slot], slot,
            ))

        assert speeds == expected
        assert network == round(sum(expected) / len(expected), 1)


def test_interval_boundaries():
    assert latest_completed_interval(NOW) == NOW.replace(minute=0)
    assert next_interval_boundary(NOW) == NOW.replace(minute=15)


# ============================================================
# PRODUCER
# ============================================================

def test_first_start_fills_six_days_and_today(city, storage):
    added = NetworkSpeedProducer(city, storage).synchronize(NOW)

    # 6 whole days, then today 00:00 to 08:00
    assert added == 6 * 96 + 32
    assert storage.get_days() == [f"2026-11-{day:02d}" for day in range(3, 10)]
    assert storage.get_latest_end() == NOW.replace(minute=0)
    # nothing in the future
    assert storage.get_interval(NOW) is None


def test_only_the_new_interval_is_added_later(city, storage):
    producer = NetworkSpeedProducer(city, storage)
    producer.synchronize(NOW)

    assert producer.synchronize(NOW + timedelta(minutes=10)) == 1
    assert producer.synchronize(NOW + timedelta(minutes=12)) == 0


def test_old_intervals_are_deleted(city, storage):
    producer = NetworkSpeedProducer(city, storage)
    producer.synchronize(NOW)
    producer.synchronize(NOW + timedelta(days=1))

    # the next day: 3 Nov is dropped, 4-10 Nov are kept
    assert storage.get_days()[0] == "2026-11-04"
    assert len(storage.get_days()) == 7


def test_a_restart_gives_the_same_values(city, storage, tmp_path):
    NetworkSpeedProducer(city, storage).synchronize(NOW)
    other = NetworkSpeedStorage(tmp_path / "other.db")
    other.initialize()
    NetworkSpeedProducer(city, other).synchronize(NOW)

    moment = NOW - timedelta(hours=3)
    assert storage.get_interval(moment) == other.get_interval(moment)


def test_other_inputs_are_refused(storage):
    with pytest.raises(ValueError):
        storage.ensure_source_metadata(
            SourceMetadata(seed=1, interval_minutes=15,
                           timezone="Asia/Riyadh", inputs="other")
        )


def test_a_changed_parameter_changes_the_fingerprint(city, monkeypatch):
    import jaadah.network_congestion.producer as producer

    before = source_metadata(city).inputs
    monkeypatch.setattr(producer, "MORNING_DEMAND_UNTIL_HOUR", 10)

    assert source_metadata(city).inputs != before


def test_run_forever_stops(city, storage):
    stop = Event()
    stop.set()

    NetworkSpeedProducer(city, storage).run_forever(stop)

    assert storage.get_latest_end() is not None


# ============================================================
# SERVER
# ============================================================

@pytest.fixture
def client(city, storage):
    NetworkSpeedProducer(city, storage).synchronize(NOW)

    with TestClient(create_app(city, storage, run_producer=False)) as result:
        yield result


def test_health_and_days(client):
    health = client.get("/health").json()
    days = client.get("/days").json()

    assert health["latest_interval_end"] == "2026-11-09T08:00:00+03:00"
    assert days["days"][-1] == "2026-11-09"
    assert days["low_above_speed_ratio"] == 0.67


def test_speeds_of_one_interval(client):
    latest = client.get("/speeds").json()
    earlier = client.get("/speeds", params={"time": "2026-11-09T07:20:00"}).json()

    assert latest["interval_start"] == "2026-11-09T07:45:00+03:00"
    assert earlier["interval_start"] == "2026-11-09T07:15:00+03:00"
    assert set(earlier["speeds"]) == {"SEG_00001", "SEG_00002"}
    assert client.get("/speeds", params={"time": "2026-11-09T09:00:00"}).status_code == 404


def test_timeline_and_segments(client):
    timeline = client.get("/timeline", params={"day": "2026-11-09"}).json()
    segments = client.get("/segments").json()

    # 00:00 to 07:45 on the day it is now
    assert len(timeline["intervals"]) == 32
    assert [f["properties"]["id"] for f in segments["features"]] == [
        "SEG_00001", "SEG_00002",
    ]
    assert "osm" not in str(segments).lower()


def test_storage_keeps_riyadh_time(storage):
    # 02:00 UTC is 05:00 in Riyadh, on the same date
    utc_start = datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)
    storage.insert_intervals([IntervalSpeeds(
        interval_start=utc_start,
        interval_end=utc_start + timedelta(minutes=15),
        network_speed=90.0,
        speeds=[90, 90],
    )])

    assert storage.get_days() == ["2026-11-09"]

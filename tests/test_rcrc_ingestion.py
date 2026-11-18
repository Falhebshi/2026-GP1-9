from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from backend.ingestion.adapter import adapt_rcrc_record
from backend.ingestion.client import RcrcReplayClient
from backend.ingestion.service import ingest_rcrc_observations
from jaadah.models.traffic import TrafficObservationSource
from test_rcrc_replay_source import (
    ANCHOR,
    CONFIG,
    DAY,
    STEP,
    FakeNow,
    day_report,
)
from traffic_source.rcrc_replay.report import read_rcrc_report
from traffic_source.rcrc_replay.server import create_app
from traffic_source.rcrc_replay.storage import RcrcReplayStorage


def record(**overrides):
    values = {
        "Detector ID : Description": "144409: P2-NB-L1-L-STB-RP2",
        "Time Stamp": "Jul 13, 2026 00:15:00",
        "Volume (Vehicles)": "52",
        "Occupancy (Seconds)": "33",
        "Occupancy (Percent)": "4",
    }
    values.update(overrides)
    return values


# ============================================================
# ADAPTER
# ============================================================

def test_record_becomes_an_observation():
    observation = adapt_rcrc_record(record(), site_id="1444")

    assert observation.observation_id == "OBS_RCRC_1444_144409_20260713T0015"
    assert observation.source == TrafficObservationSource.RCRC
    assert observation.site_id == "1444"
    assert observation.detector_id == "144409"
    assert observation.description == "P2-NB-L1-L-STB-RP2"
    assert observation.vehicle_count == 52
    assert observation.occupancy_s == 33
    assert observation.occupancy_percent == 4


def test_time_stamp_is_the_interval_end_in_riyadh_time():
    observation = adapt_rcrc_record(record(), site_id="1444")

    assert observation.interval_end == datetime.fromisoformat("2026-07-13T00:15:00+03:00")
    assert observation.interval_start == datetime.fromisoformat("2026-07-13T00:00:00+03:00")


def test_midnight_stamp_closes_the_previous_day():
    observation = adapt_rcrc_record(record(**{"Time Stamp": "Jul 13, 2026 00:00:00"}), "1444")

    assert observation.interval_start == datetime.fromisoformat("2026-07-12T23:45:00+03:00")


def test_numbers_may_arrive_as_numbers():
    observation = adapt_rcrc_record(
        record(**{"Volume (Vehicles)": 52, "Occupancy (Seconds)": 33, "Occupancy (Percent)": 4}),
        site_id="1444",
    )

    assert observation.vehicle_count == 52


def test_blank_occupancy_is_not_supplied():
    observation = adapt_rcrc_record(
        record(**{"Occupancy (Seconds)": "", "Occupancy (Percent)": ""}), "1444",
    )

    assert observation.occupancy_s is None
    assert observation.occupancy_percent is None


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"Volume (Vehicles)": "-3"}, "Volume"),
        ({"Volume (Vehicles)": "12.5"}, "Volume"),
        ({"Volume (Vehicles)": True}, "Volume"),
        ({"Time Stamp": "2026-07-13 00:15"}, "Time Stamp"),
        ({"Time Stamp": "Jul 13, 2026 00:17:00"}, "15-minute boundary"),
        ({"Detector ID : Description": "144409 P2-NB"}, "Detector ID"),
        ({"Detector ID : Description": "A1: P2-NB"}, "whole number"),
        ({"Detector ID : Description": "144409:  "}, "description"),
        ({"Occupancy (Seconds)": "abc"}, "Occupancy"),
        ({"Occupancy (Seconds)": "nan"}, "Occupancy"),
        ({"Occupancy (Seconds)": "901"}, "longer than the interval"),
        ({"Occupancy (Percent)": "101"}, "less than or equal to 100"),
    ],
)
def test_invalid_record_is_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        adapt_rcrc_record(record(**overrides), site_id="1444")


def test_record_missing_a_field_is_rejected():
    values = record()
    del values["Occupancy (Percent)"]

    with pytest.raises(ValueError, match="missing required field"):
        adapt_rcrc_record(values, site_id="1444")


def test_non_object_record_is_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        adapt_rcrc_record(["144409"], site_id="1444")


# ============================================================
# SERVICE WITH A FAKE CLIENT
# ============================================================

class FakeClient:
    def __init__(self, records):
        self.records = records

    def fetch_observations(self, start, end):
        from backend.ingestion.client import RcrcBatch

        return RcrcBatch(site_id="1444", records=self.records)


def test_invalid_rows_are_reported_and_valid_rows_kept():
    result = ingest_rcrc_observations(
        FakeClient([record(), record(**{"Volume (Vehicles)": "x"}), "not a row"]),
        start=DAY,
        end=DAY + STEP,
    )

    assert result.received_count == 3
    assert result.accepted_count == 1
    assert [(e.record_number, e.site_id, e.detector_id, e.source_timestamp)
            for e in result.errors] == [
        (2, "1444", "144409", "Jul 13, 2026 00:15:00"),
        (3, "1444", None, None),
    ]


# ============================================================
# END TO END: REPLAY SOURCE -> CLIENT -> INGESTION
# ============================================================

@pytest.fixture
def client(tmp_path, monkeypatch):
    """An RCRC client connected to a replay source released through 10:00."""

    storage = RcrcReplayStorage(tmp_path / "replay.db")
    storage.initialize()
    storage.load_report(read_rcrc_report(day_report(tmp_path, skip={DAY + 20 * STEP})))
    now = FakeNow(ANCHOR)
    api = TestClient(
        create_app(storage=storage, config=CONFIG, now=now)
    )
    api.__enter__()

    def get_from_source(url, params=None, timeout=None):
        response = api.get(url.removeprefix("http://rcrc-source"), params=params)
        return httpx2.Response(
            response.status_code,
            json=response.json(),
            request=httpx2.Request("GET", url),
        )

    monkeypatch.setattr("backend.ingestion.client.httpx2.get", get_from_source)

    yield RcrcReplayClient("http://rcrc-source"), now

    api.__exit__(None, None, None)


def test_released_rows_become_observations(client):
    rcrc, _ = client

    result = ingest_rcrc_observations(rcrc, start=DAY, end=DAY + 4 * STEP)

    assert result.errors == []
    assert result.accepted_count == 4 * 2
    assert {o.detector_id for o in result.observations} == {"144409", "144410"}
    assert all(o.source == TrafficObservationSource.RCRC for o in result.observations)


def test_latest_available_follows_the_replay_clock(client):
    rcrc, now = client

    assert rcrc.fetch_latest_available_timestamp() == DAY + 40 * STEP

    now.moment = ANCHOR + timedelta(minutes=15)

    assert rcrc.fetch_latest_available_timestamp() == DAY + 41 * STEP


def test_missing_interval_arrives_as_no_rows(client):
    rcrc, _ = client

    result = ingest_rcrc_observations(rcrc, start=DAY + 19 * STEP, end=DAY + 21 * STEP)

    assert {o.interval_end for o in result.observations} == {DAY + 21 * STEP}


def test_ingestion_is_repeatable(client):
    rcrc, _ = client

    first = ingest_rcrc_observations(rcrc, start=DAY, end=DAY + 8 * STEP)
    second = ingest_rcrc_observations(rcrc, start=DAY, end=DAY + 8 * STEP)

    assert [o.observation_id for o in first.observations] == [
        o.observation_id for o in second.observations
    ]


def test_source_failure_is_raised(monkeypatch):
    def failing_get(url, params=None, timeout=None):
        raise httpx2.ConnectError("source is down")

    monkeypatch.setattr("backend.ingestion.client.httpx2.get", failing_get)

    with pytest.raises(httpx2.ConnectError):
        ingest_rcrc_observations(RcrcReplayClient("http://rcrc-source"), DAY, DAY + STEP)


@pytest.mark.parametrize(
    "body,message",
    [
        ({"site_id": "1444"}, "observations list"),
        ({"site_id": "1444", "observations": {}}, "observations list"),
        ({"observations": []}, "site_id"),
    ],
)
def test_malformed_source_response_is_raised(monkeypatch, body, message):
    def get(url, params=None, timeout=None):
        return httpx2.Response(200, json=body, request=httpx2.Request("GET", url))

    monkeypatch.setattr("backend.ingestion.client.httpx2.get", get)

    with pytest.raises(ValueError, match=message):
        RcrcReplayClient("http://rcrc-source").fetch_observations(DAY, DAY + STEP)

from datetime import datetime

import httpx2
import pytest

from backend.ingestion.client import SyntheticTrafficClient


def make_response(
    status_code: int = 200,
    json_data: dict | None = None,
) -> httpx2.Response:
    """Create an HTTP response for client tests."""

    request = httpx2.Request(
        "GET",
        "http://synthetic-source/observations",
    )

    return httpx2.Response(
        status_code=status_code,
        request=request,
        json=json_data,
    )


def test_fetch_observations_sends_correct_request(
    monkeypatch,
) -> None:
    captured_request = {}

    expected_observations = [
        {
            "Site ID": 9,
            "detector_id": 3,
            "Date  & Time": "2026-10-14T22:45:00+03:00",
            "volume": 51,
            "description": "P2-WB-L1-L-STB",
        }
    ]

    def fake_get(
        url: str,
        params: dict,
        timeout: float,
    ) -> httpx2.Response:
        captured_request["url"] = url
        captured_request["params"] = params
        captured_request["timeout"] = timeout

        return make_response(
            json_data={
                "source": "synthetic",
                "observations": expected_observations,
            }
        )

    monkeypatch.setattr(
        httpx2,
        "get",
        fake_get,
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source/",
        timeout_s=5.0,
    )

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    observations = client.fetch_observations(
        start=start,
        end=end,
    )

    assert captured_request["url"] == (
        "http://synthetic-source/observations"
    )

    assert captured_request["params"] == {
        "start": "2026-10-14T22:30:00+03:00",
        "end": "2026-10-14T23:00:00+03:00",
    }

    assert captured_request["timeout"] == 5.0

    assert observations == expected_observations


def test_fetch_observations_raises_on_http_error(
    monkeypatch,
) -> None:
    def fake_get(
        url: str,
        params: dict,
        timeout: float,
    ) -> httpx2.Response:
        return make_response(
            status_code=500,
            json_data={
                "detail": "synthetic source failed",
            },
        )

    monkeypatch.setattr(
        httpx2,
        "get",
        fake_get,
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    with pytest.raises(httpx2.HTTPStatusError):
        client.fetch_observations(
            start=start,
            end=end,
        )


def test_missing_observations_list_is_rejected(
    monkeypatch,
) -> None:
    def fake_get(
        url: str,
        params: dict,
        timeout: float,
    ) -> httpx2.Response:
        return make_response(
            json_data={
                "source": "synthetic",
            }
        )

    monkeypatch.setattr(
        httpx2,
        "get",
        fake_get,
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    with pytest.raises(
        ValueError,
        match="observations list",
    ):
        client.fetch_observations(
            start=start,
            end=end,
        )


def test_non_list_observations_is_rejected(
    monkeypatch,
) -> None:
    def fake_get(
        url: str,
        params: dict,
        timeout: float,
    ) -> httpx2.Response:
        return make_response(
            json_data={
                "source": "synthetic",
                "observations": {
                    "detector_id": 3,
                },
            }
        )

    monkeypatch.setattr(
        httpx2,
        "get",
        fake_get,
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    with pytest.raises(
        ValueError,
        match="observations list",
    ):
        client.fetch_observations(
            start=start,
            end=end,
        )


def fake_health(monkeypatch, captured, status_code=200, json_data=None):
    """Replace httpx2.get with a fake /health response."""

    def fake_get(url: str, timeout: float) -> httpx2.Response:
        captured["url"] = url
        captured["timeout"] = timeout

        return make_response(
            status_code=status_code,
            json_data=json_data,
        )

    monkeypatch.setattr(
        httpx2,
        "get",
        fake_get,
    )


def test_latest_available_timestamp_is_read_from_health(
    monkeypatch,
) -> None:
    captured = {}
    fake_health(
        monkeypatch,
        captured,
        json_data={
            "status": "ok",
            "source": "synthetic",
            "latest_available_timestamp": "2026-10-20T09:15:00+03:00",
        },
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source/",
        timeout_s=5.0,
    )

    latest = client.fetch_latest_available_timestamp()

    assert captured == {
        "url": "http://synthetic-source/health",
        "timeout": 5.0,
    }
    assert latest == datetime.fromisoformat(
        "2026-10-20T09:15:00+03:00"
    )
    assert latest.utcoffset() is not None


def test_empty_source_has_no_latest_timestamp(
    monkeypatch,
) -> None:
    fake_health(
        monkeypatch,
        {},
        json_data={
            "status": "ok",
            "latest_available_timestamp": None,
        },
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    assert client.fetch_latest_available_timestamp() is None


def test_latest_available_timestamp_raises_on_http_error(
    monkeypatch,
) -> None:
    fake_health(
        monkeypatch,
        {},
        status_code=500,
        json_data={
            "detail": "synthetic source failed",
        },
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    with pytest.raises(httpx2.HTTPStatusError):
        client.fetch_latest_available_timestamp()


@pytest.mark.parametrize(
    "json_data, message",
    [
        (
            {"status": "ok"},
            "must contain latest_available_timestamp",
        ),
        (
            {"latest_available_timestamp": "2026-10-20T09:15:00"},
            "must include timezone information",
        ),
    ],
)
def test_invalid_health_response_is_rejected(
    monkeypatch,
    json_data,
    message,
) -> None:
    fake_health(
        monkeypatch,
        {},
        json_data=json_data,
    )

    client = SyntheticTrafficClient(
        base_url="http://synthetic-source"
    )

    with pytest.raises(
        ValueError,
        match=message,
    ):
        client.fetch_latest_available_timestamp()

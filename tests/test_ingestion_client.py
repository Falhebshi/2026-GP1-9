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
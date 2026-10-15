from datetime import datetime

import httpx2
import pytest

from jaadah.ingestion.service import ingest_synthetic_observations


class FakeSyntheticTrafficClient:
    """Simple fake client used to test the ingestion service."""

    def __init__(self, records: list) -> None:
        self.records = records

    def fetch_observations(
        self,
        start: datetime,
        end: datetime,
    ) -> list:
        return self.records


def make_record(
    detector_id: int,
    volume: int,
) -> dict:
    """Create one synthetic source record for service tests."""

    return {
        "Site ID": 9,
        "detector_id": detector_id,
        "Date  & Time": "2026-10-14T22:45:00+03:00",
        "volume": volume,
        "description": f"Detector {detector_id}",
    }


def test_service_keeps_valid_records_and_reports_invalid_ones() -> None:
    records = [
        make_record(
            detector_id=1,
            volume=40,
        ),
        make_record(
            detector_id=2,
            volume=-5,
        ),
        make_record(
            detector_id=3,
            volume=52,
        ),
    ]

    client = FakeSyntheticTrafficClient(records)

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    result = ingest_synthetic_observations(
        client=client,
        start=start,
        end=end,
    )

    assert result.received_count == 3
    assert result.accepted_count == 2
    assert result.rejected_count == 1

    assert len(result.observations) == 2
    assert len(result.errors) == 1

    assert {
        observation.detector_id
        for observation in result.observations
    } == {
        "1",
        "3",
    }

    error = result.errors[0]

    assert error.record_number == 2
    assert error.site_id == "9"
    assert error.detector_id == "2"
    assert error.source_timestamp == (
        "2026-10-14T22:45:00+03:00"
    )


def test_service_reports_non_object_record() -> None:
    records = [
        make_record(
            detector_id=1,
            volume=40,
        ),
        "not a dictionary",
    ]

    client = FakeSyntheticTrafficClient(records)

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    result = ingest_synthetic_observations(
        client=client,
        start=start,
        end=end,
    )

    assert result.received_count == 2
    assert result.accepted_count == 1
    assert result.rejected_count == 1

    error = result.errors[0]

    assert error.record_number == 2
    assert error.site_id is None
    assert error.detector_id is None
    assert error.source_timestamp is None

    assert "must be an object" in error.message


def test_all_valid_records_are_accepted() -> None:
    records = [
        make_record(
            detector_id=1,
            volume=40,
        ),
        make_record(
            detector_id=2,
            volume=45,
        ),
    ]

    client = FakeSyntheticTrafficClient(records)

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    result = ingest_synthetic_observations(
        client=client,
        start=start,
        end=end,
    )

    assert result.received_count == 2
    assert result.accepted_count == 2
    assert result.rejected_count == 0

    assert len(result.errors) == 0


def test_source_failure_is_not_hidden() -> None:
    class FailingClient:
        def fetch_observations(
            self,
            start: datetime,
            end: datetime,
        ) -> list:
            request = httpx2.Request(
                "GET",
                "http://synthetic-source/observations",
            )

            raise httpx2.ConnectError(
                "source unavailable",
                request=request,
            )

    client = FailingClient()

    start = datetime.fromisoformat(
        "2026-10-14T22:30:00+03:00"
    )
    end = datetime.fromisoformat(
        "2026-10-14T23:00:00+03:00"
    )

    with pytest.raises(httpx2.ConnectError):
        ingest_synthetic_observations(
            client=client,
            start=start,
            end=end,
        )
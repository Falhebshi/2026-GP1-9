from dataclasses import dataclass
from datetime import datetime

import httpx2


class SyntheticTrafficClient:
    """HTTP client for Jaadah's synthetic traffic source."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def fetch_observations(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Fetch synthetic observations for the requested physical traffic window."""

        response = httpx2.get(
            f"{self.base_url}/observations",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=self.timeout_s,
        )

        response.raise_for_status()

        body = response.json()

        observations = body.get("observations")

        if not isinstance(observations, list):
            raise ValueError(
                "synthetic source response must contain an observations list"
            )

        return observations

    def fetch_latest_available_timestamp(self) -> datetime | None:
        """
        Return the end of the latest interval the source has stored,
        or None when it has no observations yet.

        Records are labelled by interval end, so a value of 09:15 means
        that every interval up to 09:00-09:15 is available.
        """

        return _fetch_latest_available_timestamp(
            self.base_url, self.timeout_s, "synthetic source"
        )


def _fetch_latest_available_timestamp(
    base_url: str,
    timeout_s: float,
    label: str,
) -> datetime | None:
    """Read latest_available_timestamp from a source's /health."""

    response = httpx2.get(
        f"{base_url}/health",
        timeout=timeout_s,
    )

    response.raise_for_status()

    body = response.json()

    if "latest_available_timestamp" not in body:
        raise ValueError(
            f"{label} health response must contain "
            "latest_available_timestamp"
        )

    value = body["latest_available_timestamp"]

    if value is None:
        return None

    timestamp = datetime.fromisoformat(value)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(
            "latest_available_timestamp must include timezone information"
        )

    return timestamp


@dataclass(frozen=True)
class RcrcBatch:
    """
    The rows an RCRC source returned for one request, as RCRC wrote
    them, with the site they belong to (RCRC rows do not repeat it).
    """

    site_id: str
    records: list


class RcrcReplayClient:
    """
    HTTP client for an RCRC source: the RCRC replay source today, a live
    RCRC feed with the same API later.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def fetch_observations(
        self,
        start: datetime,
        end: datetime,
    ) -> RcrcBatch:
        """Fetch the RCRC rows whose interval ends after start and by end."""

        response = httpx2.get(
            f"{self.base_url}/observations",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=self.timeout_s,
        )

        response.raise_for_status()

        body = response.json()
        observations = body.get("observations")

        if not isinstance(observations, list):
            raise ValueError(
                "RCRC source response must contain an observations list"
            )

        site_id = body.get("site_id")

        if site_id is None or not str(site_id).strip():
            raise ValueError("RCRC source response must contain a site_id")

        return RcrcBatch(site_id=str(site_id).strip(), records=observations)

    def fetch_latest_available_timestamp(self) -> datetime | None:
        """
        Return the end of the latest interval the source has delivered,
        or None when it has none. An interval at or before this time
        with no rows is missing data, not data still to come.
        """

        return _fetch_latest_available_timestamp(
            self.base_url, self.timeout_s, "RCRC source"
        )

    def fetch_data_window(self) -> tuple[datetime | None, datetime | None]:
        """
        Return the start and end of the data the source holds (data_start
        and data_end in /health), each None when the source does not say.
        Unlike latest_available_timestamp, they do not move with the
        replay clock: a window outside them will never be delivered.
        """

        response = httpx2.get(f"{self.base_url}/health", timeout=self.timeout_s)
        response.raise_for_status()
        body = response.json()
        start, end = body.get("data_start"), body.get("data_end")
        return (
            datetime.fromisoformat(start) if start else None,
            datetime.fromisoformat(end) if end else None,
        )

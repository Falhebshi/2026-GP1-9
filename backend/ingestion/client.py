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

        response = httpx2.get(
            f"{self.base_url}/health",
            timeout=self.timeout_s,
        )

        response.raise_for_status()

        body = response.json()

        if "latest_available_timestamp" not in body:
            raise ValueError(
                "synthetic source health response must contain "
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

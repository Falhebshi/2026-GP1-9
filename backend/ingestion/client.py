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
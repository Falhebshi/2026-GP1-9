from dataclasses import dataclass
from datetime import datetime

from backend.ingestion.adapter import adapt_synthetic_record
from backend.ingestion.client import SyntheticTrafficClient
from jaadah.models.traffic import TrafficObservation


@dataclass(frozen=True)
class IngestionError:
    """Information about one source record that could not be ingested."""

    record_number: int
    message: str
    site_id: str | None = None
    detector_id: str | None = None
    source_timestamp: str | None = None


@dataclass
class IngestionResult:
    """Result of ingesting one batch of source observations."""

    observations: list[TrafficObservation]
    errors: list[IngestionError]

    @property
    def received_count(self) -> int:
        return len(self.observations) + len(self.errors)

    @property
    def accepted_count(self) -> int:
        return len(self.observations)

    @property
    def rejected_count(self) -> int:
        return len(self.errors)


def _optional_text(value: object) -> str | None:
    """Convert a source value to non-empty text when possible."""

    if value is None:
        return None

    text = str(value).strip()

    return text or None


def ingest_synthetic_observations(
    client: SyntheticTrafficClient,
    start: datetime,
    end: datetime,
) -> IngestionResult:
    """
    Fetch and standardize a batch of synthetic traffic observations.

    Valid records are retained while invalid records are reported
    separately.
    """

    records = client.fetch_observations(
        start=start,
        end=end,
    )

    observations: list[TrafficObservation] = []
    errors: list[IngestionError] = []

    for record_number, record in enumerate(
        records,
        start=1,
    ):
        try:
            observation = adapt_synthetic_record(record)

        except ValueError as exc:
            record_data = (
                record
                if isinstance(record, dict)
                else {}
            )

            errors.append(
                IngestionError(
                    record_number=record_number,
                    message=str(exc),
                    site_id=_optional_text(
                        record_data.get("Site ID")
                    ),
                    detector_id=_optional_text(
                        record_data.get("detector_id")
                    ),
                    source_timestamp=_optional_text(
                        record_data.get("Date  & Time")
                    ),
                )
            )

            continue

        observations.append(observation)

    return IngestionResult(
        observations=observations,
        errors=errors,
    )
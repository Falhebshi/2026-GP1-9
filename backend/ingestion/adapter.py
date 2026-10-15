from datetime import datetime, timedelta

from jaadah.models.traffic import (
    TrafficObservation,
    TrafficObservationSource,
)


SYNTHETIC_INTERVAL_MINUTES = 15

SYNTHETIC_REQUIRED_FIELDS = {
    "Site ID",
    "detector_id",
    "Date  & Time",
    "volume",
    "description",
}


def build_observation_id(
    source: TrafficObservationSource,
    site_id: str,
    detector_id: str,
    interval_end: datetime,
) -> str:
    """Create a readable stable ID for one source traffic observation."""

    source_code = {
        TrafficObservationSource.SYNTHETIC: "SYN",
        TrafficObservationSource.RCRC: "RCRC",
    }[source]

    interval_label = interval_end.strftime("%Y%m%dT%H%M")

    return (
        f"OBS_{source_code}_"
        f"{site_id.strip()}_"
        f"{detector_id.strip()}_"
        f"{interval_label}"
    )


def adapt_synthetic_record(
    record: dict,
) -> TrafficObservation:
    """
    Convert one synthetic source record into a standardized
    Jaadah TrafficObservation.
    """

    if not isinstance(record, dict):
        raise ValueError(
            "synthetic source record must be an object"
        )

    missing_fields = (
        SYNTHETIC_REQUIRED_FIELDS - record.keys()
    )

    if missing_fields:
        raise ValueError(
            "synthetic source record is missing required field(s): "
            + ", ".join(sorted(missing_fields))
        )

    if record["Site ID"] is None:
        raise ValueError("Site ID must not be null")

    if record["detector_id"] is None:
        raise ValueError("detector_id must not be null")

    if record["description"] is None:
        raise ValueError("description must not be null")

    site_id = str(record["Site ID"]).strip()
    detector_id = str(record["detector_id"]).strip()

    try:
        interval_end = datetime.fromisoformat(
            str(record["Date  & Time"]).strip()
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Date  & Time must be a valid ISO datetime"
        ) from exc

    if (
        interval_end.minute % SYNTHETIC_INTERVAL_MINUTES != 0
        or interval_end.second != 0
        or interval_end.microsecond != 0
    ):
        raise ValueError(
            "Date  & Time must be aligned to a 15-minute boundary"
        )

    interval_start = interval_end - timedelta(
        minutes=SYNTHETIC_INTERVAL_MINUTES
    )

    description = str(record["description"]).strip()

    if not description:
        raise ValueError("description must not be empty")

    observation_id = build_observation_id(
        source=TrafficObservationSource.SYNTHETIC,
        site_id=site_id,
        detector_id=detector_id,
        interval_end=interval_end,
    )

    return TrafficObservation(
        observation_id=observation_id,
        source=TrafficObservationSource.SYNTHETIC,
        site_id=site_id,
        detector_id=detector_id,
        interval_start=interval_start,
        interval_end=interval_end,
        vehicle_count=record["volume"],
        description=description,
        average_speed_kmh=None,
        travel_time_s=None,
    )
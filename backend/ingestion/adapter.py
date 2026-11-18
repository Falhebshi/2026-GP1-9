import math
import re
from datetime import datetime, timedelta, timezone

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

# ============================================================
# RCRC
# ============================================================

RCRC_INTERVAL_MINUTES = 15

RCRC_TIME_FORMAT = "%b %d, %Y %H:%M:%S"

RCRC_RIYADH = timezone(timedelta(hours=3))

RCRC_DETECTOR_FIELD = "Detector ID : Description"
RCRC_TIME_FIELD = "Time Stamp"
RCRC_VOLUME_FIELD = "Volume (Vehicles)"
RCRC_OCCUPANCY_S_FIELD = "Occupancy (Seconds)"
RCRC_OCCUPANCY_PERCENT_FIELD = "Occupancy (Percent)"

RCRC_REQUIRED_FIELDS = {
    RCRC_DETECTOR_FIELD,
    RCRC_TIME_FIELD,
    RCRC_VOLUME_FIELD,
    RCRC_OCCUPANCY_S_FIELD,
    RCRC_OCCUPANCY_PERCENT_FIELD,
}

_WHOLE_NUMBER = re.compile(r"\d+")


def parse_rcrc_detector(value) -> tuple[str, str]:
    """
    Split an RCRC "Detector ID : Description" value, for example
    "144409: P2-NB-L1-L-STB-RP2", into the ID and the description.
    """

    if not isinstance(value, str) or ":" not in value:
        raise ValueError(
            f"{RCRC_DETECTOR_FIELD} must be '<ID>: <description>', got {value!r}"
        )

    detector_id, description = (part.strip() for part in value.split(":", 1))

    if not _WHOLE_NUMBER.fullmatch(detector_id):
        raise ValueError(f"detector ID must be a whole number, got {detector_id!r}")

    if not description:
        raise ValueError("detector description must not be empty")

    return detector_id, description


def parse_rcrc_interval_end(value) -> datetime:
    """
    Read an RCRC time stamp as the end of a Riyadh-time interval.

    RCRC time stamps have no timezone. Reading them as interval ends is
    the convention of the RCRC sample analysis; RCRC has not confirmed
    it (see docs/traffic_ingestion.md).
    """

    try:
        moment = datetime.strptime(str(value).strip(), RCRC_TIME_FORMAT)
    except ValueError as exc:
        raise ValueError(
            f"{RCRC_TIME_FIELD} must look like 'Jul 13, 2026 00:15:00', got {value!r}"
        ) from exc

    if moment.minute % RCRC_INTERVAL_MINUTES or moment.second:
        raise ValueError(
            f"{RCRC_TIME_FIELD} must be on a 15-minute boundary, got {value!r}"
        )

    return moment.replace(tzinfo=RCRC_RIYADH)


def _rcrc_whole_number(record: dict, field: str) -> int:
    value = record[field]

    if isinstance(value, bool) or not _WHOLE_NUMBER.fullmatch(str(value).strip()):
        raise ValueError(f"{field} must be a non-negative whole number, got {value!r}")

    return int(str(value).strip())


def _rcrc_optional_number(record: dict, field: str) -> float | None:
    value = record[field]

    if value is None or str(value).strip() == "":
        return None

    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number, got {value!r}")

    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc

    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a non-negative number, got {value!r}")

    return number


def adapt_rcrc_record(
    record: dict,
    site_id: str,
) -> TrafficObservation:
    """
    Convert one RCRC row, as RCRC wrote it, into a standardized Jaadah
    TrafficObservation. RCRC rows do not name their site; the site comes
    from the response the row arrived in.
    """

    if not isinstance(record, dict):
        raise ValueError("RCRC record must be an object")

    missing_fields = RCRC_REQUIRED_FIELDS - record.keys()

    if missing_fields:
        raise ValueError(
            "RCRC record is missing required field(s): "
            + ", ".join(sorted(missing_fields))
        )

    detector_id, description = parse_rcrc_detector(record[RCRC_DETECTOR_FIELD])
    interval_end = parse_rcrc_interval_end(record[RCRC_TIME_FIELD])

    return TrafficObservation(
        observation_id=build_observation_id(
            source=TrafficObservationSource.RCRC,
            site_id=site_id,
            detector_id=detector_id,
            interval_end=interval_end,
        ),
        source=TrafficObservationSource.RCRC,
        site_id=site_id,
        detector_id=detector_id,
        interval_start=interval_end - timedelta(minutes=RCRC_INTERVAL_MINUTES),
        interval_end=interval_end,
        vehicle_count=_rcrc_whole_number(record, RCRC_VOLUME_FIELD),
        description=description,
        occupancy_s=_rcrc_optional_number(record, RCRC_OCCUPANCY_S_FIELD),
        occupancy_percent=_rcrc_optional_number(record, RCRC_OCCUPANCY_PERCENT_FIELD),
    )

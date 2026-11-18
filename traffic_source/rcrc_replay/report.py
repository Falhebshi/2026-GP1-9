"""
Reading RCRC "Intersection historical data report" CSV exports.

The first row is a title holding the site ID, the report period and the
aggregation interval. Every detector block then starts with the same
column header row:

    Detector ID : Description, Time Stamp, Volume (Vehicles),
    Occupancy (Seconds), Occupancy (Percent)

The replay source keeps the rows exactly as RCRC wrote them and serves
them unchanged. It only reads the time stamp to know when to release a
row. Interpreting the values is Jaadah's job, in its RCRC ingestion
adapter.
"""

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from traffic_source.rcrc_replay.config import INTERVAL_MINUTES, RIYADH


RCRC_COLUMNS = (
    "Detector ID : Description",
    "Time Stamp",
    "Volume (Vehicles)",
    "Occupancy (Seconds)",
    "Occupancy (Percent)",
)

RCRC_TIME_FORMAT = "%b %d, %Y %H:%M:%S"

_SITE_PATTERN = re.compile(r"report for\s*:\s*(\d+)", re.IGNORECASE)
_INTERVAL_PATTERN = re.compile(r"Aggregation Interval\s*:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ReportRow:
    """One data row as RCRC wrote it, with the interval end it labels."""

    row_number: int
    values: dict[str, str]
    interval_end: datetime | None


@dataclass(frozen=True)
class RcrcReport:
    """One RCRC report file."""

    site_id: str
    title: str
    sha256: str
    rows: list[ReportRow] = field(default_factory=list)
    repeated_header_count: int = 0

    @property
    def undated_rows(self) -> list[ReportRow]:
        return [row for row in self.rows if row.interval_end is None]


def _clean_row(row: list[str]) -> tuple[str, ...]:
    values = [value.strip() for value in row]

    while values and not values[-1]:
        values.pop()

    return tuple(values)


def parse_time_stamp(value: str) -> datetime | None:
    """
    Read an RCRC time stamp as Riyadh time, or None when it cannot be
    read or is not on a 15-minute boundary.
    """

    try:
        moment = datetime.strptime(value.strip(), RCRC_TIME_FORMAT)
    except ValueError:
        return None

    if moment.minute % INTERVAL_MINUTES or moment.second:
        return None

    return moment.replace(tzinfo=RIYADH)


def read_rcrc_report(path: str | Path) -> RcrcReport:
    """
    Read an RCRC report file.

    A file that is not a readable 15-minute RCRC report raises
    ValueError: no title, no site ID, another aggregation interval, an
    unexpected column header, or a row with more columns than the
    header. Repeated header rows and blank rows are skipped. Rows are
    kept as written; a row whose time stamp cannot be read keeps
    interval_end None and is never released by the replay.
    """

    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(text.splitlines(keepends=True)))

    if not rows or not rows[0] or not rows[0][0].strip():
        raise ValueError("RCRC report has no title row")

    title = rows[0][0].strip()
    site_match = _SITE_PATTERN.search(title)

    if site_match is None:
        raise ValueError("RCRC report title does not name a site ID")

    interval_match = _INTERVAL_PATTERN.search(title)

    if interval_match is None:
        raise ValueError("RCRC report title does not give the aggregation interval")

    if int(interval_match.group(1)) != INTERVAL_MINUTES:
        raise ValueError(
            f"RCRC report uses {interval_match.group(1)}-minute intervals; "
            f"only {INTERVAL_MINUTES}-minute reports are supported"
        )

    if len(rows) < 2 or _clean_row(rows[1]) != RCRC_COLUMNS:
        raise ValueError(
            "RCRC report does not have the expected column header: "
            + ", ".join(RCRC_COLUMNS)
        )

    report_rows = []
    repeated_headers = 0

    for line_number, row in enumerate(rows[2:], start=3):
        cleaned = _clean_row(row)

        if not any(cleaned):
            continue

        if cleaned == RCRC_COLUMNS:
            repeated_headers += 1
            continue

        if len(cleaned) > len(RCRC_COLUMNS):
            raise ValueError(
                f"RCRC report line {line_number} has more values than its columns"
            )

        values = {
            column: (row[index].strip() if index < len(row) else "")
            for index, column in enumerate(RCRC_COLUMNS)
        }
        report_rows.append(
            ReportRow(
                row_number=len(report_rows) + 1,
                values=values,
                interval_end=parse_time_stamp(values["Time Stamp"]),
            )
        )

    return RcrcReport(
        site_id=site_match.group(1),
        title=title,
        sha256=hashlib.sha256(raw).hexdigest(),
        rows=report_rows,
        repeated_header_count=repeated_headers,
    )

"""
SQLite storage of the RCRC replay source.

Holds the report rows exactly as RCRC wrote them and a record of the
loaded report. Only this class touches the database, so
moving the source to another database later changes this file only.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from traffic_source.rcrc_replay.report import RCRC_COLUMNS, RcrcReport


_COLUMN_FIELDS = {
    "Detector ID : Description": "detector",
    "Time Stamp": "time_stamp",
    "Volume (Vehicles)": "volume",
    "Occupancy (Seconds)": "occupancy_s",
    "Occupancy (Percent)": "occupancy_percent",
}


class RcrcReplayStorage:
    """Store an RCRC report and serve its rows by interval end."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the database folder and tables if needed."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS report (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    site_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    first_interval_end TEXT,
                    last_interval_end TEXT
                );

                CREATE TABLE IF NOT EXISTS report_rows (
                    row_number INTEGER PRIMARY KEY,
                    detector TEXT NOT NULL,
                    time_stamp TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    occupancy_s TEXT NOT NULL,
                    occupancy_percent TEXT NOT NULL,
                    interval_end TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_report_rows_interval_end
                ON report_rows(interval_end);
                """
            )

    # ------------------------------------------------------------
    # Report
    # ------------------------------------------------------------

    def load_report(self, report: RcrcReport) -> bool:
        """
        Store a report. Loading the same file again changes nothing and
        returns False. A different report replaces the stored one.
        """

        stored = self.get_report_info()

        if stored is not None and stored["sha256"] == report.sha256:
            return False

        dated = [row.interval_end for row in report.rows if row.interval_end]

        with self._connect() as connection:
            connection.execute("DELETE FROM report_rows")
            connection.execute("DELETE FROM report")
            connection.execute(
                """
                INSERT INTO report (
                    id, site_id, title, sha256, row_count,
                    first_interval_end, last_interval_end
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.site_id,
                    report.title,
                    report.sha256,
                    len(report.rows),
                    min(dated).isoformat() if dated else None,
                    max(dated).isoformat() if dated else None,
                ),
            )
            connection.executemany(
                """
                INSERT INTO report_rows (
                    row_number, detector, time_stamp, volume,
                    occupancy_s, occupancy_percent, interval_end
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.row_number,
                        *(row.values[column] for column in RCRC_COLUMNS),
                        row.interval_end.isoformat() if row.interval_end else None,
                    )
                    for row in report.rows
                ],
            )

        return True

    def get_report_info(self) -> dict | None:
        """The stored report's site, title, fingerprint and data period."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT site_id, title, sha256, row_count,
                       first_interval_end, last_interval_end
                FROM report WHERE id = 1
                """
            ).fetchone()

        if row is None:
            return None

        site_id, title, sha256, row_count, first, last = row

        return {
            "site_id": site_id,
            "title": title,
            "sha256": sha256,
            "row_count": row_count,
            "first_interval_end": datetime.fromisoformat(first) if first else None,
            "last_interval_end": datetime.fromisoformat(last) if last else None,
        }

    def get_rows(self, after: datetime, through: datetime) -> list[dict]:
        """
        Return the rows whose interval end is after `after` and at or
        before `through`, as RCRC wrote them, in report order within
        each interval.
        """

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT detector, time_stamp, volume, occupancy_s, occupancy_percent
                FROM report_rows
                WHERE interval_end > ? AND interval_end <= ?
                ORDER BY interval_end, row_number
                """,
                (after.isoformat(), through.isoformat()),
            ).fetchall()

        return [dict(zip(RCRC_COLUMNS, row)) for row in rows]

    def get_detectors(self) -> list[str]:
        """The distinct "Detector ID : Description" values, sorted."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT detector FROM report_rows ORDER BY detector"
            ).fetchall()

        return [row[0] for row in rows]

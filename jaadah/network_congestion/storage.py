"""
Store the network map's speeds, one row per 15-minute interval.

Built like the synthetic traffic source's storage
(traffic_source/synthetic/storage.py): a local SQLite database that
the producer fills and the server reads. Each row is one interval of
the whole city: its start and end, the network speed for the
timeline, and every segment's speed (percent of free flow) as a JSON
list in the order of road_segments.json.

One row per interval, not per segment: the page always shows one
interval of the whole city, and 14,747 segments x 96 intervals a day
would be about 10 million rows a week.

The database is not committed (see .gitignore): its values are shaped
by the RCRC measures.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jaadah.network_congestion.segments import REPO_ROOT

DEFAULT_DATABASE = REPO_ROOT / "data/network_congestion/network_speeds.db"

# Times are stored as text in Riyadh time, so they sort and compare in
# time order
RIYADH = ZoneInfo("Asia/Riyadh")


@dataclass(frozen=True)
class IntervalSpeeds:
    """The speeds of the whole city in one 15-minute interval."""

    interval_start: datetime
    interval_end: datetime
    network_speed: float
    speeds: list[int]       # one per segment, in road_segments.json order


@dataclass(frozen=True)
class SourceMetadata:
    """
    What the stored values were built from.

    inputs is a fingerprint (SHA-256) of the segment IDs and the RCRC
    measures, so values built from other inputs are never mixed in. It
    does not reveal the measures.
    """

    seed: int
    interval_minutes: int
    timezone: str
    inputs: str


def _riyadh_text(moment: datetime) -> str:
    """Return a time as Riyadh-time text; it must include a timezone."""

    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("stored times must include a timezone")

    return moment.astimezone(RIYADH).isoformat()


class NetworkSpeedStorage:
    """Store and read the network map's 15-minute speeds."""

    def __init__(self, database_path: Path = DEFAULT_DATABASE) -> None:
        self.database_path = database_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open and safely close a database connection."""

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interval_speeds (
                    interval_start TEXT PRIMARY KEY,
                    interval_end TEXT NOT NULL,
                    network_speed REAL NOT NULL,
                    speeds TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    seed INTEGER NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    timezone TEXT NOT NULL,
                    inputs TEXT NOT NULL
                )
                """
            )

    def ensure_source_metadata(self, metadata: SourceMetadata) -> None:
        """Store the source settings, or check them against the stored ones."""

        expected = (
            metadata.seed,
            metadata.interval_minutes,
            metadata.timezone,
            metadata.inputs,
        )

        with self._connect() as connection:
            stored = connection.execute(
                """
                SELECT seed, interval_minutes, timezone, inputs
                FROM source_metadata
                WHERE id = 1
                """
            ).fetchone()

            if stored is None:
                connection.execute(
                    """
                    INSERT INTO source_metadata
                        (id, seed, interval_minutes, timezone, inputs)
                    VALUES (1, ?, ?, ?, ?)
                    """,
                    expected,
                )
                return

        if stored != expected:
            raise ValueError(
                f"{self.database_path} was built from other inputs (seed, "
                "segments or RCRC measures changed). Delete it and start "
                "the server again to rebuild the last 7 days."
            )

    def insert_intervals(self, intervals: list[IntervalSpeeds]) -> None:
        """Store a batch of intervals."""

        rows = []

        for interval in intervals:
            rows.append((
                _riyadh_text(interval.interval_start),
                _riyadh_text(interval.interval_end),
                interval.network_speed,
                json.dumps(interval.speeds, separators=(",", ":")),
            ))

        if not rows:
            return

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO interval_speeds
                    (interval_start, interval_end, network_speed, speeds)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

    def delete_before(self, cutoff: datetime) -> int:
        """Delete the intervals that start before cutoff; return how many."""

        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM interval_speeds WHERE interval_start < ?",
                (_riyadh_text(cutoff),),
            )

        return cursor.rowcount

    def get_latest_end(self) -> datetime | None:
        """Return the end of the newest stored interval."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(interval_end) FROM interval_speeds"
            ).fetchone()

        if row is None or row[0] is None:
            return None

        return datetime.fromisoformat(row[0])

    def get_interval(self, moment: datetime | None = None) -> IntervalSpeeds | None:
        """
        Return the interval that contains moment (start <= moment < end),
        or the newest interval when moment is None. None if not stored.
        """

        if moment is None:
            query = """
                SELECT interval_start, interval_end, network_speed, speeds
                FROM interval_speeds
                ORDER BY interval_start DESC
                LIMIT 1
            """
            parameters = ()
        else:
            text = _riyadh_text(moment)
            query = """
                SELECT interval_start, interval_end, network_speed, speeds
                FROM interval_speeds
                WHERE interval_start <= ? AND interval_end > ?
            """
            parameters = (text, text)

        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()

        if row is None:
            return None

        start, end, network_speed, speeds = row

        return IntervalSpeeds(
            interval_start=datetime.fromisoformat(start),
            interval_end=datetime.fromisoformat(end),
            network_speed=network_speed,
            speeds=json.loads(speeds),
        )

    def get_network_speeds(
        self,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime, float]]:
        """Return (start, end, network speed) of the intervals in [start, end)."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT interval_start, interval_end, network_speed
                FROM interval_speeds
                WHERE interval_start >= ? AND interval_start < ?
                ORDER BY interval_start
                """,
                (_riyadh_text(start), _riyadh_text(end)),
            ).fetchall()

        return [
            (datetime.fromisoformat(a), datetime.fromisoformat(b), speed)
            for a, b, speed in rows
        ]

    def get_days(self) -> list[str]:
        """Return the dates (YYYY-MM-DD) with stored intervals, oldest first."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT substr(interval_start, 1, 10)
                FROM interval_speeds
                ORDER BY 1
                """
            ).fetchall()

        return [row[0] for row in rows]

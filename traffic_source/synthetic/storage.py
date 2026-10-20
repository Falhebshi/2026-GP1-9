import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from traffic_source.synthetic.config import (
    SyntheticSourceConfig,
)
from traffic_source.synthetic.generator import (
    SyntheticDetectorObservation,
)


class SyntheticTrafficStorage:
    """Store and retrieve persistent synthetic traffic observations."""

    def __init__(self, database_path: Path) -> None:
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
        """Create the database directory and required tables if needed."""

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    site_id INTEGER NOT NULL,
                    detector_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    volume INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    PRIMARY KEY (
                        site_id,
                        detector_id,
                        timestamp
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    seed INTEGER NOT NULL,
                    scenario TEXT NOT NULL,
                    variation_scale REAL NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    timezone TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_observations_timestamp
                ON observations(timestamp)
                """
            )

    def ensure_source_metadata(
        self,
        config: SyntheticSourceConfig,
    ) -> None:
        """Store the source configuration or verify the existing one."""

        expected = (
            config.seed,
            config.scenario,
            config.variation_scale,
            config.interval_minutes,
            config.timezone,
        )

        with self._connect() as connection:
            stored = connection.execute(
                """
                SELECT
                    seed,
                    scenario,
                    variation_scale,
                    interval_minutes,
                    timezone
                FROM source_metadata
                WHERE id = 1
                """
            ).fetchone()

            if stored is None:
                connection.execute(
                    """
                    INSERT INTO source_metadata (
                        id,
                        seed,
                        scenario,
                        variation_scale,
                        interval_minutes,
                        timezone
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (1, *expected),
                )
                return

            if stored != expected:
                raise ValueError(
                    "The existing synthetic traffic database was created "
                    "with a different source configuration."
                )

    def insert_observations(
        self,
        observations: list[SyntheticDetectorObservation],
    ) -> None:
        """Store a batch of synthetic traffic observations."""

        if not observations:
            return

        rows: list[
            tuple[int, int, str, int, str]
        ] = []

        for observation in observations:
            if (
                observation.timestamp.tzinfo is None
                or observation.timestamp.utcoffset() is None
            ):
                raise ValueError(
                    "Stored observation timestamps must include a timezone."
                )

            rows.append(
                (
                    observation.site_id,
                    observation.detector_id,
                    observation.timestamp.isoformat(),
                    observation.volume,
                    observation.description,
                )
            )

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO observations (
                    site_id,
                    detector_id,
                    timestamp,
                    volume,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_latest_timestamp(self) -> datetime | None:
        """Return the newest stored observation timestamp."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(timestamp)
                FROM observations
                """
            ).fetchone()

        if row is None or row[0] is None:
            return None

        return datetime.fromisoformat(row[0])

    def get_observations(
        self,
        start: datetime,
        end: datetime,
        detector_ids: list[int] | None = None,
    ) -> list[SyntheticDetectorObservation]:
        """
        Return stored observations for a physical traffic-coverage window.

        Record timestamps label the end of each observation interval, so
        observations are returned when start < timestamp <= end.
        """

        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
        ):
            raise ValueError(
                "Observation query timestamps must include a timezone."
            )

        if end <= start:
            raise ValueError(
                "end must be later than start"
            )

        query = """
            SELECT
                site_id,
                detector_id,
                timestamp,
                volume,
                description
            FROM observations
            WHERE timestamp > ?
              AND timestamp <= ?
        """

        parameters: list[str | int] = [
            start.isoformat(),
            end.isoformat(),
        ]

        if detector_ids is not None:
            selected_detector_ids = sorted(
                {
                    int(detector_id)
                    for detector_id in detector_ids
                }
            )

            if not selected_detector_ids:
                return []

            placeholders = ", ".join(
                "?"
                for _ in selected_detector_ids
            )

            query += (
                f" AND detector_id IN ({placeholders})"
            )

            parameters.extend(
                selected_detector_ids
            )

        query += """
            ORDER BY
                timestamp ASC,
                detector_id ASC
        """

        with self._connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        return [
            SyntheticDetectorObservation(
                site_id=site_id,
                detector_id=detector_id,
                timestamp=datetime.fromisoformat(
                    timestamp
                ),
                volume=volume,
                description=description,
            )
            for (
                site_id,
                detector_id,
                timestamp,
                volume,
                description,
            ) in rows
        ]

    def get_observation_count(self) -> int:
        """Return the total number of stored observations."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM observations
                """
            ).fetchone()

        return int(row[0])
from datetime import date, datetime, time, timedelta
from threading import Event
from zoneinfo import ZoneInfo

from traffic_source.synthetic.config import (
    INITIAL_HISTORY_DAYS,
    SyntheticSourceConfig,
)
from traffic_source.synthetic.generator import (
    SyntheticDetectorObservation,
    SyntheticTrafficGenerator,
)
from traffic_source.synthetic.storage import (
    SyntheticTrafficStorage,
)


def _daily_random_seed(
    base_seed: int,
    day: date,
) -> int:
    """Derive reproducible randomness for one interval-start traffic day."""

    return (
        base_seed * 100_000_000
        + int(day.strftime("%Y%m%d"))
    )


def latest_completed_interval(
    now: datetime,
    config: SyntheticSourceConfig,
) -> datetime:
    """Return the latest completed source interval boundary."""

    timezone = ZoneInfo(config.timezone)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    interval_minutes = config.interval_minutes

    completed_minute = (
        now.minute // interval_minutes
    ) * interval_minutes

    return now.replace(
        minute=completed_minute,
        second=0,
        microsecond=0,
    )


def next_interval_boundary(
    now: datetime,
    config: SyntheticSourceConfig,
) -> datetime:
    """Return the next source interval boundary."""

    timezone = ZoneInfo(config.timezone)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    current_boundary = latest_completed_interval(
        now=now,
        config=config,
    )

    return current_boundary + timedelta(
        minutes=config.interval_minutes
    )


class SyntheticTrafficProducer:
    """Generate and persist missing synthetic traffic observations."""

    def __init__(
        self,
        generator: SyntheticTrafficGenerator,
        storage: SyntheticTrafficStorage,
        config: SyntheticSourceConfig,
    ) -> None:
        self.generator = generator
        self.storage = storage
        self.config = config

    def synchronize(
        self,
        now: datetime | None = None,
    ) -> int:
        """Generate all observations missing up to the latest completed interval."""

        timezone = ZoneInfo(
            self.config.timezone
        )

        if now is None:
            now = datetime.now(timezone)

        cutoff = latest_completed_interval(
            now=now,
            config=self.config,
        )

        latest = (
            self.storage.get_latest_timestamp()
        )

        if latest is None:
            start = cutoff - timedelta(
                days=INITIAL_HISTORY_DAYS
            )
        else:
            start = latest

        if start >= cutoff:
            return 0

        observations = self._generate_window(
            start_exclusive=start,
            end_inclusive=cutoff,
        )

        self.storage.insert_observations(
            observations
        )

        return len(observations)

    def _generate_window(
        self,
        start_exclusive: datetime,
        end_inclusive: datetime,
    ) -> list[SyntheticDetectorObservation]:
        """Replay each traffic day from its first interval-end record.

        A traffic day's last record is the following midnight. Replaying its
        full prefix preserves state when only a later suffix needs recovery.
        """

        timezone = ZoneInfo(
            self.config.timezone
        )

        start_exclusive = (
            start_exclusive.astimezone(timezone)
        )

        end_inclusive = (
            end_inclusive.astimezone(timezone)
        )

        interval = timedelta(
            minutes=self.config.interval_minutes
        )

        first_missing = (
            start_exclusive + interval
        )

        current_day = (first_missing - interval).date()
        last_day = (end_inclusive - interval).date()

        generated: list[
            SyntheticDetectorObservation
        ] = []

        while current_day <= last_day:
            day_start = datetime.combine(
                current_day,
                time.min,
                tzinfo=timezone,
            )

            day_last_timestamp = (
                day_start
                + timedelta(days=1)
            )

            generation_end = min(
                day_last_timestamp,
                end_inclusive,
            )

            self.generator.reset(
                seed=_daily_random_seed(
                    self.config.seed,
                    current_day,
                )
            )

            timestamp = day_start + interval

            while timestamp <= generation_end:
                observations = (
                    self.generator.generate_timestamp(
                        timestamp
                    )
                )

                if timestamp > start_exclusive:
                    generated.extend(
                        observations
                    )

                timestamp += interval

            current_day += timedelta(days=1)

        return generated

    def run_forever(
        self,
        stop_event: Event,
    ) -> None:
        """Keep stored observations synchronized with completed intervals."""

        timezone = ZoneInfo(
            self.config.timezone
        )

        self.synchronize()

        while not stop_event.is_set():
            now = datetime.now(timezone)

            next_boundary = next_interval_boundary(
                now=now,
                config=self.config,
            )

            wait_seconds = max(
                (
                    next_boundary
                    - now
                ).total_seconds(),
                0.0,
            )

            should_stop = stop_event.wait(
                wait_seconds
            )

            if should_stop:
                break

            self.synchronize()

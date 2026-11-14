"""
Keep the network map's speeds up to date, 15 minutes at a time.

Works like the synthetic traffic source's producer
(traffic_source/synthetic/producer.py):

- on the first start, it fills today up to the latest completed 15
  minutes and the 6 whole days before (7 dates on the page);
- then it wakes at every 15-minute boundary and adds only the interval
  that has just finished, never one in the future;
- after a restart, it fills only the missing intervals.

The values do not depend on when they are made: the same date, slot
and seed always give the same speed (synthetic.py). Intervals before
those 7 dates are deleted, so the database stays about one week.
"""

import hashlib
from datetime import datetime, timedelta
from threading import Event

from jaadah.network_congestion.parameters import (
    HISTORY_DAYS,
    INTERVAL_S,
    SEED,
)
from jaadah.network_congestion.storage import (
    RIYADH,
    IntervalSpeeds,
    NetworkSpeedStorage,
    SourceMetadata,
)
from jaadah.network_congestion.synthetic import (
    City,
    CityDay,
    city_day,
    interval_speeds,
)

INTERVAL = timedelta(seconds=INTERVAL_S)


def latest_completed_interval(now: datetime) -> datetime:
    """Return the end of the latest completed 15 minutes (Riyadh time)."""

    now = now.astimezone(RIYADH)
    minutes = INTERVAL_S // 60

    return now.replace(
        minute=now.minute // minutes * minutes,
        second=0,
        microsecond=0,
    )


def next_interval_boundary(now: datetime) -> datetime:
    """Return the next 15-minute boundary (Riyadh time)."""

    return latest_completed_interval(now) + INTERVAL


def source_metadata(city: City) -> SourceMetadata:
    """Return the settings and input fingerprint the values are built from."""

    fingerprint = hashlib.sha256()
    fingerprint.update(str(SEED).encode())
    fingerprint.update(",".join(s.segment_id for s in city.segments).encode())
    fingerprint.update(repr(city.measures).encode())

    return SourceMetadata(
        seed=SEED,
        interval_minutes=INTERVAL_S // 60,
        timezone=str(RIYADH),
        inputs=fingerprint.hexdigest(),
    )


class NetworkSpeedProducer:
    """Generate and store the missing 15-minute intervals."""

    def __init__(self, city: City, storage: NetworkSpeedStorage) -> None:
        self.city = city
        self.storage = storage
        self._day: CityDay | None = None

    def _city_day(self, start: datetime) -> CityDay:
        """Return the day of an interval, keeping the current one in memory."""

        if self._day is None or self._day.day != start.date():
            self._day = city_day(self.city, start.date())

        return self._day

    def interval(self, start: datetime) -> IntervalSpeeds:
        """Return the speeds of the interval that starts at start."""

        start = start.astimezone(RIYADH)
        slot = (start.hour * 3600 + start.minute * 60) // INTERVAL_S
        speeds, network_speed = interval_speeds(
            self.city, self._city_day(start), slot,
        )

        return IntervalSpeeds(
            interval_start=start,
            interval_end=start + INTERVAL,
            network_speed=network_speed,
            speeds=speeds,
        )

    def synchronize(self, now: datetime | None = None) -> int:
        """
        Store every interval missing up to the latest completed one, and
        delete the ones before the 7 dates kept. Returns how many were added.
        """

        cutoff = latest_completed_interval(now or datetime.now(RIYADH))
        # whole days: from midnight 6 days ago, so the page lists 7 dates
        first_day = cutoff.date() - timedelta(days=HISTORY_DAYS - 1)
        oldest = datetime(first_day.year, first_day.month, first_day.day,
                          tzinfo=RIYADH)
        latest = self.storage.get_latest_end()
        start = oldest if latest is None or latest < oldest else latest

        added = 0
        batch = []

        while start + INTERVAL <= cutoff:
            batch.append(self.interval(start))
            start += INTERVAL

            # one day at a time, so a long gap does not sit in memory
            if len(batch) == 96:
                self.storage.insert_intervals(batch)
                added += len(batch)
                batch = []

        self.storage.insert_intervals(batch)
        added += len(batch)
        self.storage.delete_before(oldest)

        return added

    def run_forever(self, stop_event: Event) -> None:
        """Keep the stored intervals up to date until stop_event is set."""

        self.synchronize()

        while not stop_event.is_set():
            now = datetime.now(RIYADH)
            wait_s = max((next_interval_boundary(now) - now).total_seconds(), 0)

            if stop_event.wait(wait_s):
                break

            self.synchronize()

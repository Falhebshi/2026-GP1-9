"""
Keep the network map's speeds up to date, 15 minutes at a time.

Two producers: ObservedSpeedProducer works the speeds out from the RCRC
counts at the study intersection (observed.py) and follows the RCRC
source's clock; NetworkSpeedProducer generates them (synthetic.py)
and follows the computer's clock. Both work like the synthetic traffic
source's producer (traffic_source/synthetic/producer.py):

- on the first start, it fills the latest day up to the latest
  completed 15 minutes and the 6 whole days before (7 dates on the
  page);
- then it wakes at every 15-minute boundary and adds only the interval
  that has just finished, never one in the future;
- after a restart, it fills only the missing intervals.

The values do not depend on when they are made: the same counts, or
the same date, slot and seed, always give the same speed. Intervals
before those 7 dates are deleted, so the database stays about one week.
"""

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event

from backend.demand.service import build_simulation_demand
from backend.ingestion.client import RcrcReplayClient
from backend.ingestion.service import ingest_rcrc_observations
from jaadah.network_congestion.observed import (
    BPR_ALPHA,
    BPR_BETA,
    DEFAULT_HOURLY_VC,
    DEFAULT_WEEKEND_HOURLY_VC,
    DEFAULT_MAPPING_PATH,
    DEFAULT_NETWORK_PATH,
    MAX_VOLUME_TO_CAPACITY,
    ObservedModel,
    SiteInputs,
    build_model,
    day_factors,
    load_road_network,
    load_site_inputs,
    site_levels,
)
from jaadah.network_congestion.observed import (
    interval_speeds as observed_interval_speeds,
)
from jaadah.network_congestion.parameters import (
    CALIBRATION_START,
    CALIBRATION_WEEKS,
    DAY_FACTOR_LIMITS,
    EVENING_DEMAND_FROM_HOUR,
    HISTORY_DAYS,
    IMPUTATION_HISTORY_DAYS,
    INTERVAL_S,
    MORNING_DEMAND_UNTIL_HOUR,
    NETWORK_SPREAD,
    SEED,
    TIMELINE_SLOWEST_SHARE,
    TOMTOM_CONGESTION_LEVEL_PERCENT,
    TOMTOM_HOURS,
    TOMTOM_TRAVEL_TIME_10KM_S,
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
    """
    Return the settings and input fingerprint the values are built from.

    The fingerprint covers everything a stored speed depends on: the
    seed, the segments, the corridor factors (so the demand too), the
    RCRC measures, the TomTom table and the morning/evening hours. If
    any of them changes, old rows would no longer match new ones.
    """

    fingerprint = hashlib.sha256()

    for part in (
        SEED,
        ",".join(s.segment_id for s in city.segments),
        sorted(city.factors.items()),
        city.measures,
        TOMTOM_HOURS,
        sorted(TOMTOM_TRAVEL_TIME_10KM_S.items()),
        (MORNING_DEMAND_UNTIL_HOUR, EVENING_DEMAND_FROM_HOUR),
    ):
        fingerprint.update(repr(part).encode())

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

        keep_up_to_date(self.synchronize, stop_event)


def keep_up_to_date(synchronize: Callable[[], int], stop_event: Event) -> None:
    """Synchronize now and at every 15-minute boundary until stop_event is set."""

    synchronize()

    while not stop_event.is_set():
        now = datetime.now(RIYADH)
        wait_s = max((next_interval_boundary(now) - now).total_seconds(), 0)

        if stop_event.wait(wait_s):
            break

        synchronize()


# ============================================================
# FROM THE RCRC COUNTS (observed.py)
# ============================================================

def observed_site_levels(
    client: RcrcReplayClient,
    site: SiteInputs,
    start: datetime,
    end: datetime,
    history_days: int = IMPUTATION_HISTORY_DAYS,
) -> dict[datetime, float]:
    """
    The study intersection's critical v/c in every interval from start
    to end, from the source's counts through ingestion and demand
    building, as the baseline runner does (run_baseline.py): the days
    before start are used to estimate missing detectors. At the start of
    the data there are no days before, so the window's own counts are
    used. Rejected rows are left out, and an interval whose demand
    cannot be built has no v/c, so the map shows no data for it.
    """

    observations = ingest_rcrc_observations(
        client, start=start - timedelta(days=history_days), end=end,
    ).observations
    window = [o for o in observations if o.interval_start >= start]
    history = [o for o in observations if o.interval_start < start] or window

    demand = build_simulation_demand(
        window,
        history=history,
        window_start=start,
        window_end=end,
        available_until=end,
    )

    return {
        moment: level
        for moment, level in site_levels(site, demand.demands).items()
        if level is not None
    }


def load_observed_model(client: RcrcReplayClient) -> ObservedModel:
    """
    Read the intersection and the road network, and take the
    intersection's usual v/c from the calibration weeks of the source's
    counts (parameters.py).
    """

    start = CALIBRATION_START
    end = start + timedelta(weeks=CALIBRATION_WEEKS)
    latest = client.fetch_latest_available_timestamp()

    if latest is None or latest < end:
        raise RuntimeError(
            f"the RCRC source must reach {end.isoformat()} for the network "
            f"map (latest: {latest.isoformat() if latest else 'none'}); "
            "start the RCRC replay first"
        )

    site = load_site_inputs()
    levels = observed_site_levels(client, site, start, end)

    return build_model(site, load_road_network(), levels, NETWORK_SPREAD)


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_source_metadata(model: ObservedModel) -> SourceMetadata:
    """
    Return the settings and input fingerprint the observed values are
    built from: the segments and their rank offsets (so the demand
    model too), the spread, the intersection's usual v/c, the day factor
    limits, the TomTom table, the speed function, the calibration weeks
    and the intersection's mapping and signal program. The usual v/c
    comes from RCRC counts; the fingerprint does not reveal it.
    """

    fingerprint = hashlib.sha256()

    for part in (
        "rcrc",
        ",".join(s.segment_id for s in model.network.segments),
        [offsets.round(6).tobytes() for offsets in model.network.offsets],
        [offsets.round(6).tobytes() for offsets in (model.network.weekend_offsets or [])],
        model.spread,
        sorted((key, round(value, 6)) for key, value in model.usual.items()),
        DAY_FACTOR_LIMITS,
        sorted(TOMTOM_CONGESTION_LEVEL_PERCENT.items()),
        sorted(TOMTOM_TRAVEL_TIME_10KM_S.items()),
        TIMELINE_SLOWEST_SHARE,
        (BPR_ALPHA, BPR_BETA, MAX_VOLUME_TO_CAPACITY),
        (CALIBRATION_START, CALIBRATION_WEEKS, IMPUTATION_HISTORY_DAYS),
        file_fingerprint(DEFAULT_MAPPING_PATH),
        file_fingerprint(DEFAULT_NETWORK_PATH),
        file_fingerprint(DEFAULT_HOURLY_VC) if DEFAULT_HOURLY_VC.exists() else "demand model",
        file_fingerprint(DEFAULT_WEEKEND_HOURLY_VC) if DEFAULT_WEEKEND_HOURLY_VC.exists() else "no weekend profile",
    ):
        fingerprint.update(repr(part).encode())

    return SourceMetadata(
        seed=SEED,
        interval_minutes=INTERVAL_S // 60,
        timezone=str(RIYADH),
        inputs=fingerprint.hexdigest(),
    )


class ObservedSpeedProducer:
    """
    Store the missing 15-minute intervals from the source's counts.

    Follows the source's clock, not the computer's: the RCRC replay
    runs whole weeks behind (traffic_source/rcrc_replay/clock.py), so
    the map shows the data's own dates, as the rest of Jaadah does. The
    7 dates kept end at the source's latest interval.
    """

    def __init__(
        self,
        model: ObservedModel,
        storage: NetworkSpeedStorage,
        latest: Callable[[], datetime | None],
        levels: Callable[[datetime, datetime], dict[datetime, float]],
    ) -> None:
        self.model = model
        self.storage = storage
        self.latest = latest
        self.levels = levels

    def interval(self, start: datetime, site_level: float, factor: float | None = None) -> IntervalSpeeds:
        """Return the speeds of the interval that starts at start."""

        speeds, network_speed = observed_interval_speeds(self.model, start, site_level, factor)

        return IntervalSpeeds(
            interval_start=start,
            interval_end=start + INTERVAL,
            network_speed=network_speed,
            speeds=speeds,
        )

    def synchronize(self) -> int:
        """
        Store every interval missing up to the source's latest one, and
        delete the ones before the 7 dates kept. An interval without the
        intersection's v/c is not stored. Returns how many were added.
        """

        cutoff = self.latest()

        if cutoff is None:
            return 0

        cutoff = cutoff.astimezone(RIYADH)
        first_day = cutoff.date() - timedelta(days=HISTORY_DAYS - 1)
        oldest = datetime(first_day.year, first_day.month, first_day.day, tzinfo=RIYADH)
        stored = self.storage.get_latest_end()
        start = oldest if stored is None or stored < oldest else stored

        added = 0

        if start < cutoff:
            # from the start of start's day, for the day factor so far
            day_start = datetime(start.year, start.month, start.day, tzinfo=RIYADH)
            fetched = {
                moment.astimezone(RIYADH): level
                for moment, level in self.levels(day_start, cutoff).items()
                if moment + INTERVAL <= cutoff
            }
            factors = day_factors(self.model, fetched)
            levels = sorted((moment, level) for moment, level in fetched.items() if start <= moment)

            # one day at a time, so a long gap does not sit in memory
            for first in range(0, len(levels), 96):
                batch = [self.interval(moment, level, factors[moment]) for moment, level in levels[first:first + 96]]
                self.storage.insert_intervals(batch)
                added += len(batch)

        self.storage.delete_before(oldest)

        return added

    def run_forever(self, stop_event: Event) -> None:
        """Keep the stored intervals up to date until stop_event is set."""

        keep_up_to_date(self.synchronize, stop_event)

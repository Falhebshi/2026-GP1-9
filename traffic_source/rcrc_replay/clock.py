"""
The replay clock: which part of the report RCRC has "delivered" so far.
"""

from datetime import datetime

from traffic_source.rcrc_replay.config import INTERVAL_MINUTES, RIYADH, ReplayConfig


def replay_now(now: datetime, config: ReplayConfig) -> datetime:
    """The data time shown as "now": the real time, offset_weeks earlier."""

    return now.astimezone(RIYADH) - config.offset


def released_until(
    now: datetime,
    config: ReplayConfig,
    data_end: datetime | None,
) -> datetime:
    """
    Return the end of the latest interval released at real time `now`:
    the replay time rounded down to a 15-minute boundary. After the end
    of the data it stays at the end of the data: the provider has
    nothing newer to deliver.
    """

    moment = replay_now(now, config)
    released = moment.replace(
        minute=moment.minute - moment.minute % INTERVAL_MINUTES,
        second=0,
        microsecond=0,
    )

    if data_end is not None and released > data_end:
        return data_end

    return released

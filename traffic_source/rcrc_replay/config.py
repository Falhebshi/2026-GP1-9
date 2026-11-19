"""
Configuration of the RCRC replay source.

The replay source plays a private RCRC report back as if RCRC were
delivering it live. The report and the replay database hold restricted
RCRC data, so both live in the private data folder next to the
repository, never inside it.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PRIVATE_DATA_DIR = REPO_ROOT.parent / "jaadah-private-data"

RCRC_REPORT_DIR = PRIVATE_DATA_DIR / "raw" / "rcrc" / "site_1444"

RCRC_REPLAY_DATABASE_PATH = (
    PRIVATE_DATA_DIR
    / "processed"
    / "rcrc_replay"
    / "rcrc_replay.db"
)

RIYADH = timezone(timedelta(hours=3))

INTERVAL_MINUTES = 15

OFFSET_WEEKS_VARIABLE = "JAADAH_REPLAY_OFFSET_WEEKS"


@dataclass(frozen=True)
class ReplayConfig:
    """
    How far the replay runs behind the real clock.

    The data shown as "now" is the real time minus offset_weeks whole
    weeks, so the time of day and the weekday always match the real
    clock: a Tuesday-morning demonstration shows Tuesday-morning
    traffic. With 13 weeks, 16 November 2026 shows 17 August, and
    1 December shows 1 September. Everything before that is history;
    later intervals are released as real time passes. The dates in the
    data are never changed.
    """

    offset_weeks: int = 13

    def __post_init__(self) -> None:
        if isinstance(self.offset_weeks, bool) or not isinstance(self.offset_weeks, int):
            raise ValueError("offset_weeks must be a whole number of weeks")

        if self.offset_weeks < 0:
            raise ValueError("offset_weeks must not be negative")

    @property
    def offset(self) -> timedelta:
        return timedelta(weeks=self.offset_weeks)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "ReplayConfig":
        """
        Read offset_weeks from JAADAH_REPLAY_OFFSET_WEEKS, default 13.

        Calibration needs days later than the demonstration
        clock has released; it starts the server with a smaller offset,
        for example 0, which releases the whole report.
        """

        environ = os.environ if environ is None else environ
        value = environ.get(OFFSET_WEEKS_VARIABLE)
        if value is None or not value.strip():
            return cls()

        try:
            weeks = int(value.strip())
        except ValueError:
            raise ValueError(f"{OFFSET_WEEKS_VARIABLE} must be a whole number of weeks") from None

        return cls(offset_weeks=weeks)

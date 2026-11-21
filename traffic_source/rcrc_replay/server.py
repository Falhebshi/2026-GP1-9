"""
The RCRC replay source: a stand-in for a live RCRC feed.

It serves a private RCRC report through the same kind of API as the
synthetic source (/health, /detectors, /observations), releasing the
report's intervals as the replay clock advances. Rows are served exactly
as RCRC wrote them; Jaadah converts them in its RCRC ingestion adapter.

Run with:

    uvicorn traffic_source.rcrc_replay.server:app --port 8002

after loading a report with python -m traffic_source.rcrc_replay.load.
The data shown as "now" runs a whole number of weeks behind the real
clock (ReplayConfig).
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from traffic_source.rcrc_replay.clock import released_until, replay_now
from traffic_source.rcrc_replay.config import (
    INTERVAL_MINUTES,
    RCRC_REPLAY_DATABASE_PATH,
    ReplayConfig,
)
from traffic_source.rcrc_replay.storage import RcrcReplayStorage


def _wall_now() -> datetime:
    return datetime.now(timezone.utc)


def _check_boundary(name: str, moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must include a timezone",
        )

    if moment.minute % INTERVAL_MINUTES or moment.second or moment.microsecond:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be aligned to a {INTERVAL_MINUTES}-minute interval",
        )


def create_app(
    storage: RcrcReplayStorage | None = None,
    config: ReplayConfig | None = None,
    now: Callable[[], datetime] = _wall_now,
) -> FastAPI:
    """Create the RCRC replay source API."""

    config = config or ReplayConfig()
    storage = storage or RcrcReplayStorage(RCRC_REPLAY_DATABASE_PATH)

    def released() -> tuple[dict | None, datetime | None]:
        info = storage.get_report_info()

        if info is None:
            return None, None

        return info, released_until(now(), config, info["last_interval_end"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage.initialize()
        yield

    app = FastAPI(
        title="Jaadah RCRC Replay Source",
        version="0.1.0",
        description=(
            "Plays back a private RCRC intersection report as if RCRC "
            "were delivering it live."
        ),
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict:
        info, latest = released()

        return {
            "status": "ok" if info is not None else "no_report",
            "source": "rcrc",
            "site_id": info["site_id"] if info else None,
            "latest_available_timestamp": latest.isoformat() if latest else None,
            "replay_time": replay_now(now(), config).isoformat(),
            "data_end": (
                info["last_interval_end"].isoformat()
                if info and info["last_interval_end"]
                else None
            ),
        }

    @app.get("/detectors")
    def detectors() -> dict:
        info = storage.get_report_info()
        values = storage.get_detectors()

        return {
            "site_id": info["site_id"] if info else None,
            "count": len(values),
            "detectors": values,
        }

    @app.get("/observations")
    def observations(start: datetime, end: datetime) -> dict:
        """
        Return the released rows whose time stamp (an interval end) is
        after start and at or before end. Rows not yet released are not
        returned; latest_available_timestamp says how far the feed has
        reached.
        """

        _check_boundary("start", start)
        _check_boundary("end", end)

        if end <= start:
            raise HTTPException(status_code=400, detail="end must be later than start")

        info, latest = released()

        if info is None:
            raise HTTPException(status_code=503, detail="no RCRC report is loaded")

        through = min(end, latest)
        rows = storage.get_rows(after=start, through=through) if through > start else []

        return {
            "source": "rcrc",
            "site_id": info["site_id"],
            "interval_minutes": INTERVAL_MINUTES,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "latest_available_timestamp": latest.isoformat(),
            "observations": rows,
        }

    return app


app = create_app(config=ReplayConfig.from_environment())

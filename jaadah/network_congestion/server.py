"""
The network map server: the city's road speeds every 15 minutes.

Built like the synthetic traffic source's server
(traffic_source/synthetic/server.py): a small FastAPI app with a
background producer (producer.py) that adds each completed 15 minutes
to a local SQLite database (storage.py). Network Overview reads it
through the Vite proxy at /api/network (frontend/vite.config.js).

Run it next to the website (it needs jaadah-private-data next to the
repository, like synthetic.py):

    uvicorn jaadah.network_congestion.server:app --port 8001

Endpoints:

    GET /health                   status and the newest stored interval
    GET /segments                 every segment's line (GeoJSON, no OSM IDs)
    GET /days                     the days with data and the level limits
    GET /speeds?time=             every segment's speed in the interval that
                                  contains time; the newest without time
    GET /timeline?day=YYYY-MM-DD  the network speed of each stored interval
                                  of that day, for the timeline bars
"""

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from threading import Event, Thread

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware

from jaadah.network_congestion.parameters import (
    LOW_ABOVE_SPEED_RATIO,
    MODERATE_ABOVE_SPEED_RATIO,
)
from jaadah.network_congestion.producer import (
    NetworkSpeedProducer,
    source_metadata,
)
from jaadah.network_congestion.storage import (
    RIYADH,
    NetworkSpeedStorage,
)
from jaadah.network_congestion.synthetic import (
    City,
    load_city,
    segments_geojson,
)


def _riyadh(moment: datetime) -> datetime:
    """Read a time without a timezone as Riyadh time."""

    if moment.tzinfo is None:
        return moment.replace(tzinfo=RIYADH)

    return moment.astimezone(RIYADH)


def create_app(
    city: City | None = None,
    storage: NetworkSpeedStorage | None = None,
    run_producer: bool = True,
) -> FastAPI:
    """Create the network map server."""

    speeds_storage = storage if storage is not None else NetworkSpeedStorage()
    state = {"city": city, "geojson": None}

    def get_city() -> City:
        """Load the city once (it reads the private RCRC profiles)."""

        if state["city"] is None:
            state["city"] = load_city()

        return state["city"]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Prepare the database and run the producer in the background."""

        speeds_storage.initialize()
        speeds_storage.ensure_source_metadata(source_metadata(get_city()))

        stop_event = Event()
        producer_thread = None

        if run_producer:
            producer = NetworkSpeedProducer(get_city(), speeds_storage)
            producer_thread = Thread(
                target=producer.run_forever,
                args=(stop_event,),
                daemon=True,
                name="network-speed-producer",
            )
            producer_thread.start()

        try:
            yield
        finally:
            stop_event.set()

            if producer_thread is not None:
                producer_thread.join(timeout=5.0)

    app = FastAPI(
        title="Jaadah Network Map Server",
        version="0.1.0",
        description="Synthetic road speeds for Network Overview, every 15 minutes.",
        lifespan=lifespan,
    )
    # /segments is about 5 MB and /speeds about 200 kB before compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/health")
    def health() -> dict:
        """Return the server status and the newest stored interval."""

        latest = speeds_storage.get_latest_end()

        return {
            "status": "ok",
            "source": "synthetic",
            "latest_interval_end": latest.isoformat() if latest else None,
        }

    @app.get("/segments")
    def segments() -> dict:
        """Return every segment's line, name, road class and lanes."""

        if state["geojson"] is None:
            current = get_city()
            state["geojson"] = segments_geojson(
                current.segments, current.capacities,
            )

        return state["geojson"]

    @app.get("/days")
    def days() -> dict:
        """Return the days with data and the speed limits of the levels."""

        latest = speeds_storage.get_latest_end()

        return {
            "source": "synthetic",
            "days": speeds_storage.get_days(),
            "latest_interval_end": latest.isoformat() if latest else None,
            "low_above_speed_ratio": LOW_ABOVE_SPEED_RATIO,
            "moderate_above_speed_ratio": MODERATE_ABOVE_SPEED_RATIO,
        }

    @app.get("/speeds")
    def speeds(time: datetime | None = None) -> dict:
        """Return every segment's speed in one interval."""

        interval = speeds_storage.get_interval(
            _riyadh(time) if time is not None else None
        )

        if interval is None:
            raise HTTPException(
                status_code=404,
                detail="no stored interval for this time",
            )

        ids = [segment.segment_id for segment in get_city().segments]

        return {
            "source": "synthetic",
            "interval_start": interval.interval_start.isoformat(),
            "interval_end": interval.interval_end.isoformat(),
            "network_speed": interval.network_speed,
            "speeds": dict(zip(ids, interval.speeds)),
        }

    @app.get("/timeline")
    def timeline(day: date) -> dict:
        """Return the network speed of each stored interval of a day."""

        start = datetime(day.year, day.month, day.day, tzinfo=RIYADH)
        rows = speeds_storage.get_network_speeds(start, start + timedelta(days=1))

        return {
            "day": day.isoformat(),
            "intervals": [
                {
                    "interval_start": interval_start.isoformat(),
                    "interval_end": interval_end.isoformat(),
                    "network_speed": network_speed,
                }
                for interval_start, interval_end, network_speed in rows
            ],
        }

    return app


app = create_app()

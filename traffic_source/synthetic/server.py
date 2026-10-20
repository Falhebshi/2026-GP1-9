from contextlib import asynccontextmanager
from datetime import datetime
from threading import Event, Thread
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query

from traffic_source.synthetic.config import (
    SYNTHETIC_DATABASE_PATH,
    SyntheticSourceConfig,
)
from traffic_source.synthetic.generator import (
    TARGET_DETECTORS,
    TARGET_SITE_ID,
    SyntheticDetectorObservation,
    SyntheticTrafficGenerator,
    SyntheticTrafficProfiles,
    load_profiles,
)
from traffic_source.synthetic.producer import (
    SyntheticTrafficProducer,
)
from traffic_source.synthetic.storage import (
    SyntheticTrafficStorage,
)


def _normalize_timestamp(
    timestamp: datetime,
    timezone_name: str,
) -> datetime:
    """Normalize a timestamp to the configured source timezone."""

    timezone = ZoneInfo(timezone_name)

    if timestamp.tzinfo is None:
        return timestamp.replace(
            tzinfo=timezone
        )

    return timestamp.astimezone(
        timezone
    )


def _serialize_observation(
    observation: SyntheticDetectorObservation,
) -> dict:
    """Convert one observation to the external RCRC-shaped representation."""

    return {
        "Site ID": observation.site_id,
        "detector_id": observation.detector_id,
        "Date  & Time": observation.timestamp.isoformat(),
        "volume": observation.volume,
        "description": observation.description,
    }


def create_app(
    profiles: SyntheticTrafficProfiles | None = None,
    storage: SyntheticTrafficStorage | None = None,
    run_producer: bool = True,
) -> FastAPI:
    """Create the standalone synthetic traffic-source API."""

    config = SyntheticSourceConfig()

    source_storage = (
        storage
        if storage is not None
        else SyntheticTrafficStorage(
            database_path=SYNTHETIC_DATABASE_PATH,
        )
    )

    profile_cache = profiles
    generator_cache: SyntheticTrafficGenerator | None = None

    def get_profiles() -> SyntheticTrafficProfiles:
        """Load and cache the traffic profiles used by the source."""

        nonlocal profile_cache

        if profile_cache is None:
            profile_cache = load_profiles()

        return profile_cache

    def get_generator() -> SyntheticTrafficGenerator:
        """Create and cache the source generator."""

        nonlocal generator_cache

        if generator_cache is None:
            generator_cache = SyntheticTrafficGenerator(
                profiles=get_profiles(),
                config=config,
            )

        return generator_cache

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize source storage and manage the background producer."""

        source_storage.initialize()
        source_storage.ensure_source_metadata(
            config
        )

        stop_event: Event | None = None
        producer_thread: Thread | None = None

        if run_producer:
            producer = SyntheticTrafficProducer(
                generator=get_generator(),
                storage=source_storage,
                config=config,
            )

            stop_event = Event()

            producer_thread = Thread(
                target=producer.run_forever,
                args=(stop_event,),
                daemon=True,
                name="synthetic-traffic-producer",
            )

            producer_thread.start()

        try:
            yield

        finally:
            if stop_event is not None:
                stop_event.set()

            if producer_thread is not None:
                producer_thread.join(
                    timeout=5.0
                )

    app = FastAPI(
        title="Jaadah Synthetic Traffic Source",
        version="0.1.0",
        description=(
            "Synthetic traffic-data source that provides "
            "RCRC-shaped detector observations for Jaadah."
        ),
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict:
        """Return the current status of the traffic source."""

        latest = (
            source_storage.get_latest_timestamp()
        )

        return {
            "status": "ok",
            "source": "synthetic",
            "latest_available_timestamp": (
                latest.isoformat()
                if latest is not None
                else None
            ),
        }

    @app.get("/detectors")
    def detectors() -> dict:
        """Return the detector IDs exposed by the synthetic source."""

        detector_ids = sorted(
            detector.detector_id
            for detector in TARGET_DETECTORS
        )

        return {
            "site_id": TARGET_SITE_ID,
            "count": len(detector_ids),
            "detector_ids": detector_ids,
        }

    @app.get("/observations")
    def observations(
        start: datetime,
        end: datetime,
        detector_id: Annotated[
            list[int] | None,
            Query(),
        ] = None,
    ) -> dict:
        """
        Return stored observations for a requested physical traffic window.

        Record timestamps label the end of each observation interval.
        """

        start_local = _normalize_timestamp(
            start,
            config.timezone,
        )

        end_local = _normalize_timestamp(
            end,
            config.timezone,
        )

        if end_local <= start_local:
            raise HTTPException(
                status_code=400,
                detail="end must be later than start",
            )

        interval_minutes = (
            config.interval_minutes
        )

        if (
            start_local.second != 0
            or start_local.microsecond != 0
            or start_local.minute
            % interval_minutes
            != 0
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"start must be aligned to a "
                    f"{interval_minutes}-minute interval"
                ),
            )

        if (
            end_local.second != 0
            or end_local.microsecond != 0
            or end_local.minute
            % interval_minutes
            != 0
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"end must be aligned to a "
                    f"{interval_minutes}-minute interval"
                ),
            )

        stored_observations = (
            source_storage.get_observations(
                start=start_local,
                end=end_local,
                detector_ids=detector_id,
            )
        )

        latest = (
            source_storage.get_latest_timestamp()
        )

        return {
            "source": "synthetic",
            "scenario": config.scenario,
            "seed": config.seed,
            "interval_minutes": (
                config.interval_minutes
            ),
            "timezone": config.timezone,
            "start": start_local.isoformat(),
            "end": end_local.isoformat(),
            "latest_available_timestamp": (
                latest.isoformat()
                if latest is not None
                else None
            ),
            "observations": [
                _serialize_observation(
                    observation
                )
                for observation
                in stored_observations
            ],
        }

    return app


app = create_app()
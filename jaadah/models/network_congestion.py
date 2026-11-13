"""
Models for the network map (Network Overview).

A RoadSegment is one direction of a main road, from one intersection
or signal to the next (jaadah/network_congestion/segments.py writes
them). A SegmentCongestion is how busy one segment was in one
15-minute interval, and the level it is coloured with.
"""

from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ============================================================
# ENUMS
# ============================================================

class RoadClass(str, Enum):
    """The OpenStreetMap road classes kept on the network map."""

    MOTORWAY = "motorway"
    TRUNK = "trunk"
    PRIMARY = "primary"
    SECONDARY = "secondary"


class CongestionLevel(str, Enum):
    """The colour of a segment on the map."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SegmentSource(str, Enum):
    """Where a segment's volume comes from."""

    RCRC = "rcrc"
    SYNTHETIC = "synthetic"


class CongestionStatus(str, Enum):
    """Whether a segment has a value for an interval."""

    OK = "ok"
    UNAVAILABLE = "unavailable"


# ============================================================
# ROAD SEGMENT
# ============================================================

class RoadSegment(BaseModel):
    """
    One direction of a main road between two cut points.

    The OSM way and node IDs are kept in segment_mappings.json, never
    here, so the website only sees Jaadah IDs.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    segment_id: str

    name_en: str | None = None
    name_ar: str | None = None

    road_class: RoadClass

    # a ramp (motorway_link ...) of its road class
    is_link: bool = False

    lane_count: int = Field(
        ge=1,
    )
    free_flow_speed_kmh: float = Field(
        gt=0,
    )

    signal_at_end: bool

    # (longitude, latitude) points in driving order
    geometry: list[tuple[float, float]] = Field(
        min_length=2,
    )

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id(cls, value: str) -> str:
        """Reject an empty or whitespace-only segment ID."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("geometry")
    @classmethod
    def validate_geometry(
        cls,
        value: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Reject points outside longitude and latitude ranges."""

        for lon, lat in value:
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError(f"point ({lon}, {lat}) is out of range")

        return value


# ============================================================
# SEGMENT CONGESTION
# ============================================================

class SegmentCongestion(BaseModel):
    """
    How busy one segment was in one 15-minute interval.

    An ok result has a volume, capacity, v/c, level and congestion
    weight. An unavailable result has none of them and a reason, so a
    segment without data is never shown with a level.

    Not used by the synthetic generator yet: synthetic roads always
    have a value, and its daily files keep only the speeds. It is
    kept for the RCRC data, where a missing detector makes a segment
    unavailable, and is checked against it when the data arrives.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    segment_id: str
    interval_start: datetime
    interval_end: datetime

    source: SegmentSource
    status: CongestionStatus

    # cars counted in the 15 minutes
    volume_veh: int | None = Field(
        default=None,
        ge=0,
    )
    capacity_veh_h: float | None = Field(
        default=None,
        gt=0,
    )
    volume_to_capacity: float | None = Field(
        default=None,
        ge=0,
    )
    level: CongestionLevel | None = None

    # heatmap weight: v/c capped at 1
    congestion: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "SegmentCongestion":
        """Match the values to the status, and the interval order."""

        if self.interval_end <= self.interval_start:
            raise ValueError("interval_end must be after interval_start")

        values = (
            self.volume_veh,
            self.capacity_veh_h,
            self.volume_to_capacity,
            self.level,
            self.congestion,
        )

        if self.status == CongestionStatus.OK:
            if any(value is None for value in values):
                raise ValueError("an ok result needs every value")

            if self.reason is not None:
                raise ValueError("an ok result has no reason")

        else:
            if any(value is not None for value in values):
                raise ValueError("an unavailable result has no values")

            if not self.reason:
                raise ValueError("an unavailable result needs a reason")

        return self

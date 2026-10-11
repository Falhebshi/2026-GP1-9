from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ============================================================
# INTERSECTION
# ============================================================

class Intersection(BaseModel):
    """
    A stable Jaadah intersection identity.

    This model describes the intersection at the application level.
    SUMO traffic-light IDs and source site IDs belong in mapping data,
    not here.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    intersection_id: str

    name_en: str | None = None
    name_ar: str | None = None

    center_longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
    )
    center_latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
    )

    area_label: str | None = None

    @field_validator("intersection_id")
    @classmethod
    def validate_intersection_id(cls, value: str) -> str:
        """Reject an empty or whitespace-only intersection ID."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @model_validator(mode="after")
    def validate_center_coordinates(self) -> "Intersection":
        """
        Require longitude and latitude to be supplied together
        when an intersection center is provided.
        """

        longitude_present = self.center_longitude is not None
        latitude_present = self.center_latitude is not None

        if longitude_present != latitude_present:
            raise ValueError(
                "center_longitude and center_latitude "
                "must be provided together"
            )

        return self



# ============================================================
# APPROACH
# ============================================================
class Approach(BaseModel):
    """
    A stable Jaadah approach identity belonging to an intersection.

    SUMO edge and lane mappings are intentionally stored separately.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    approach_id: str
    intersection_id: str

    @field_validator(
        "approach_id",
        "intersection_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

# ============================================================
# MOVEMENT
# ============================================================

class Movement(BaseModel):
    """
    A stable Jaadah traffic-movement identity.

    A movement belongs to an intersection and may optionally be linked
    to an approach. SUMO route edges are handled by mapping data.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    movement_id: str
    intersection_id: str
    approach_id: str | None = None

    @field_validator(
        "movement_id",
        "intersection_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only required identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("approach_id")
    @classmethod
    def validate_optional_approach_id(
        cls,
        value: str | None,
    ) -> str | None:
        """Reject a blank approach ID when one is supplied."""

        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

# ============================================================
# SEGMENT
# ============================================================

class Segment(BaseModel):
    """
    A stable Jaadah road-segment identity.

    SUMO edge IDs associated with the segment are stored separately
    in SegmentMapping.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    segment_id: str

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id(cls, value: str) -> str:
        """Reject an empty or whitespace-only segment ID."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value
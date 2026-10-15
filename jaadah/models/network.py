from enum import Enum

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

# ============================================================
# MOVEMENT AND LANE ENUMS
# ============================================================

class MovementType(str, Enum):
    """The turning direction of a movement."""

    THROUGH = "through"
    LEFT = "left"
    RIGHT = "right"


class MovementControl(str, Enum):
    """
    Whether the traffic signal controls a movement.

    UNCONTROLLED is used for right turns that leave the approach
    through a slip lane before the signal.
    """

    SIGNALIZED = "signalized"
    UNCONTROLLED = "uncontrolled_slip_lane"


# ============================================================
# MOVEMENT ATTRIBUTES
# ============================================================

class MovementAttributes(BaseModel):
    """
    Jaadah-level facts about one movement that the KPI engine needs.

    Kept separate from Movement so that Movement remains a pure
    identity. SUMO edges and lanes are handled by mapping data.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    movement_id: str
    intersection_id: str
    approach_id: str

    movement_type: MovementType
    control: MovementControl

    @field_validator(
        "movement_id",
        "intersection_id",
        "approach_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value


# ============================================================
# APPROACH LANE
# ============================================================

class ApproachLane(BaseModel):
    """
    One lane of a Jaadah approach and the movements it serves.

    lane_index counts from the median: 1 is the lane closest to the
    median. This is a Jaadah index; the mapping layer converts it to
    SUMO lane IDs (SUMO counts from the kerb, starting at 0).

    A lane shared by several movements (e.g. through and left) lists
    all of them in served_movement_ids.

    storage_length_m is the queue storage available in this lane,
    measured back from the stop line. It is optional: when it is not
    known, the queue storage ratio is reported as unavailable.
    """

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    intersection_id: str
    approach_id: str

    lane_index: int = Field(ge=1)

    served_movement_ids: list[str]

    lane_width_m: float = Field(gt=0)
    storage_length_m: float | None = Field(
        default=None,
        gt=0,
    )

    @field_validator(
        "intersection_id",
        "approach_id",
    )
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty or whitespace-only identifiers."""

        value = value.strip()

        if not value:
            raise ValueError("identifier must not be empty")

        return value

    @field_validator("lane_index", mode="before")
    @classmethod
    def validate_lane_index(cls, value):
        """Reject booleans being interpreted as lane numbers."""

        if isinstance(value, bool):
            raise ValueError(
                "lane_index must be an integer, not a boolean"
            )

        return value

    @field_validator("served_movement_ids")
    @classmethod
    def validate_served_movement_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        """
        Normalize served movement IDs and reject empty, missing or
        duplicate references.
        """

        cleaned_values = []

        for value in values:
            value = value.strip()

            if not value:
                raise ValueError(
                    "served movement ID must not be empty"
                )

            cleaned_values.append(value)

        if not cleaned_values:
            raise ValueError(
                "a lane must serve at least one movement"
            )

        if len(cleaned_values) != len(set(cleaned_values)):
            raise ValueError(
                "served_movement_ids must not contain duplicates"
            )

        return cleaned_values
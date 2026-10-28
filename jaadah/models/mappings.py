from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from .network import (
    Approach,
    ApproachLane,
    Intersection,
    Movement,
    MovementAttributes,
    MovementControl,
)
from .traffic import TrafficObservationSource


# ============================================================
# ENUMS
# ============================================================

class MappingStatus(str, Enum):
    """How reliably a detector can be associated with Jaadah movements."""

    USABLE = "usable"
    REQUIRES_ALLOCATION = "requires_allocation"
    UNRESOLVED = "unresolved"


class ApproachSide(str, Enum):
    """The intersection side where an approach is located."""

    EAST = "east"
    WEST = "west"
    NORTH = "north"
    SOUTH = "south"


# ============================================================
# NETWORK METADATA
# ============================================================

class NetworkMetadata(BaseModel):
    """Identifies the SUMO network version used by a mapping configuration."""

    model_config = ConfigDict(extra="forbid")

    version: str
    path: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("version", "path")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Reject empty or whitespace-only values."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value


# ============================================================
# INTERSECTION MAPPING
# ============================================================

class IntersectionMapping(BaseModel):
    """Connects a Jaadah intersection to source sites and a SUMO TLS."""

    model_config = ConfigDict(extra="forbid")

    intersection_id: str
    source_sites: list[str] = Field(default_factory=list)
    sumo_tls_id: str | None = None

    @field_validator("intersection_id")
    @classmethod
    def validate_intersection_id(cls, value: str) -> str:
        """Reject an empty intersection ID."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("sumo_tls_id")
    @classmethod
    def validate_sumo_tls_id(cls, value: str | None) -> str | None:
        """Reject a blank TLS ID when one is supplied."""

        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("source_sites")
    @classmethod
    def validate_source_sites(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicate source-site IDs."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("source site IDs must be unique")
        return cleaned


# ============================================================
# APPROACH MAPPING
# ============================================================

class ApproachMapping(BaseModel):
    """
    Connects a Jaadah approach to its SUMO queue-detection lanes and
    defines its measurement zone.

    The zone is zone_upstream_m before the stop line, the path through
    the junction, and zone_downstream_m after the junction exit. Both
    distances are optional, as in a draft, but are given together.
    """

    model_config = ConfigDict(extra="forbid")

    approach_id: str
    intersection_id: str
    approach_side: ApproachSide
    queue_detection_lane_ids: list[str] = Field(default_factory=list)
    zone_upstream_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    zone_downstream_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("approach_id", "intersection_id")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty required values."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("queue_detection_lane_ids")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        """Reject blank and duplicate identifiers."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("identifiers must be unique within a list")
        return cleaned

    @model_validator(mode="after")
    def validate_zone_pair(self) -> "ApproachMapping":
        """Require both zone distances or neither."""

        if (self.zone_upstream_m is None) != (self.zone_downstream_m is None):
            raise ValueError(
                "zone_upstream_m and zone_downstream_m must be given together"
            )
        return self


# ============================================================
# LANE MAPPING
# ============================================================

class LaneMapping(BaseModel):
    """Maps a Jaadah lane to SUMO segments, upstream to downstream."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    sumo_lane_ids: list[str] = Field(min_length=1)

    @field_validator("lane_id")
    @classmethod
    def validate_lane_id(cls, value: str) -> str:
        """Reject an empty lane ID."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("sumo_lane_ids")
    @classmethod
    def validate_sumo_lanes(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicate SUMO lane IDs."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("SUMO lane segments must be unique")
        return cleaned


# ============================================================
# DETECTOR MAPPING
# ============================================================

class DetectorMapping(BaseModel):
    """Connects a source detector to a Jaadah lane, approach, or movements."""

    model_config = ConfigDict(extra="forbid")

    source: TrafficObservationSource
    site_id: str
    detector_id: str
    intersection_id: str
    approach_id: str | None = None
    lane_id: str | None = None
    sumo_lane_id: str | None = None
    sumo_position_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    movement_ids: list[str] = Field(default_factory=list)
    mapping_status: MappingStatus
    mapping_note: str | None = None

    @field_validator("site_id", "detector_id", "intersection_id")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty required IDs."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("approach_id", "lane_id", "sumo_lane_id")
    @classmethod
    def validate_optional_ids(cls, value: str | None) -> str | None:
        """Reject blank optional IDs when supplied."""

        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("sumo_position_m", mode="before")
    @classmethod
    def reject_boolean_position(cls, value):
        """A boolean is not a distance, even though Python treats it as numeric."""

        if isinstance(value, bool):
            raise ValueError("SUMO position must be numeric, not boolean")
        return value

    @model_validator(mode="after")
    def validate_sumo_location(self) -> "DetectorMapping":
        """An exact SUMO location needs both a lane and a position."""

        if (self.sumo_lane_id is None) != (self.sumo_position_m is None):
            raise ValueError("sumo_lane_id and sumo_position_m must be supplied together")
        return self

    @field_validator("movement_ids")
    @classmethod
    def validate_movement_ids(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicate candidate movement IDs."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("movement IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_mapping_status(self) -> "DetectorMapping":
        """Require the movement count to agree with the mapping status."""

        count = len(self.movement_ids)
        if self.mapping_status == MappingStatus.USABLE and count != 1:
            raise ValueError("usable detector must identify exactly one movement")
        if self.mapping_status == MappingStatus.REQUIRES_ALLOCATION and count < 2:
            raise ValueError("requires_allocation needs at least two candidate movements")
        if self.mapping_status == MappingStatus.UNRESOLVED and count:
            raise ValueError("unresolved detector must not assert movement IDs")
        return self


# ============================================================
# SIGNAL CROSSING MAPPING
# ============================================================

class SignalCrossingMapping(BaseModel):
    """Identifies one ordered traffic-signal crossing on a movement route."""

    model_config = ConfigDict(extra="forbid")

    crossing_order: StrictInt = Field(ge=0)
    sumo_tls_id: str
    controlled_link_indices: list[StrictInt] = Field(min_length=1)

    @field_validator("sumo_tls_id")
    @classmethod
    def validate_sumo_tls_id(cls, value: str) -> str:
        """Reject an empty TLS ID."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("controlled_link_indices")
    @classmethod
    def validate_link_indices(cls, values: list[int]) -> list[int]:
        """Reject negative, boolean, or duplicate controlled link indices."""

        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("TLS link indices must be nonnegative integers")
        if len(values) != len(set(values)):
            raise ValueError("duplicate link indices in one crossing")
        return values


# ============================================================
# MOVEMENT MAPPING
# ============================================================

class MovementMapping(BaseModel):
    """Connects a stable Jaadah movement to a complete SUMO edge path."""

    model_config = ConfigDict(extra="forbid")

    movement_id: str
    intersection_id: str
    approach_id: str | None = None
    sumo_route_edge_ids: list[str] = Field(min_length=2)
    sumo_lanes: list[str] = Field(default_factory=list)
    signal_controlled: bool
    sumo_tls_id: str | None = None
    signal_crossings: list[SignalCrossingMapping] = Field(default_factory=list)

    @field_validator("movement_id", "intersection_id")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty required IDs."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("approach_id", "sumo_tls_id")
    @classmethod
    def validate_optional_ids(cls, value: str | None) -> str | None:
        """Reject blank optional IDs when supplied."""

        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("sumo_route_edge_ids")
    @classmethod
    def validate_route_edges(cls, values: list[str]) -> list[str]:
        """Reject blank edge IDs while allowing repeated edges in a route."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        return cleaned

    @field_validator("sumo_lanes")
    @classmethod
    def validate_lanes(cls, values: list[str]) -> list[str]:
        """Reject blank or duplicate SUMO lane IDs."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("lane IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_signal_metadata(self) -> "MovementMapping":
        """Require consistent TLS metadata for signal-controlled movements."""

        if self.signal_controlled:
            if not self.sumo_tls_id or not self.signal_crossings:
                raise ValueError("signal-controlled movement requires TLS ID and crossing(s)")
            if any(c.sumo_tls_id != self.sumo_tls_id for c in self.signal_crossings):
                raise ValueError("crossing TLS IDs must match movement TLS ID")
        elif self.signal_crossings or self.sumo_tls_id is not None:
            raise ValueError("non-signal-controlled movement must not carry TLS metadata")

        orders = [crossing.crossing_order for crossing in self.signal_crossings]
        if orders != list(range(len(orders))):
            raise ValueError("signal crossings must be ordered contiguously from zero")
        return self


# ============================================================
# NETWORK MAPPING CONFIG
# ============================================================

class NetworkMappingConfig(BaseModel):
    """
    Defines study-area entities and their source/SUMO mappings.

    movement_attributes holds the approved MovementAttributes of the
    movements in the KPI analysis. It may be incomplete, as in a draft:
    the attributes present are checked for consistency, while
    completeness is checked by the integration tests and by the KPI
    engine, which needs attributes for every movement it analyses.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    mapping_version: str
    network: NetworkMetadata
    intersection_mapping: IntersectionMapping
    approach_mappings: list[ApproachMapping] = Field(default_factory=list)
    approach_lanes: list[ApproachLane] = Field(default_factory=list)
    lane_mappings: list[LaneMapping] = Field(default_factory=list)
    detector_mappings: list[DetectorMapping] = Field(default_factory=list)
    movement_mappings: list[MovementMapping] = Field(default_factory=list)
    movement_attributes: list[MovementAttributes] = Field(default_factory=list)

    @field_validator("schema_version", "mapping_version")
    @classmethod
    def validate_versions(cls, value: str) -> str:
        """Reject empty mapping version values."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @property
    def canonical_intersection(self) -> Intersection:
        return Intersection(intersection_id=self.intersection_mapping.intersection_id)

    @property
    def canonical_approaches(self) -> dict[str, Approach]:
        return {
            item.approach_id: Approach(
                approach_id=item.approach_id, intersection_id=item.intersection_id
            )
            for item in self.approach_mappings
        }

    @property
    def canonical_movements(self) -> dict[str, Movement]:
        return {
            item.movement_id: Movement(
                movement_id=item.movement_id,
                intersection_id=item.intersection_id,
                approach_id=item.approach_id,
            )
            for item in self.movement_mappings
        }

    @model_validator(mode="after")
    def validate_references(self) -> "NetworkMappingConfig":
        """Reject duplicate records and invalid Jaadah mapping references."""

        detector_keys = [
            (item.source, item.site_id, item.detector_id)
            for item in self.detector_mappings
        ]

        for label, keys in (
            ("approach_id", [item.approach_id for item in self.approach_mappings]),
            ("movement_id", [item.movement_id for item in self.movement_mappings]),
            ("canonical lane_id", [item.lane_id for item in self.approach_lanes]),
            ("lane_id mapping", [item.lane_id for item in self.lane_mappings]),
            ("approach lane index", [(item.approach_id, item.lane_index) for item in self.approach_lanes]),
            ("detector key", detector_keys),
            ("movement attributes", [item.movement_id for item in self.movement_attributes]),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} mapping")

        intersection_id = self.canonical_intersection.intersection_id
        approaches = self.canonical_approaches
        movements = self.canonical_movements
        lanes = {item.lane_id: item for item in self.approach_lanes}

        for item in [*self.approach_mappings, *self.movement_mappings, *self.detector_mappings]:
            if item.intersection_id != intersection_id:
                raise ValueError("mapping belongs to a different intersection")

        for item in [*self.movement_mappings, *self.detector_mappings]:
            if item.approach_id is not None and item.approach_id not in approaches:
                raise ValueError(f"unknown approach_id: {item.approach_id}")

        for item in self.movement_mappings:
            if item.approach_id is not None and approaches[item.approach_id].intersection_id != item.intersection_id:
                raise ValueError("movement/approach intersection mismatch")

        for lane in self.approach_lanes:
            if lane.approach_id not in approaches:
                raise ValueError(f"lane refers to an unknown approach_id: {lane.approach_id}")
            for movement_id in lane.served_movement_ids:
                if movement_id not in movements:
                    raise ValueError(f"lane refers to an unmapped movement: {movement_id}")
                if movements[movement_id].approach_id != lane.approach_id:
                    raise ValueError("lane/movement approach mismatch")

        for mapping in self.lane_mappings:
            if mapping.lane_id not in lanes:
                raise ValueError(f"lane mapping refers to an unknown lane_id: {mapping.lane_id}")

        for detector in self.detector_mappings:
            detector_approach = detector.approach_id
            if detector.lane_id is not None:
                # The canonical lane must exist; its SUMO mapping may be pending.
                if detector.lane_id not in lanes:
                    raise ValueError(f"detector refers to an unknown lane_id: {detector.lane_id}")
                lane = lanes[detector.lane_id]
                if detector_approach is not None and detector_approach != lane.approach_id:
                    raise ValueError("detector/lane approach mismatch")
                detector_approach = lane.approach_id
                # Unresolved detectors assert no candidate movements.
                if detector.mapping_status != MappingStatus.UNRESOLVED:
                    if set(detector.movement_ids) != set(lane.served_movement_ids):
                        raise ValueError("detector candidates must match the lane's served movements")
            for movement_id in detector.movement_ids:
                if movement_id not in movements:
                    raise ValueError(f"detector refers to an unmapped movement: {movement_id}")
                # An approach-owned detector can only claim movements of that approach.
                if detector_approach and movements[movement_id].approach_id != detector_approach:
                    raise ValueError("detector/movement approach mismatch")

        movement_mappings = {item.movement_id: item for item in self.movement_mappings}
        attributes = {item.movement_id: item for item in self.movement_attributes}

        for item in self.movement_attributes:
            if item.movement_id not in movements:
                raise ValueError(f"movement attributes refer to an unmapped movement: {item.movement_id}")
            # Analysed movements roll up to an approach (MovementAttributes rule).
            if movements[item.movement_id].approach_id is None:
                raise ValueError(f"movement with attributes has no approach_id: {item.movement_id}")
            signalized = item.control == MovementControl.SIGNALIZED
            if signalized != movement_mappings[item.movement_id].signal_controlled:
                raise ValueError(
                    f"movement attributes control '{item.control.value}' disagrees with "
                    f"signal_controlled of {item.movement_id}"
                )

        for lane in self.approach_lanes:
            controls = {
                attributes[movement_id].control
                for movement_id in lane.served_movement_ids
                if movement_id in attributes
            }
            if len(controls) > 1:
                raise ValueError(
                    f"lane {lane.lane_id} serves both signalized and uncontrolled movements"
                )

        return self

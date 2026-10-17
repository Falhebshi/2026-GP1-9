from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
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
    """Connects a Jaadah approach to its SUMO queue-detection lanes."""

    model_config = ConfigDict(extra="forbid")

    approach_id: str
    intersection_id: str
    direction: str
    source_detectors: list[str] = Field(default_factory=list)
    queue_detection_lane_ids: list[str] = Field(default_factory=list)

    @field_validator("approach_id", "intersection_id", "direction")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty required values."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("source_detectors", "queue_detection_lane_ids")
    @classmethod
    def validate_identifiers(cls, values: list[str]) -> list[str]:
        """Reject blank and duplicate identifiers."""

        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("identifier must not be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("identifiers must be unique within a list")
        return cleaned


# ============================================================
# DETECTOR MAPPING
# ============================================================

class DetectorMapping(BaseModel):
    """Connects a source detector to an approach or candidate movements."""

    model_config = ConfigDict(extra="forbid")

    source: TrafficObservationSource
    site_id: str | None = None
    detector_id: str
    intersection_id: str
    approach_id: str | None = None
    movement_ids: list[str] = Field(default_factory=list)
    mapping_status: MappingStatus
    mapping_note: str | None = None

    @field_validator("detector_id", "intersection_id")
    @classmethod
    def validate_required_ids(cls, value: str) -> str:
        """Reject empty required IDs."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @field_validator("site_id", "approach_id")
    @classmethod
    def validate_optional_ids(cls, value: str | None) -> str | None:
        """Reject blank optional IDs when supplied."""

        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

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
    """Groups network-versioned mappings and checks their relationships."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    mapping_version: str
    network: NetworkMetadata
    intersection_mapping: IntersectionMapping
    approach_mappings: list[ApproachMapping] = Field(default_factory=list)
    detector_mappings: list[DetectorMapping] = Field(default_factory=list)
    movement_mappings: list[MovementMapping] = Field(default_factory=list)

    @field_validator("schema_version", "mapping_version")
    @classmethod
    def validate_versions(cls, value: str) -> str:
        """Reject empty mapping version values."""

        value = value.strip()
        if not value:
            raise ValueError("identifier must not be empty")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "NetworkMappingConfig":
        """Reject duplicate records and invalid Jaadah mapping references."""

        intersection_id = self.intersection_mapping.intersection_id
        approaches = {item.approach_id: item for item in self.approach_mappings}
        movements = {item.movement_id: item for item in self.movement_mappings}
        detector_keys = [
            (item.source, item.site_id, item.detector_id)
            for item in self.detector_mappings
        ]

        for label, keys in (
            ("approach_id", [item.approach_id for item in self.approach_mappings]),
            ("movement_id", [item.movement_id for item in self.movement_mappings]),
            ("detector key", detector_keys),
        ):
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} mapping")

        for item in [*self.approach_mappings, *self.movement_mappings, *self.detector_mappings]:
            if item.intersection_id != intersection_id:
                raise ValueError("mapping belongs to a different intersection")

        for item in [*self.movement_mappings, *self.detector_mappings]:
            if item.approach_id is not None and item.approach_id not in approaches:
                raise ValueError(f"unknown approach_id: {item.approach_id}")

        for item in self.movement_mappings:
            if item.approach_id is not None and approaches[item.approach_id].intersection_id != item.intersection_id:
                raise ValueError("movement/approach intersection mismatch")

        for detector in self.detector_mappings:
            for movement_id in detector.movement_ids:
                if movement_id not in movements:
                    raise ValueError(f"detector refers to an unmapped movement: {movement_id}")
                if detector.approach_id and movements[movement_id].approach_id not in (None, detector.approach_id):
                    raise ValueError("detector/movement approach mismatch")

        return self

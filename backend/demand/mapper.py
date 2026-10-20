from jaadah.models.mappings import (
    DetectorMapping,
    MappingStatus,
    NetworkMappingConfig,
)
from jaadah.models.traffic import TrafficObservation


def find_detector_mapping(
    observation: TrafficObservation,
    config: NetworkMappingConfig,
) -> DetectorMapping | None:
    """Return the mapping for the observation's source, site and detector."""

    for mapping in config.detector_mappings:
        if (
            mapping.source == observation.source
            and mapping.site_id == observation.site_id
            and mapping.detector_id == observation.detector_id
        ):
            return mapping

    return None


def map_observation_to_movement(
    observation: TrafficObservation,
    config: NetworkMappingConfig,
) -> str:
    """
    Return the Jaadah movement ID that one detector observation
    belongs to.
    """

    mapping = find_detector_mapping(
        observation=observation,
        config=config,
    )

    if mapping is None:
        raise ValueError(
            "detector has no mapping"
        )

    if mapping.mapping_status == MappingStatus.UNRESOLVED:
        raise ValueError(
            "detector mapping is unresolved"
        )

    if mapping.mapping_status == MappingStatus.REQUIRES_ALLOCATION:
        raise ValueError(
            "detector serves "
            + ", ".join(mapping.movement_ids)
            + "; no allocation rule adopted"
        )

    return mapping.movement_ids[0]

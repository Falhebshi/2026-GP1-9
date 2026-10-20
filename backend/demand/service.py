from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.demand.mapper import map_observation_to_movement
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import (
    MappingStatus,
    NetworkMappingConfig,
)
from jaadah.models.traffic import (
    SimulationDemand,
    SimulationDemandSource,
    TrafficObservation,
    TrafficObservationSource,
)


# Project and mapping paths
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)


@dataclass(frozen=True)
class DemandTransformationError:
    """Information about observations that did not become demand."""

    message: str
    observation_ids: tuple[str, ...] = ()
    site_id: str | None = None
    detector_id: str | None = None
    movement_id: str | None = None
    interval_end: datetime | None = None


@dataclass
class DemandTransformationResult:
    """Result of transforming one batch of observations into demand."""

    demands: list[SimulationDemand]
    errors: list[DemandTransformationError]

    @property
    def demand_count(self) -> int:
        return len(self.demands)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def build_demand_id(
    source: TrafficObservationSource,
    movement_id: str,
    interval_end: datetime,
) -> str:
    """Create a readable stable ID for one movement demand interval."""

    source_code = {
        TrafficObservationSource.SYNTHETIC: "SYN",
        TrafficObservationSource.RCRC: "RCRC",
    }[source]

    interval_label = interval_end.strftime("%Y%m%dT%H%M")

    return (
        f"DEM_{source_code}_"
        f"{movement_id.strip()}_"
        f"{interval_label}"
    )


def find_movement_detectors(
    config: NetworkMappingConfig,
) -> dict[tuple, set[tuple[str, str]]]:
    """
    Return the usable detectors of each movement, keyed by source and
    movement ID. A movement total needs all of them.
    """

    movement_detectors = defaultdict(set)

    for mapping in config.detector_mappings:
        if mapping.mapping_status != MappingStatus.USABLE:
            continue

        movement_detectors[
            (mapping.source, mapping.movement_ids[0])
        ].add(
            (mapping.site_id, mapping.detector_id)
        )

    return movement_detectors


def find_shared_detectors(
    config: NetworkMappingConfig,
) -> dict[tuple, set[tuple[str, str]]]:
    """
    Return the shared-lane detectors of each movement, keyed by source and
    movement ID. These detectors also count another movement, so the
    movement total is not known until their counts are split.
    """

    shared_detectors = defaultdict(set)

    for mapping in config.detector_mappings:
        if mapping.mapping_status != MappingStatus.REQUIRES_ALLOCATION:
            continue

        for movement_id in mapping.movement_ids:
            shared_detectors[
                (mapping.source, movement_id)
            ].add(
                (mapping.site_id, mapping.detector_id)
            )

    return shared_detectors


def transform_observations(
    observations: list[TrafficObservation],
    config: NetworkMappingConfig,
) -> DemandTransformationResult:
    """
    Turn detector observations into movement demand for each interval.

    Usable detectors are summed by movement and interval. Observations
    that cannot be mapped, and movement intervals with a missing,
    conflicting or shared-lane detector, are reported instead of
    becoming demand.
    """

    errors: list[DemandTransformationError] = []
    groups = defaultdict(dict)
    conflicted_groups = set()

    for observation in observations:
        try:
            movement_id = map_observation_to_movement(
                observation=observation,
                config=config,
            )

        except ValueError as exc:
            errors.append(
                DemandTransformationError(
                    message=str(exc),
                    observation_ids=(observation.observation_id,),
                    site_id=observation.site_id,
                    detector_id=observation.detector_id,
                    interval_end=observation.interval_end,
                )
            )

            continue

        group_key = (
            observation.source,
            movement_id,
            observation.interval_start,
            observation.interval_end,
        )
        detector_key = (
            observation.site_id,
            observation.detector_id,
        )

        group = groups[group_key]
        existing = group.get(detector_key)

        if existing is None:
            group[detector_key] = observation
            continue

        if existing.vehicle_count == observation.vehicle_count:
            errors.append(
                DemandTransformationError(
                    message="duplicate observation ignored",
                    observation_ids=(observation.observation_id,),
                    site_id=observation.site_id,
                    detector_id=observation.detector_id,
                    movement_id=movement_id,
                    interval_end=observation.interval_end,
                )
            )

            continue

        conflicted_groups.add(group_key)

        errors.append(
            DemandTransformationError(
                message=(
                    "detector sent different counts: "
                    f"{existing.vehicle_count} and "
                    f"{observation.vehicle_count}"
                ),
                observation_ids=(observation.observation_id,),
                site_id=observation.site_id,
                detector_id=observation.detector_id,
                movement_id=movement_id,
                interval_end=observation.interval_end,
            )
        )

    movement_detectors = find_movement_detectors(config)
    shared_detectors = find_shared_detectors(config)
    demands: list[SimulationDemand] = []

    for group_key in sorted(
        groups,
        key=lambda key: (key[2], key[1], key[0].value),
    ):
        if group_key in conflicted_groups:
            continue

        source, movement_id, interval_start, interval_end = group_key
        group = groups[group_key]

        observation_ids = tuple(
            sorted(
                observation.observation_id
                for observation in group.values()
            )
        )

        needed_shared = sorted(
            detector_id
            for _, detector_id in shared_detectors[(source, movement_id)]
        )

        if needed_shared:
            errors.append(
                DemandTransformationError(
                    message=(
                        "movement also uses shared detector(s) "
                        + ", ".join(needed_shared)
                        + "; no allocation rule adopted"
                    ),
                    observation_ids=observation_ids,
                    movement_id=movement_id,
                    interval_end=interval_end,
                )
            )

            continue

        missing_detectors = sorted(
            detector_id
            for _, detector_id in (
                movement_detectors[(source, movement_id)]
                - group.keys()
            )
        )

        if missing_detectors:
            errors.append(
                DemandTransformationError(
                    message=(
                        "no observation from detector(s) "
                        + ", ".join(missing_detectors)
                    ),
                    observation_ids=observation_ids,
                    movement_id=movement_id,
                    interval_end=interval_end,
                )
            )

            continue

        demands.append(
            SimulationDemand(
                demand_id=build_demand_id(
                    source=source,
                    movement_id=movement_id,
                    interval_end=interval_end,
                ),
                interval_start=interval_start,
                interval_end=interval_end,
                movement_id=movement_id,
                vehicle_count=sum(
                    observation.vehicle_count
                    for observation in group.values()
                ),
                source=SimulationDemandSource(source.value),
                source_observation_ids=list(observation_ids),
            )
        )

    return DemandTransformationResult(
        demands=demands,
        errors=errors,
    )


def build_simulation_demand(
    observations: list[TrafficObservation],
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
) -> DemandTransformationResult:
    """
    Load the network mappings and transform a batch of observations
    into movement demand.

    The observations are usually the accepted observations of one
    ingestion batch.
    """

    config = load_network_mappings(mapping_path)

    return transform_observations(
        observations=observations,
        config=config,
    )

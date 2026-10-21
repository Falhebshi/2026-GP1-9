import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.demand.imputation import (
    INTERVAL,
    ImputedCount,
    build_history_index,
    impute_count,
)
from backend.demand.mapper import (
    find_detector_mapping,
    map_observation_to_movement,
)
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import (
    MappingStatus,
    NetworkMappingConfig,
)
from jaadah.models.traffic import (
    ImputedDetector,
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


def find_reference_detectors(
    config: NetworkMappingConfig,
) -> dict[tuple, dict[str, set[tuple[str, str]]]]:
    """
    Return the reference detectors of each shared-lane detector, keyed by
    source, site and detector ID. They are the usable detectors on the
    same approach that count one of the shared lane's movements alone,
    grouped by that movement.
    """

    references = {}

    for shared in config.detector_mappings:
        if shared.mapping_status != MappingStatus.REQUIRES_ALLOCATION:
            continue

        by_movement = {
            movement_id: set()
            for movement_id in shared.movement_ids
        }

        for mapping in config.detector_mappings:
            if (
                mapping.mapping_status == MappingStatus.USABLE
                and mapping.source == shared.source
                and mapping.approach_id == shared.approach_id
                and mapping.movement_ids[0] in by_movement
            ):
                by_movement[mapping.movement_ids[0]].add(
                    (mapping.site_id, mapping.detector_id)
                )

        references[
            (shared.source, shared.site_id, shared.detector_id)
        ] = by_movement

    return references


def calculate_shares(
    volumes_per_lane: dict[str, float],
) -> dict[str, float]:
    """
    Return each movement's share of a shared lane from the average
    volume per lane of its exclusive lanes in the same interval.

    When the exclusive lanes counted no vehicles, there is no mix to
    follow and the lane is split equally.
    """

    total = sum(volumes_per_lane.values())

    if total == 0:
        return {
            movement_id: 1 / len(volumes_per_lane)
            for movement_id in volumes_per_lane
        }

    return {
        movement_id: volume / total
        for movement_id, volume in volumes_per_lane.items()
    }


def adjust_shares(
    shares: dict[str, float],
    share_adjustments: dict[str, float],
) -> dict[str, float]:
    """
    Apply a sensitivity adjustment to the share of one movement of a
    two-movement shared lane. The adjusted share is kept between 0 and
    1 and the other movement receives the rest.
    """

    adjusted = [
        movement_id
        for movement_id in shares
        if movement_id in share_adjustments
    ]

    if not adjusted:
        return shares

    if len(shares) != 2 or len(adjusted) != 1:
        raise ValueError(
            "a share adjustment needs a shared lane with two movements, "
            "one of them adjusted"
        )

    movement_id = adjusted[0]
    other_id = next(
        other for other in shares if other != movement_id
    )
    share = min(
        1.0,
        max(0.0, shares[movement_id] + share_adjustments[movement_id]),
    )

    return {
        movement_id: share,
        other_id: 1 - share,
    }


def split_count(
    vehicle_count: int,
    shares: dict[str, float],
) -> dict[str, int]:
    """
    Split a vehicle count into whole vehicles by share, keeping the
    total. Each part is rounded down and the remaining vehicles go to
    the largest remainders, ties to the first movement ID.
    """

    exact = {
        movement_id: vehicle_count * share
        for movement_id, share in shares.items()
    }
    parts = {
        movement_id: math.floor(value)
        for movement_id, value in exact.items()
    }
    remaining = vehicle_count - sum(parts.values())

    for movement_id in sorted(
        parts,
        key=lambda movement_id: (
            -(exact[movement_id] - parts[movement_id]),
            movement_id,
        ),
    )[:remaining]:
        parts[movement_id] += 1

    return parts


def validate_share_adjustments(
    share_adjustments: dict[str, float],
    config: NetworkMappingConfig,
) -> None:
    """Reject adjustments for movements no shared lane serves."""

    shared_movements = {
        movement_id
        for mapping in config.detector_mappings
        if mapping.mapping_status == MappingStatus.REQUIRES_ALLOCATION
        for movement_id in mapping.movement_ids
    }

    for movement_id, adjustment in share_adjustments.items():
        if movement_id not in shared_movements:
            raise ValueError(
                f"share adjustment for {movement_id}, "
                "which no shared-lane detector serves"
            )

        if not math.isfinite(adjustment) or not -1 <= adjustment <= 1:
            raise ValueError(
                "share adjustment must be between -1 and 1"
            )


def add_observation(
    group: dict,
    observation: TrafficObservation,
    movement_id: str | None,
    errors: list[DemandTransformationError],
) -> bool:
    """
    Add an observation to its group, keyed by site and detector.

    An identical repeated observation is used once and reported.
    Returns False when the detector already sent a different count for
    the interval.
    """

    detector_key = (
        observation.site_id,
        observation.detector_id,
    )
    existing = group.get(detector_key)

    if existing is None:
        group[detector_key] = observation
        return True

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

        return True

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

    return False


def find_neighbour_detectors(
    config: NetworkMappingConfig,
) -> dict[tuple, list[tuple]]:
    """
    Return the neighbours of each usable detector, keyed by source, site
    and detector ID: the other usable detectors on the same approach
    that count the same movement.
    """

    usable = [
        mapping
        for mapping in config.detector_mappings
        if mapping.mapping_status == MappingStatus.USABLE
    ]

    return {
        (mapping.source, mapping.site_id, mapping.detector_id): sorted(
            (other.source, other.site_id, other.detector_id)
            for other in usable
            if other is not mapping
            and other.source == mapping.source
            and other.approach_id == mapping.approach_id
            and other.movement_ids[0] == mapping.movement_ids[0]
        )
        for mapping in usable
    }


def impute_missing_detectors(
    accepted: list[TrafficObservation],
    history: list[TrafficObservation],
    config: NetworkMappingConfig,
    groups: dict,
    conflicted_detectors: set,
) -> dict[tuple, dict[tuple, ImputedCount]]:
    """
    Estimate the counts of usable detectors that did not report in an
    interval of the batch, at a site that did report.

    The estimates are learned from the valid history and the accepted
    observations of the batch only: rejected and conflicting
    observations are never used.

    Returns the estimates keyed like the movement groups: source,
    movement and interval, then site and detector ID. Shared-lane
    detectors are never estimated.
    """

    history_index = build_history_index(history + accepted)
    known = [
        interval
        for counts in history_index.values()
        for interval in counts
    ]

    if not known:
        return {}

    first_known, last_known = min(known), max(known)
    neighbours = find_neighbour_detectors(config)

    reporting_sites = defaultdict(set)
    current_counts = defaultdict(dict)

    for group_key, group in groups.items():
        source, _, interval_start, interval_end = group_key

        for detector_key, observation in group.items():
            reporting_sites[(source, interval_start, interval_end)].add(
                detector_key[0]
            )

            if (
                (source, interval_start, interval_end) + detector_key
                not in conflicted_detectors
            ):
                current_counts[(source, interval_start)][
                    (source,) + detector_key
                ] = observation.vehicle_count

    imputed = defaultdict(dict)

    for interval_key, sites in reporting_sites.items():
        source, interval_start, interval_end = interval_key

        for mapping in config.detector_mappings:
            if (
                mapping.mapping_status != MappingStatus.USABLE
                or mapping.source != source
                or mapping.site_id not in sites
            ):
                continue

            group_key = (
                source,
                mapping.movement_ids[0],
                interval_start,
                interval_end,
            )
            detector_key = (mapping.site_id, mapping.detector_id)

            if detector_key in groups.get(group_key, {}):
                continue

            estimate = impute_count(
                target=(source,) + detector_key,
                interval_start=interval_start,
                neighbours=neighbours[(source,) + detector_key],
                current_counts=current_counts[(source, interval_start)],
                history_index=history_index,
                first_known=first_known,
                last_known=last_known,
            )

            if estimate is not None:
                imputed[group_key][detector_key] = estimate

    return imputed


def is_quarter_hour(moment: datetime) -> bool:
    """True when a time is on :00, :15, :30 or :45 exactly."""

    return (
        moment.minute % 15 == 0
        and moment.second == 0
        and moment.microsecond == 0
    )


def validate_window(
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    """Reject a requested window that is incomplete or not aligned."""

    if (window_start is None) != (window_end is None):
        raise ValueError(
            "window_start and window_end must be given together"
        )

    if window_start is None:
        return

    for moment in (window_start, window_end):
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(
                "window times must include timezone information"
            )

        if not is_quarter_hour(moment):
            raise ValueError("window times must be on a quarter hour")

    if window_end <= window_start:
        raise ValueError("window_end must be later than window_start")


def interval_problem(
    observation: TrafficObservation,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> str | None:
    """
    Return why an observation's interval cannot be used, or None.

    Demand is built for 15-minute intervals starting on a quarter hour,
    so other intervals are refused. When a window is given, intervals
    outside it are refused too.
    """

    if observation.interval_end - observation.interval_start != INTERVAL:
        return "observation interval must be 15 minutes"

    if not is_quarter_hour(observation.interval_start):
        return "observation interval must start on a quarter hour"

    if window_start is not None and (
        observation.interval_start < window_start
        or observation.interval_end > window_end
    ):
        return "observation is outside the requested window"

    return None


def transform_observations(
    observations: list[TrafficObservation],
    config: NetworkMappingConfig,
    share_adjustments: dict[str, float] | None = None,
    history: list[TrafficObservation] | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> DemandTransformationResult:
    """
    Turn detector observations into movement demand for each interval.

    Usable detectors are summed by movement and interval. A shared-lane
    detector's count is split between its movements in proportion to
    the volume per lane of their exclusive lanes in the same interval
    (a modelled assumption), and the demand records the split
    observation in allocated_observation_ids.

    share_adjustments changes the share of one movement of a shared
    lane, e.g. {"MOV_W_N": -0.2}, for sensitivity runs.

    history holds past observations. When it is given, a usable
    detector that did not report is estimated from its neighbours or
    its past counts (see imputation.py), and the demand records it in
    imputed_detectors.

    Every demand covers one 15-minute interval starting on a quarter
    hour; observations with any other interval are reported. When
    window_start and window_end are given, observations outside the
    window are reported, and every movement with detectors gets either
    a demand or an error for every interval of the window, including
    intervals in which nothing was received.

    Observations that cannot be mapped, and movement intervals with a
    missing or conflicting detector, are reported instead of becoming
    demand.
    """

    share_adjustments = share_adjustments or {}

    validate_share_adjustments(
        share_adjustments=share_adjustments,
        config=config,
    )
    validate_window(
        window_start=window_start,
        window_end=window_end,
    )

    errors: list[DemandTransformationError] = []
    groups = defaultdict(dict)
    conflicted_groups = defaultdict(list)
    shared_groups = defaultdict(dict)
    conflicted_detectors = set()

    for observation in observations:
        problem = interval_problem(
            observation=observation,
            window_start=window_start,
            window_end=window_end,
        )

        if problem is not None:
            errors.append(
                DemandTransformationError(
                    message=problem,
                    observation_ids=(observation.observation_id,),
                    site_id=observation.site_id,
                    detector_id=observation.detector_id,
                    interval_end=observation.interval_end,
                )
            )

            continue

        mapping = find_detector_mapping(
            observation=observation,
            config=config,
        )

        if (
            mapping is not None
            and mapping.mapping_status == MappingStatus.REQUIRES_ALLOCATION
        ):
            shared_key = (
                observation.source,
                observation.interval_start,
                observation.interval_end,
            )

            if not add_observation(
                group=shared_groups[shared_key],
                observation=observation,
                movement_id=None,
                errors=errors,
            ):
                conflicted_detectors.add(
                    shared_key
                    + (observation.site_id, observation.detector_id)
                )

            continue

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

        if not add_observation(
            group=groups[group_key],
            observation=observation,
            movement_id=movement_id,
            errors=errors,
        ):
            conflicted_groups[group_key].append(observation)
            conflicted_detectors.add(
                (
                    observation.source,
                    observation.interval_start,
                    observation.interval_end,
                    observation.site_id,
                    observation.detector_id,
                )
            )

    accepted = [
        observation
        for group in list(groups.values()) + list(shared_groups.values())
        for observation in group.values()
        if (
            observation.source,
            observation.interval_start,
            observation.interval_end,
            observation.site_id,
            observation.detector_id,
        )
        not in conflicted_detectors
    ]
    imputed = (
        impute_missing_detectors(
            accepted=accepted,
            history=[
                observation
                for observation in history
                if interval_problem(observation) is None
            ],
            config=config,
            groups=groups,
            conflicted_detectors=conflicted_detectors,
        )
        if history
        else {}
    )

    def counted(group_key, detector_key):
        """The reported or estimated count of a detector, or None."""

        if detector_key in groups.get(group_key, {}):
            return groups[group_key][detector_key].vehicle_count

        if detector_key in imputed.get(group_key, {}):
            return imputed[group_key][detector_key].vehicle_count

        return None

    references = find_reference_detectors(config)
    allocated = defaultdict(dict)
    split_estimates = defaultdict(dict)
    blocked = {}

    for shared_key, shared_group in shared_groups.items():
        source, interval_start, interval_end = shared_key

        for detector_key, observation in shared_group.items():
            by_movement = references[(source,) + detector_key]
            movement_keys = {
                movement_id: (
                    source,
                    movement_id,
                    interval_start,
                    interval_end,
                )
                for movement_id in by_movement
            }

            reason = None
            detector_id = detector_key[1]

            if shared_key + detector_key in conflicted_detectors:
                reason = (
                    f"shared detector {detector_id} sent different counts"
                )

            elif not all(by_movement.values()):
                reason = (
                    f"shared detector {detector_id} has no exclusive "
                    "lane for every movement to split by"
                )

            else:
                unusable = sorted(
                    key[1]
                    for movement_id, detector_keys in by_movement.items()
                    for key in detector_keys
                    if counted(movement_keys[movement_id], key) is None
                    or shared_key + key in conflicted_detectors
                )

                if unusable:
                    reason = (
                        f"split of shared detector {detector_id} "
                        "needs detector(s) "
                        + ", ".join(unusable)
                    )

            if reason is not None:
                for group_key in movement_keys.values():
                    blocked[group_key] = (
                        reason,
                        observation.observation_id,
                    )

                continue

            volumes_per_lane = {
                movement_id: sum(
                    counted(movement_keys[movement_id], key)
                    for key in detector_keys
                )
                / len(detector_keys)
                for movement_id, detector_keys in by_movement.items()
            }
            estimates_used = {
                key: imputed[movement_keys[movement_id]][key]
                for movement_id, detector_keys in by_movement.items()
                for key in detector_keys
                if key in imputed.get(movement_keys[movement_id], {})
            }
            shares = adjust_shares(
                shares=calculate_shares(volumes_per_lane),
                share_adjustments=share_adjustments,
            )
            parts = split_count(
                vehicle_count=observation.vehicle_count,
                shares=shares,
            )

            for movement_id, part in parts.items():
                allocated[movement_keys[movement_id]][detector_key] = (
                    observation,
                    part,
                )
                split_estimates[movement_keys[movement_id]].update(
                    estimates_used
                )

    movement_detectors = find_movement_detectors(config)
    shared_detectors = find_shared_detectors(config)
    demands: list[SimulationDemand] = []

    for group_key in sorted(
        set(groups) | set(allocated) | set(blocked) | set(imputed),
        key=lambda key: (key[2], key[1], key[0].value),
    ):
        source, movement_id, interval_start, interval_end = group_key
        group = groups.get(group_key, {})
        shared_parts = allocated.get(group_key, {})
        estimates = imputed.get(group_key, {})

        observation_ids = sorted(
            [observation.observation_id for observation in group.values()]
            + [
                observation.observation_id
                for observation, _ in shared_parts.values()
            ]
        )

        if group_key in conflicted_groups:
            conflicting = conflicted_groups[group_key]

            errors.append(
                DemandTransformationError(
                    message=(
                        "no demand because detector(s) "
                        + ", ".join(
                            sorted(
                                {
                                    observation.detector_id
                                    for observation in conflicting
                                }
                            )
                        )
                        + " sent different counts"
                    ),
                    observation_ids=tuple(
                        sorted(
                            set(observation_ids)
                            | {
                                observation.observation_id
                                for observation in conflicting
                            }
                        )
                    ),
                    movement_id=movement_id,
                    interval_end=interval_end,
                )
            )

            continue

        if group_key in blocked:
            reason, shared_observation_id = blocked[group_key]

            errors.append(
                DemandTransformationError(
                    message=reason,
                    observation_ids=tuple(
                        sorted(observation_ids + [shared_observation_id])
                    ),
                    movement_id=movement_id,
                    interval_end=interval_end,
                )
            )

            continue

        missing_detectors = sorted(
            detector_id
            for _, detector_id in (
                (
                    movement_detectors[(source, movement_id)]
                    | shared_detectors[(source, movement_id)]
                )
                - group.keys()
                - shared_parts.keys()
                - estimates.keys()
            )
        )

        if missing_detectors:
            errors.append(
                DemandTransformationError(
                    message=(
                        "no observation from detector(s) "
                        + ", ".join(missing_detectors)
                    ),
                    observation_ids=tuple(observation_ids),
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
                vehicle_count=(
                    sum(
                        observation.vehicle_count
                        for observation in group.values()
                    )
                    + sum(part for _, part in shared_parts.values())
                    + sum(
                        estimate.vehicle_count
                        for estimate in estimates.values()
                    )
                ),
                source=SimulationDemandSource(source.value),
                source_observation_ids=observation_ids,
                allocated_observation_ids=sorted(
                    observation.observation_id
                    for observation, _ in shared_parts.values()
                ),
                imputed_detectors=[
                    ImputedDetector(
                        site_id=estimate.site_id,
                        detector_id=estimate.detector_id,
                        method=estimate.method,
                    )
                    for _, estimate in sorted(
                        (
                            estimates
                            | split_estimates.get(group_key, {})
                        ).items()
                    )
                ],
            )
        )

    if window_start is not None:
        errors.extend(
            find_window_gaps(
                observations=observations,
                config=config,
                handled=(
                    set(groups) | set(allocated) | set(blocked) | set(imputed)
                ),
                movement_detectors=movement_detectors,
                shared_detectors=shared_detectors,
                window_start=window_start,
                window_end=window_end,
            )
        )

    return DemandTransformationResult(
        demands=demands,
        errors=errors,
    )


def find_window_gaps(
    observations: list[TrafficObservation],
    config: NetworkMappingConfig,
    handled: set[tuple],
    movement_detectors: dict,
    shared_detectors: dict,
    window_start: datetime,
    window_end: datetime,
) -> list[DemandTransformationError]:
    """
    Report every movement and interval of the window that received no
    observation at all, so the window is fully accounted for.
    """

    sources = sorted(
        {observation.source for observation in observations}
        or {mapping.source for mapping in config.detector_mappings},
        key=lambda source: source.value,
    )
    needed = defaultdict(set)

    for detectors in (movement_detectors, shared_detectors):
        for (source, movement_id), detector_keys in list(detectors.items()):
            needed[(source, movement_id)] |= detector_keys

    gaps = []
    interval_start = window_start

    while interval_start < window_end:
        interval_end = interval_start + INTERVAL

        for source in sources:
            for movement_id in sorted(
                movement
                for (movement_source, movement) in needed
                if movement_source == source
            ):
                group_key = (source, movement_id, interval_start, interval_end)

                if group_key in handled:
                    continue

                gaps.append(
                    DemandTransformationError(
                        message=(
                            "no observation from detector(s) "
                            + ", ".join(
                                sorted(
                                    detector_id
                                    for _, detector_id in needed[
                                        (source, movement_id)
                                    ]
                                )
                            )
                        ),
                        movement_id=movement_id,
                        interval_end=interval_end,
                    )
                )

        interval_start = interval_end

    return gaps


def build_simulation_demand(
    observations: list[TrafficObservation],
    mapping_path: str | Path = DEFAULT_MAPPING_PATH,
    share_adjustments: dict[str, float] | None = None,
    history: list[TrafficObservation] | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> DemandTransformationResult:
    """
    Load the network mappings and transform a batch of observations
    into movement demand.

    The observations are usually the accepted observations of one
    ingestion batch. share_adjustments (sensitivity runs), history
    (estimating detectors that did not report) and the requested window
    are passed on to transform_observations.
    """

    config = load_network_mappings(mapping_path)

    return transform_observations(
        observations=observations,
        config=config,
        share_adjustments=share_adjustments,
        history=history,
        window_start=window_start,
        window_end=window_end,
    )

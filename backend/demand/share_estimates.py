"""
Demand for movements that no detector counts.

Some movements have no detector for a source. At RCRC site 1444 these
are the uncontrolled right-turn slips and the south bypass. Their demand
is estimated as a ratio of the demand of observed movements on the same
approach in the same interval (the basis movements):

    estimated demand = ratio x (sum of the basis movements' demand)

The ratio is defined so that a turning count can replace it directly:
the counted slip volume divided by the counted volume of the basis
movements over the same period. Every ratio has a low, central and
high value, so results can be run for each (sensitivity), and records
where it came from (share_origin). The ratios are kept in a JSON file,
not in code, so measured values can replace assumed ones without a
code change.
"""

import json
from datetime import datetime
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.demand.imputation import whole_vehicles
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.traffic import (
    ImputedDetector,
    ShareEstimate,
    ShareOrigin,
    ShareScenario,
    SimulationDemand,
    SimulationDemandSource,
    TrafficObservationSource,
)


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SHARE_CONFIG_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "traffic_demand"
    / "undetected_movement_shares.json"
)


# ============================================================
# CONFIGURATION
# ============================================================

class RatioRange(BaseModel):
    """Low, central and high values of one ratio."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    low: float = Field(ge=0)
    central: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "RatioRange":
        """Require low <= central <= high."""

        if not self.low <= self.central <= self.high:
            raise ValueError("ratio must satisfy low <= central <= high")

        return self

    def value(self, scenario: ShareScenario) -> float:
        return getattr(self, scenario.value)


class UndetectedMovementShare(BaseModel):
    """How one undetected movement's demand is estimated for one source."""

    model_config = ConfigDict(extra="forbid")

    movement_id: str
    source: TrafficObservationSource
    basis_movement_ids: list[str] = Field(min_length=1)
    ratio: RatioRange
    share_origin: ShareOrigin
    note: str

    @field_validator("movement_id", "note")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("value must not be empty")

        return value

    @field_validator("basis_movement_ids")
    @classmethod
    def validate_basis(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]

        if any(not value for value in cleaned):
            raise ValueError("basis movement ID must not be empty")

        if len(cleaned) != len(set(cleaned)):
            raise ValueError("basis movement IDs must be unique")

        return cleaned

    @model_validator(mode="after")
    def validate_not_own_basis(self) -> "UndetectedMovementShare":
        if self.movement_id in self.basis_movement_ids:
            raise ValueError("a movement cannot be its own basis")

        return self


class ShareConfig(BaseModel):
    """The ratios used for every undetected movement."""

    model_config = ConfigDict(extra="forbid")

    config_version: str
    description: str
    shares: list[UndetectedMovementShare] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique(self) -> "ShareConfig":
        keys = [(item.source, item.movement_id) for item in self.shares]

        if len(keys) != len(set(keys)):
            raise ValueError("each movement may have one share per source")

        return self


def validate_share_config(
    share_config: ShareConfig,
    config: NetworkMappingConfig,
) -> None:
    """
    Check the ratios against the network mapping: the movement and its
    basis movements exist on the same approach, the movement has no
    detector for the source (a counted movement is never estimated),
    and every basis movement has one.
    """

    movements = config.canonical_movements
    detected = {
        (mapping.source, movement_id)
        for mapping in config.detector_mappings
        for movement_id in mapping.movement_ids
    }

    for item in share_config.shares:
        label = f"{item.source.value} {item.movement_id}"

        if item.movement_id not in movements:
            raise ValueError(f"{label}: unknown movement")

        approach_id = movements[item.movement_id].approach_id

        if approach_id is None:
            raise ValueError(f"{label}: movement has no approach")

        if (item.source, item.movement_id) in detected:
            raise ValueError(
                f"{label}: movement has a detector and must not be estimated"
            )

        for basis_id in item.basis_movement_ids:
            if basis_id not in movements:
                raise ValueError(f"{label}: unknown basis movement {basis_id}")

            if movements[basis_id].approach_id != approach_id:
                raise ValueError(
                    f"{label}: basis movement {basis_id} is on another approach"
                )

            if (item.source, basis_id) not in detected:
                raise ValueError(
                    f"{label}: basis movement {basis_id} has no detector"
                )


def load_share_config(
    path: str | Path = DEFAULT_SHARE_CONFIG_PATH,
) -> ShareConfig:
    """Read a share configuration file."""

    return ShareConfig.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


# ============================================================
# ESTIMATION
# ============================================================

def estimate_undetected_movements(
    demands: list[SimulationDemand],
    share_config: ShareConfig,
    config: NetworkMappingConfig,
    scenario: ShareScenario = ShareScenario.CENTRAL,
    sources: set[TrafficObservationSource] | None = None,
    intervals: list[tuple[datetime, datetime]] | None = None,
) -> tuple[list[SimulationDemand], list[tuple[str, datetime, str]]]:
    """
    Estimate the demand of every configured undetected movement.

    An estimate is made for each interval in which every basis movement
    has a demand. intervals (a requested window) adds intervals with no
    demand at all, so each is either estimated or reported. sources
    limits the estimates to the sources present in the batch (default:
    the sources of the demands).

    Returns the estimated demands and the problems, each as
    (movement ID, interval end, message).
    """

    validate_share_config(share_config, config)

    by_key = {
        (demand.source.value, demand.movement_id, demand.interval_start): demand
        for demand in demands
    }
    sources = sources if sources is not None else {
        TrafficObservationSource(demand.source.value)
        for demand in demands
        if demand.source.value in TrafficObservationSource._value2member_map_
    }

    estimates: list[SimulationDemand] = []
    problems: list[tuple[str, datetime, str]] = []

    for item in share_config.shares:
        if item.source not in sources:
            continue

        source = item.source.value
        candidate_intervals = {
            (demand.interval_start, demand.interval_end)
            for demand in demands
            if demand.source.value == source
            and demand.movement_id in item.basis_movement_ids
        } | set(intervals or [])

        ratio = item.ratio.value(scenario)

        for interval_start, interval_end in sorted(candidate_intervals):
            basis = [
                by_key.get((source, basis_id, interval_start))
                for basis_id in item.basis_movement_ids
            ]
            missing = [
                basis_id
                for basis_id, demand in zip(item.basis_movement_ids, basis)
                if demand is None
            ]

            if missing:
                problems.append(
                    (
                        item.movement_id,
                        interval_end,
                        "no estimate: basis movement(s) "
                        + ", ".join(missing)
                        + " have no demand",
                    )
                )
                continue

            imputed = {}

            for demand in basis:
                for detector in demand.imputed_detectors:
                    imputed.setdefault(
                        (detector.site_id, detector.detector_id),
                        detector,
                    )

            estimates.append(
                SimulationDemand(
                    demand_id=_demand_id(source, item.movement_id, interval_end),
                    interval_start=interval_start,
                    interval_end=interval_end,
                    movement_id=item.movement_id,
                    vehicle_count=whole_vehicles(
                        ratio * sum(demand.vehicle_count for demand in basis)
                    ),
                    source=SimulationDemandSource(source),
                    source_observation_ids=[],
                    imputed_detectors=[
                        ImputedDetector.model_validate(detector.model_dump())
                        for _, detector in sorted(imputed.items())
                    ],
                    share_estimate=ShareEstimate(
                        ratio=ratio,
                        scenario=scenario,
                        share_origin=item.share_origin,
                        basis_demand_ids=[demand.demand_id for demand in basis],
                    ),
                )
            )

    return estimates, problems


def _demand_id(source: str, movement_id: str, interval_end: datetime) -> str:
    """Same format as backend.demand.service.build_demand_id."""

    code = {"synthetic": "SYN", "rcrc": "RCRC"}[source]

    return f"DEM_{code}_{movement_id}_{interval_end.strftime('%Y%m%dT%H%M')}"

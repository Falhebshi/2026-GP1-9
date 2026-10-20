from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# Project and local data paths
REPO_ROOT = Path(__file__).resolve().parents[2]

PRIVATE_DATA_DIR = REPO_ROOT.parent / "jaadah-private-data"

PROFILE_DIR = (
    PRIVATE_DATA_DIR
    / "processed"
    / "rcrc_sample"
)

PROFILE_SUMMARY_PATH = PROFILE_DIR / "rcrc_profile_summary.json"
DETECTOR_VOLUME_SUMMARY_PATH = PROFILE_DIR / "detector_volume_summary.csv"
DETECTOR_TIME_OF_DAY_PROFILE_PATH = PROFILE_DIR / "detector_time_of_day_profile.csv"
OVERALL_TIME_OF_DAY_PROFILE_PATH = PROFILE_DIR / "time_of_day_profile.csv"
DAY_TYPE_TIME_PROFILE_PATH = PROFILE_DIR / "day_type_time_profile.csv"
TEMPORAL_AUTOCORRELATION_SUMMARY_PATH = (
    PROFILE_DIR / "temporal_autocorrelation_summary.csv"
)

SYNTHETIC_TRAFFIC_DIR = (
    REPO_ROOT
    / "data"
    / "synthetic_traffic"
)

SYNTHETIC_DATABASE_PATH = (
    SYNTHETIC_TRAFFIC_DIR
    / "synthetic_traffic.db"
)

INITIAL_HISTORY_DAYS = 7

ScenarioLevel = Literal["low", "normal", "high"]


SCENARIO_SCALES: dict[ScenarioLevel, float] = {
    "low": 0.80,
    "normal": 1.00,
    "high": 1.20,
}


@dataclass(frozen=True)
class SyntheticSourceConfig:
    """
    Configuration for the synthetic external traffic source.

    Scenario scaling is a controlled synthetic-development setting and
    should not be interpreted as a measured definition of low, normal,
    or high traffic conditions in Riyadh.
    """

    seed: int = 42
    scenario: ScenarioLevel = "normal"
    interval_minutes: int = 15
    timezone: str = "Asia/Riyadh"
    variation_scale: float = 1.0

    @property
    def scenario_scale(self) -> float:
        return SCENARIO_SCALES[self.scenario]
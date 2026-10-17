import json
import random

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import sqrt

import pandas as pd

from traffic_source.synthetic.config import (
    PROFILE_SUMMARY_PATH,
    DETECTOR_VOLUME_SUMMARY_PATH,
    DETECTOR_TIME_OF_DAY_PROFILE_PATH,
    OVERALL_TIME_OF_DAY_PROFILE_PATH,
    DAY_TYPE_TIME_PROFILE_PATH,
    TEMPORAL_AUTOCORRELATION_SUMMARY_PATH,
    SyntheticSourceConfig,
)


@dataclass(frozen=True)
class SyntheticDetectorObservation:
    """
    One generated RCRC-shaped detector-volume observation.

    Internal Python field names are kept clean. The API layer maps them
    to the exact provider-facing field names such as "Site ID" and
    "Date  & Time".
    """

    site_id: int
    detector_id: int
    timestamp: datetime
    volume: int
    description: str


@dataclass(frozen=True)
class SyntheticTrafficProfiles:
    """
    Processed sample traffic profiles used as the reference for synthetic
    traffic generation.
    """

    profile_summary: dict
    detector_volume_summary: pd.DataFrame
    detector_time_of_day_profile: pd.DataFrame
    overall_time_of_day_profile: pd.DataFrame
    day_type_time_profile: pd.DataFrame
    temporal_autocorrelation_summary: pd.DataFrame


def load_profiles() -> SyntheticTrafficProfiles:
    """
    Load the processed reference profiles used to generate synthetic
    detector observations.
    """

    with PROFILE_SUMMARY_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        profile_summary = json.load(file)

    return SyntheticTrafficProfiles(
        profile_summary=profile_summary,
        detector_volume_summary=pd.read_csv(
            DETECTOR_VOLUME_SUMMARY_PATH
        ),
        detector_time_of_day_profile=pd.read_csv(
            DETECTOR_TIME_OF_DAY_PROFILE_PATH
        ),
        overall_time_of_day_profile=pd.read_csv(
            OVERALL_TIME_OF_DAY_PROFILE_PATH
        ),
        day_type_time_profile=pd.read_csv(
            DAY_TYPE_TIME_PROFILE_PATH
        ),
        temporal_autocorrelation_summary=pd.read_csv(
            TEMPORAL_AUTOCORRELATION_SUMMARY_PATH
        ),
    )


def get_day_type(timestamp: datetime) -> str:
    """
    Map a date to the day-type categories used by the profiles.

    Sunday through Thursday are treated as workdays.
    Friday and Saturday use their own profile categories.
    """

    if timestamp.weekday() == 4:
        return "friday"

    if timestamp.weekday() == 5:
        return "saturday"

    return "workday"


@dataclass(frozen=True)
class TargetDetector:
    """A synthetic detector attached to one incoming SUMO lane."""

    detector_id: int
    description: str


TARGET_SITE_ID = 9


TARGET_DETECTORS = (
    TargetDetector(1, "SYN-EB-L1-L-STB"),
    TargetDetector(2, "SYN-EB-L2-LT-STB"),
    TargetDetector(3, "SYN-EB-L3-T-STB"),

    TargetDetector(4, "SYN-SB-L1-L-STB"),
    TargetDetector(5, "SYN-SB-L2-L-STB"),
    TargetDetector(6, "SYN-SB-L3-L-STB"),

    TargetDetector(7, "SYN-NB-L1-T-STB"),
    TargetDetector(8, "SYN-NB-L2-T-STB"),

    TargetDetector(9, "SYN-WB-L1-L-STB"),
    TargetDetector(10, "SYN-WB-L2-LT-STB"),
    TargetDetector(11, "SYN-WB-L3-T-STB"),
    TargetDetector(12, "SYN-WB-L4-T-STB"),
)


def assign_reference_templates(
    profiles: SyntheticTrafficProfiles,
    config: SyntheticSourceConfig,
) -> tuple[dict[int, int], float]:
    """
    Assign one unique reference detector profile to each target detector.

    The assignment is reproducible for a given seed. The returned
    normalization factor keeps the average traffic level of the selected
    templates aligned with the overall reference-detector average.
    """

    volume_summary = profiles.detector_volume_summary

    required_columns = {
        "detector_id",
        "mean_volume",
    }

    if not required_columns.issubset(
        volume_summary.columns
    ):
        raise ValueError(
            "detector_volume_summary must contain "
            "'detector_id' and 'mean_volume' columns"
        )

    reference_ids = sorted(
        int(detector_id)
        for detector_id in volume_summary[
            "detector_id"
        ].dropna().unique()
    )

    target_count = len(TARGET_DETECTORS)

    if len(reference_ids) < target_count:
        raise ValueError(
            "Not enough reference detector profiles to assign one "
            "unique template to each target detector"
        )

    template_random = random.Random(
        config.seed
    )

    selected_ids = template_random.sample(
        reference_ids,
        target_count,
    )

    template_by_detector = {
        target.detector_id: reference_id
        for target, reference_id in zip(
            TARGET_DETECTORS,
            selected_ids,
        )
    }

    overall_reference_mean = float(
        volume_summary["mean_volume"].mean()
    )

    selected_reference_mean = float(
        volume_summary[
            volume_summary["detector_id"].isin(
                selected_ids
            )
        ]["mean_volume"].mean()
    )

    if selected_reference_mean <= 0:
        raise ValueError(
            "Selected reference detector profiles have an invalid "
            "average traffic volume"
        )

    normalization_factor = (
        overall_reference_mean
        / selected_reference_mean
    )

    return (
        template_by_detector,
        normalization_factor,
    )


def calculate_expected_volume(
    target_detector_id: int,
    timestamp: datetime,
    profiles: SyntheticTrafficProfiles,
    config: SyntheticSourceConfig,
    template_by_detector: dict[int, int],
    normalization_factor: float,
) -> float:
    """
    Calculate the expected traffic volume for one target detector before
    stochastic variation is added.

    The target detector uses its assigned reference detector as a behavioral
    template while retaining its own synthetic identity.
    """

    if target_detector_id not in template_by_detector:
        raise ValueError(
            f"No reference template assigned to target detector "
            f"{target_detector_id}"
        )

    reference_detector_id = template_by_detector[
        target_detector_id
    ]

    time_of_day = timestamp.strftime(
        "%H:%M"
    )
    day_type = get_day_type(timestamp)

    detector_match = (
        profiles.detector_time_of_day_profile[
            (
                profiles.detector_time_of_day_profile[
                    "detector_id"
                ]
                == reference_detector_id
            )
            & (
                profiles.detector_time_of_day_profile[
                    "time_of_day"
                ]
                == time_of_day
            )
        ]
    )

    if detector_match.empty:
        raise ValueError(
            f"No detector profile found for reference detector "
            f"{reference_detector_id} at {time_of_day}"
        )

    overall_match = (
        profiles.overall_time_of_day_profile[
            profiles.overall_time_of_day_profile[
                "time_of_day"
            ]
            == time_of_day
        ]
    )

    if overall_match.empty:
        raise ValueError(
            f"No overall time-of-day profile found for "
            f"{time_of_day}"
        )

    day_type_match = (
        profiles.day_type_time_profile[
            (
                profiles.day_type_time_profile[
                    "day_type"
                ]
                == day_type
            )
            & (
                profiles.day_type_time_profile[
                    "time_of_day"
                ]
                == time_of_day
            )
        ]
    )

    if day_type_match.empty:
        raise ValueError(
            f"No {day_type} profile found for "
            f"{time_of_day}"
        )

    detector_time_mean = float(
        detector_match.iloc[0][
            "mean_volume"
        ]
    )

    overall_time_mean = float(
        overall_match.iloc[0][
            "mean_volume"
        ]
    )

    overall_mean = float(
        profiles.profile_summary[
            "overall_volume"
        ][
            "mean_volume_per_detector_per_15_min_interval"
        ]
    )

    day_type_mean = float(
        day_type_match.iloc[0][
            "day_type_mean_volume"
        ]
    )

    day_type_shape = float(
        day_type_match.iloc[0][
            "normalized_shape"
        ]
    )

    overall_shape = (
        overall_time_mean
        / overall_mean
    )

    day_type_level_adjustment = (
        day_type_mean
        / overall_mean
    )

    day_type_shape_adjustment = (
        day_type_shape
        / overall_shape
    )

    expected_volume = (
        detector_time_mean
        * normalization_factor
        * day_type_level_adjustment
        * day_type_shape_adjustment
        * config.scenario_scale
    )

    return expected_volume


class SyntheticTrafficGenerator:
    """
    Generate reproducible synthetic detector volumes with shared variation
    and temporal persistence.
    """

    def __init__(
        self,
        profiles: SyntheticTrafficProfiles,
        config: SyntheticSourceConfig,
    ) -> None:
        self.profiles = profiles
        self.config = config

        (
            self.template_by_detector,
            self.normalization_factor,
        ) = assign_reference_templates(
            profiles=profiles,
            config=config,
        )

        self.random = random.Random(
            config.seed
        )

        self.previous_deviation: dict[
            int,
            float,
        ] = {}

        self.shared_correlation = float(
            profiles.profile_summary[
                "cross_detector_dependence"
            ][
                "mean_residual_correlation_after_removing_time_of_day_and_day_level"
            ]
        )

        if not (
            0.0
            <= self.shared_correlation
            <= 1.0
        ):
            raise ValueError(
                "Shared detector correlation must be between 0 and 1"
            )

    def _get_reference_detector_id(
        self,
        target_detector_id: int,
    ) -> int:
        """Return the reference profile assigned to a target detector."""

        try:
            return self.template_by_detector[
                target_detector_id
            ]
        except KeyError as exc:
            raise ValueError(
                f"No reference template assigned to target detector "
                f"{target_detector_id}"
            ) from exc

    def _get_detector_standard_deviation(
        self,
        target_detector_id: int,
        timestamp: datetime,
    ) -> float:
        """
        Return the time-specific variability inherited from the assigned
        reference profile.
        """

        reference_detector_id = (
            self._get_reference_detector_id(
                target_detector_id
            )
        )

        time_of_day = timestamp.strftime(
            "%H:%M"
        )

        match = (
            self.profiles.detector_time_of_day_profile[
                (
                    self.profiles.detector_time_of_day_profile[
                        "detector_id"
                    ]
                    == reference_detector_id
                )
                & (
                    self.profiles.detector_time_of_day_profile[
                        "time_of_day"
                    ]
                    == time_of_day
                )
            ]
        )

        if match.empty:
            raise ValueError(
                f"No variability profile found for reference detector "
                f"{reference_detector_id} at {time_of_day}"
            )

        reference_standard_deviation = float(
            match.iloc[0][
                "std_volume"
            ]
        )

        return (
            reference_standard_deviation
            * self.normalization_factor
            * self.config.scenario_scale
        )

    def _get_temporal_persistence(
        self,
        target_detector_id: int,
    ) -> float:
        """
        Return the temporal persistence inherited from the assigned
        reference profile.
        """

        reference_detector_id = (
            self._get_reference_detector_id(
                target_detector_id
            )
        )

        match = (
            self.profiles.temporal_autocorrelation_summary[
                self.profiles.temporal_autocorrelation_summary[
                    "detector_id"
                ]
                == reference_detector_id
            ]
        )

        if match.empty:
            raise ValueError(
                f"No temporal persistence profile found for reference "
                f"detector {reference_detector_id}"
            )

        persistence = float(
            match.iloc[0][
                "adjusted_lag1_correlation"
            ]
        )

        if not (
            0.0
            <= persistence
            < 1.0
        ):
            raise ValueError(
                f"Temporal persistence for reference detector "
                f"{reference_detector_id} must be between 0 and 1"
            )

        return persistence

    def generate_volume(
        self,
        target_detector_id: int,
        timestamp: datetime,
        shared_noise: float,
    ) -> int:
        """
        Generate one non-negative integer traffic count for a target detector.

        The generated value combines its expected traffic level with shared
        variation, detector-specific variation, and temporal persistence.
        """

        expected_volume = (
            calculate_expected_volume(
                target_detector_id=target_detector_id,
                timestamp=timestamp,
                profiles=self.profiles,
                config=self.config,
                template_by_detector=self.template_by_detector,
                normalization_factor=self.normalization_factor,
            )
        )

        standard_deviation = (
            self._get_detector_standard_deviation(
                target_detector_id,
                timestamp,
            )
        )

        persistence = (
            self._get_temporal_persistence(
                target_detector_id
            )
        )

        detector_noise = (
            self.random.gauss(
                0.0,
                1.0,
            )
        )

        innovation = (
            sqrt(
                self.shared_correlation
            )
            * shared_noise
            + sqrt(
                1.0
                - self.shared_correlation
            )
            * detector_noise
        )

        previous = (
            self.previous_deviation.get(
                target_detector_id,
                0.0,
            )
        )

        current_deviation = (
            persistence
            * previous
            + sqrt(
                1.0
                - persistence**2
            )
            * innovation
        )

        self.previous_deviation[
            target_detector_id
        ] = current_deviation

        synthetic_volume = (
            expected_volume
            + self.config.variation_scale
            * standard_deviation
            * current_deviation
        )

        return max(
            0,
            round(
                synthetic_volume
            ),
        )

    def get_detector_ids(
        self,
    ) -> list[int]:
        """Return the synthetic detector IDs available for generation."""

        return sorted(
            detector.detector_id
            for detector in TARGET_DETECTORS
        )

    def _get_target_detector(
        self,
        detector_id: int,
    ) -> TargetDetector:
        """Return the target detector definition for a detector ID."""

        for detector in TARGET_DETECTORS:
            if (
                detector.detector_id
                == detector_id
            ):
                return detector

        raise ValueError(
            f"Unknown detector ID: "
            f"{detector_id}"
        )

    def reset(
        self,
        seed: int | None = None,
    ) -> None:
        """
        Reset the random generator and temporal state.

        If no seed is provided, the configured seed is used.
        """

        self.random.seed(
            self.config.seed
            if seed is None
            else seed
        )

        self.previous_deviation.clear()

    def _validate_timestamp_alignment(
        self,
        timestamp: datetime,
    ) -> None:
        """Ensure a timestamp lies on a configured generation boundary."""

        if (
            self.config.interval_minutes
            <= 0
        ):
            raise ValueError(
                "interval_minutes must be greater than zero"
            )

        if (
            timestamp.second != 0
            or timestamp.microsecond != 0
            or (
                timestamp.minute
                % self.config.interval_minutes
                != 0
            )
        ):
            raise ValueError(
                f"Timestamp "
                f"{timestamp.isoformat()} "
                f"is not aligned to a "
                f"{self.config.interval_minutes}-minute interval"
            )

    def generate_timestamp(
        self,
        timestamp: datetime,
        detector_ids: list[int] | None = None,
    ) -> list[
        SyntheticDetectorObservation
    ]:
        """
        Generate one interval-ending observation for the target detectors.

        The timestamp labels the end of the observation interval. With a
        15-minute interval, a timestamp of 12:00 represents traffic observed
        from 11:45 up to 12:00.
        """

        self._validate_timestamp_alignment(
            timestamp
        )

        available_detector_ids = (
            self.get_detector_ids()
        )

        if detector_ids is None:
            requested_detector_ids = (
                available_detector_ids
            )

        else:
            requested_detector_ids = sorted(
                {
                    int(detector_id)
                    for detector_id
                    in detector_ids
                }
            )

            if not requested_detector_ids:
                raise ValueError(
                    "At least one detector ID is required for generation"
                )

        unknown_detector_ids = [
            detector_id
            for detector_id
            in requested_detector_ids
            if detector_id
            not in available_detector_ids
        ]

        if unknown_detector_ids:
            raise ValueError(
                "Unknown detector ID(s): "
                + ", ".join(
                    str(detector_id)
                    for detector_id
                    in unknown_detector_ids
                )
            )

        shared_noise = self.random.gauss(
            0.0,
            1.0,
        )

        generated_by_detector: dict[
            int,
            SyntheticDetectorObservation,
        ] = {}

        # All target detectors are generated internally so that requesting
        # only a subset does not change the random sequence for that timestamp.
        for detector_id in available_detector_ids:
            target_detector = (
                self._get_target_detector(
                    detector_id
                )
            )

            generated_by_detector[
                detector_id
            ] = SyntheticDetectorObservation(
                site_id=TARGET_SITE_ID,
                detector_id=detector_id,
                timestamp=timestamp,
                volume=self.generate_volume(
                    target_detector_id=detector_id,
                    timestamp=timestamp,
                    shared_noise=shared_noise,
                ),
                description=(
                    target_detector.description
                ),
            )

        return [
            generated_by_detector[
                detector_id
            ]
            for detector_id
            in requested_detector_ids
        ]

    def generate_range(
        self,
        start: datetime,
        end: datetime,
        detector_ids: list[int] | None = None,
    ) -> list[
        SyntheticDetectorObservation
    ]:
        """
        Generate observations covering the requested traffic time window.

        Because record timestamps label the end of each observation interval,
        a requested range from 08:00 to 09:00 produces records timestamped
        08:15, 08:30, 08:45, and 09:00.
        """

        self._validate_timestamp_alignment(
            start
        )
        self._validate_timestamp_alignment(
            end
        )

        if end <= start:
            raise ValueError(
                "end must be later than start"
            )

        interval = timedelta(
            minutes=(
                self.config.interval_minutes
            )
        )

        timestamp = (
            start
            + interval
        )

        observations: list[
            SyntheticDetectorObservation
        ] = []

        while timestamp <= end:
            observations.extend(
                self.generate_timestamp(
                    timestamp=timestamp,
                    detector_ids=detector_ids,
                )
            )

            timestamp += interval

        return observations
from dataclasses import replace
from datetime import datetime
import pandas as pd
import pytest
from traffic_source.synthetic.config import (
    SyntheticSourceConfig,
)
from traffic_source.synthetic.generator import (
    TARGET_DETECTORS,
    TARGET_SITE_ID,
    SyntheticTrafficGenerator,
    SyntheticTrafficProfiles,
    assign_reference_templates,
    get_day_type,
    load_profiles,
)
def make_assignment_profiles(
    detector_count: int = 18,
) -> SyntheticTrafficProfiles:
    """
    Create the minimum reference-profile data needed to test
    target-template assignment.
    """
    reference_ids = list(
        range(
            1001,
            1001 + detector_count,
        )
    )
    mean_volumes = [
        50.0 + index
        for index in range(detector_count)
    ]
    return SyntheticTrafficProfiles(
        profile_summary={},
        detector_volume_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "mean_volume": mean_volumes,
            }
        ),
        detector_time_of_day_profile=pd.DataFrame(),
        overall_time_of_day_profile=pd.DataFrame(),
        day_type_time_profile=pd.DataFrame(),
        temporal_autocorrelation_summary=pd.DataFrame(),
    )
def test_target_detector_count_is_16() -> None:
    assert len(TARGET_DETECTORS) == 16
def test_target_detector_ids_are_1_to_16() -> None:
    detector_ids = [
        detector.detector_id
        for detector in TARGET_DETECTORS
    ]
    assert detector_ids == list(
        range(1, 17)
    )
def test_target_detector_descriptions_are_unique() -> None:
    descriptions = [
        detector.description
        for detector in TARGET_DETECTORS
    ]
    assert len(descriptions) == len(
        set(descriptions)
    )
def test_assignment_selects_16_unique_reference_profiles() -> None:
    profiles = make_assignment_profiles()
    mapping, _ = assign_reference_templates(
        profiles=profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    selected_reference_ids = list(
        mapping.values()
    )
    assert len(mapping) == 16
    assert set(mapping.keys()) == set(
        range(1, 17)
    )
    assert len(
        set(selected_reference_ids)
    ) == 16
def test_assignment_uses_only_available_reference_profiles() -> None:
    profiles = make_assignment_profiles()
    mapping, _ = assign_reference_templates(
        profiles=profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    available_ids = set(
        profiles.detector_volume_summary[
            "detector_id"
        ]
    )
    selected_ids = set(
        mapping.values()
    )
    assert selected_ids.issubset(
        available_ids
    )
def test_same_seed_produces_same_template_assignment() -> None:
    profiles = make_assignment_profiles()
    first_mapping, first_factor = (
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
    )
    second_mapping, second_factor = (
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
    )
    assert first_mapping == second_mapping
    assert first_factor == pytest.approx(
        second_factor
    )
def test_normalization_aligns_selected_mean_with_reference_mean() -> None:
    profiles = make_assignment_profiles()
    mapping, normalization_factor = (
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
    )
    volume_summary = (
        profiles.detector_volume_summary
    )
    selected_ids = set(
        mapping.values()
    )
    overall_mean = float(
        volume_summary[
            "mean_volume"
        ].mean()
    )
    selected_mean = float(
        volume_summary[
            volume_summary[
                "detector_id"
            ].isin(selected_ids)
        ][
            "mean_volume"
        ].mean()
    )
    normalized_selected_mean = (
        selected_mean
        * normalization_factor
    )
    assert normalized_selected_mean == pytest.approx(
        overall_mean
    )
def test_assignment_rejects_too_few_reference_profiles() -> None:
    profiles = make_assignment_profiles(
        detector_count=11
    )
    with pytest.raises(
        ValueError,
        match="Not enough reference detector profiles",
    ):
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
@pytest.mark.parametrize(
    "missing_column",
    [
        "detector_id",
        "mean_volume",
    ],
)
def test_assignment_rejects_missing_required_columns(
    missing_column: str,
) -> None:
    profiles = make_assignment_profiles()
    profiles.detector_volume_summary.drop(
        columns=[missing_column],
        inplace=True,
    )
    with pytest.raises(
        ValueError,
        match="must contain",
    ):
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
# ---------------------------------------------------------------------------
# Basic observation generation
# ---------------------------------------------------------------------------
def make_generation_profiles() -> SyntheticTrafficProfiles:
    """
    Create in-memory profiles with enough information to generate
    observations for one workday timestamp.
    """
    reference_ids = list(
        range(1001, 1019)
    )
    detector_means = {
        detector_id: 80.0 + index * 2.0
        for index, detector_id
        in enumerate(reference_ids)
    }
    detector_time_rows = [
        {
            "detector_id": detector_id,
            "time_of_day": "08:15",
            "mean_volume": detector_means[
                detector_id
            ],
            "std_volume": 10.0,
        }
        for detector_id in reference_ids
    ]
    return SyntheticTrafficProfiles(
        profile_summary={
            "overall_volume": {
                "mean_volume_per_detector_per_15_min_interval": 100.0,
            },
            "cross_detector_dependence": {
                "mean_residual_correlation_after_removing_time_of_day_and_day_level": 0.25,
            },
        },
        detector_volume_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "mean_volume": [
                    detector_means[
                        detector_id
                    ]
                    for detector_id
                    in reference_ids
                ],
            }
        ),
        detector_time_of_day_profile=pd.DataFrame(
            detector_time_rows
        ),
        overall_time_of_day_profile=pd.DataFrame(
            {
                "time_of_day": [
                    "08:15",
                ],
                "mean_volume": [
                    100.0,
                ],
            }
        ),
        day_type_time_profile=pd.DataFrame(
            {
                "day_type": [
                    "workday",
                ],
                "time_of_day": [
                    "08:15",
                ],
                "day_type_mean_volume": [
                    100.0,
                ],
                "normalized_shape": [
                    1.0,
                ],
            }
        ),
        temporal_autocorrelation_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "adjusted_lag1_correlation": [
                    0.5
                    for _ in reference_ids
                ],
            }
        ),
    )
def make_generation_generator(
    seed: int = 42,
) -> SyntheticTrafficGenerator:
    """Create a generator using the observation-generation test profiles."""
    return SyntheticTrafficGenerator(
        profiles=make_generation_profiles(),
        config=SyntheticSourceConfig(
            seed=seed
        ),
    )
def test_generate_timestamp_returns_16_observations() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    assert len(observations) == 16
def test_generated_detector_ids_are_1_to_16() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    detector_ids = [
        observation.detector_id
        for observation in observations
    ]
    assert detector_ids == list(
        range(1, 17)
    )
def test_generated_site_id_is_target_site() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    assert all(
        observation.site_id
        == TARGET_SITE_ID
        for observation in observations
    )
    assert TARGET_SITE_ID == 9
def test_generated_descriptions_match_target_detectors() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    expected_descriptions = {
        detector.detector_id:
        detector.description
        for detector in TARGET_DETECTORS
    }
    for observation in observations:
        assert (
            observation.description
            == expected_descriptions[
                observation.detector_id
            ]
        )
def test_generated_timestamp_is_preserved() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    assert all(
        observation.timestamp
        == timestamp
        for observation in observations
    )
def test_generated_volumes_are_non_negative_integers() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp
    )
    assert all(
        isinstance(
            observation.volume,
            int,
        )
        for observation in observations
    )
    assert all(
        observation.volume >= 0
        for observation in observations
    )
def test_generate_timestamp_can_filter_detectors() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    observations = generator.generate_timestamp(
        timestamp,
        detector_ids=[
            2,
            5,
            9,
        ],
    )
    assert [
        observation.detector_id
        for observation in observations
    ] == [
        2,
        5,
        9,
    ]
def test_filtered_detector_values_match_full_request() -> None:
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    full_generator = (
        make_generation_generator(
            seed=42
        )
    )
    filtered_generator = (
        make_generation_generator(
            seed=42
        )
    )
    full_observations = (
        full_generator.generate_timestamp(
            timestamp
        )
    )
    filtered_observations = (
        filtered_generator.generate_timestamp(
            timestamp,
            detector_ids=[
                2,
                5,
                9,
            ],
        )
    )
    full_selected = [
        observation
        for observation
        in full_observations
        if observation.detector_id
        in {
            2,
            5,
            9,
        }
    ]
    assert (
        filtered_observations
        == full_selected
    )
def test_unknown_detector_is_rejected() -> None:
    generator = make_generation_generator()
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    with pytest.raises(
        ValueError,
        match="Unknown detector",
    ):
        generator.generate_timestamp(
            timestamp,
            detector_ids=[
                999,
            ],
        )
# ---------------------------------------------------------------------------
# Time and range semantics
# ---------------------------------------------------------------------------
def make_time_profiles() -> SyntheticTrafficProfiles:
    """
    Create in-memory profiles covering several consecutive
    15-minute timestamps for range testing.
    """
    reference_ids = list(
        range(1001, 1019)
    )
    times = [
        "08:15",
        "08:30",
        "08:45",
        "09:00",
    ]
    detector_time_rows = [
        {
            "detector_id": detector_id,
            "time_of_day": time_of_day,
            "mean_volume": 100.0,
            "std_volume": 10.0,
        }
        for detector_id in reference_ids
        for time_of_day in times
    ]
    return SyntheticTrafficProfiles(
        profile_summary={
            "overall_volume": {
                "mean_volume_per_detector_per_15_min_interval": 100.0,
            },
            "cross_detector_dependence": {
                "mean_residual_correlation_after_removing_time_of_day_and_day_level": 0.25,
            },
        },
        detector_volume_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "mean_volume": [
                    100.0
                    for _ in reference_ids
                ],
            }
        ),
        detector_time_of_day_profile=pd.DataFrame(
            detector_time_rows
        ),
        overall_time_of_day_profile=pd.DataFrame(
            {
                "time_of_day": times,
                "mean_volume": [
                    100.0
                    for _ in times
                ],
            }
        ),
        day_type_time_profile=pd.DataFrame(
            {
                "day_type": [
                    "workday"
                    for _ in times
                ],
                "time_of_day": times,
                "day_type_mean_volume": [
                    100.0
                    for _ in times
                ],
                "normalized_shape": [
                    1.0
                    for _ in times
                ],
            }
        ),
        temporal_autocorrelation_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "adjusted_lag1_correlation": [
                    0.5
                    for _ in reference_ids
                ],
            }
        ),
    )
def make_time_generator() -> SyntheticTrafficGenerator:
    """Create a generator for time and range tests."""
    return SyntheticTrafficGenerator(
        profiles=make_time_profiles(),
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
def make_time_lookup_profiles() -> SyntheticTrafficProfiles:
    """
    Create profiles with deliberately different values at 08:00
    and 08:15 so timestamp lookup behavior can be tested.
    """
    reference_ids = list(
        range(1001, 1019)
    )
    detector_time_rows = []
    for detector_id in reference_ids:
        detector_time_rows.extend(
            [
                {
                    "detector_id": detector_id,
                    "time_of_day": "08:00",
                    "mean_volume": 50.0,
                    "std_volume": 10.0,
                },
                {
                    "detector_id": detector_id,
                    "time_of_day": "08:15",
                    "mean_volume": 150.0,
                    "std_volume": 10.0,
                },
            ]
        )
    return SyntheticTrafficProfiles(
        profile_summary={
            "overall_volume": {
                "mean_volume_per_detector_per_15_min_interval": 100.0,
            },
            "cross_detector_dependence": {
                "mean_residual_correlation_after_removing_time_of_day_and_day_level": 0.25,
            },
        },
        detector_volume_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "mean_volume": [
                    100.0
                    for _ in reference_ids
                ],
            }
        ),
        detector_time_of_day_profile=pd.DataFrame(
            detector_time_rows
        ),
        overall_time_of_day_profile=pd.DataFrame(
            {
                "time_of_day": [
                    "08:00",
                    "08:15",
                ],
                "mean_volume": [
                    100.0,
                    100.0,
                ],
            }
        ),
        day_type_time_profile=pd.DataFrame(
            {
                "day_type": [
                    "workday",
                    "workday",
                ],
                "time_of_day": [
                    "08:00",
                    "08:15",
                ],
                "day_type_mean_volume": [
                    100.0,
                    100.0,
                ],
                "normalized_shape": [
                    1.0,
                    1.0,
                ],
            }
        ),
        temporal_autocorrelation_summary=pd.DataFrame(
            {
                "detector_id": reference_ids,
                "adjusted_lag1_correlation": [
                    0.5
                    for _ in reference_ids
                ],
            }
        ),
    )
def test_generate_range_uses_interval_end_timestamps() -> None:
    generator = make_time_generator()
    observations = generator.generate_range(
        start=datetime(
            2026,
            10,
            12,
            8,
            0,
        ),
        end=datetime(
            2026,
            10,
            12,
            8,
            30,
        ),
    )
    timestamps = sorted(
        {
            observation.timestamp
            for observation in observations
        }
    )
    assert timestamps == [
        datetime(
            2026,
            10,
            12,
            8,
            15,
        ),
        datetime(
            2026,
            10,
            12,
            8,
            30,
        ),
    ]
def test_one_hour_range_produces_four_intervals() -> None:
    generator = make_time_generator()
    observations = generator.generate_range(
        start=datetime(
            2026,
            10,
            12,
            8,
            0,
        ),
        end=datetime(
            2026,
            10,
            12,
            9,
            0,
        ),
    )
    timestamps = sorted(
        {
            observation.timestamp
            for observation in observations
        }
    )
    assert timestamps == [
        datetime(
            2026,
            10,
            12,
            8,
            15,
        ),
        datetime(
            2026,
            10,
            12,
            8,
            30,
        ),
        datetime(
            2026,
            10,
            12,
            8,
            45,
        ),
        datetime(
            2026,
            10,
            12,
            9,
            0,
        ),
    ]
    assert len(observations) == 64
def test_single_interval_range_produces_one_timestamp() -> None:
    generator = make_time_generator()
    observations = generator.generate_range(
        start=datetime(
            2026,
            10,
            12,
            8,
            0,
        ),
        end=datetime(
            2026,
            10,
            12,
            8,
            15,
        ),
    )
    assert len(observations) == 16
    assert {
        observation.timestamp
        for observation in observations
    } == {
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    }
def test_range_returns_16_observations_per_timestamp() -> None:
    generator = make_time_generator()
    observations = generator.generate_range(
        start=datetime(
            2026,
            10,
            12,
            8,
            0,
        ),
        end=datetime(
            2026,
            10,
            12,
            8,
            30,
        ),
    )
    timestamp_0815 = [
        observation
        for observation in observations
        if observation.timestamp
        == datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    ]
    timestamp_0830 = [
        observation
        for observation in observations
        if observation.timestamp
        == datetime(
            2026,
            10,
            12,
            8,
            30,
        )
    ]
    assert len(timestamp_0815) == 16
    assert len(timestamp_0830) == 16
def test_range_with_detector_filter_returns_only_requested_detectors() -> None:
    generator = make_time_generator()
    observations = generator.generate_range(
        start=datetime(
            2026,
            10,
            12,
            8,
            0,
        ),
        end=datetime(
            2026,
            10,
            12,
            8,
            30,
        ),
        detector_ids=[
            2,
            5,
            9,
        ],
    )
    assert len(observations) == 6
    assert {
        observation.detector_id
        for observation in observations
    } == {
        2,
        5,
        9,
    }
def test_range_rejects_unaligned_start_timestamp() -> None:
    generator = make_time_generator()
    with pytest.raises(
        ValueError,
        match="not aligned",
    ):
        generator.generate_range(
            start=datetime(
                2026,
                10,
                12,
                8,
                7,
            ),
            end=datetime(
                2026,
                10,
                12,
                8,
                30,
            ),
        )
def test_range_rejects_unaligned_end_timestamp() -> None:
    generator = make_time_generator()
    with pytest.raises(
        ValueError,
        match="not aligned",
    ):
        generator.generate_range(
            start=datetime(
                2026,
                10,
                12,
                8,
                0,
            ),
            end=datetime(
                2026,
                10,
                12,
                8,
                37,
            ),
        )
@pytest.mark.parametrize(
    "start,end",
    [
        (
            datetime(
                2026,
                10,
                12,
                8,
                0,
            ),
            datetime(
                2026,
                10,
                12,
                8,
                0,
            ),
        ),
        (
            datetime(
                2026,
                10,
                12,
                9,
                0,
            ),
            datetime(
                2026,
                10,
                12,
                8,
                0,
            ),
        ),
    ],
)
def test_range_requires_end_later_than_start(
    start: datetime,
    end: datetime,
) -> None:
    generator = make_time_generator()
    with pytest.raises(
        ValueError,
        match="end must be later than start",
    ):
        generator.generate_range(
            start=start,
            end=end,
        )
def test_record_timestamp_is_used_for_profile_lookup() -> None:
    generator = SyntheticTrafficGenerator(
        profiles=make_time_lookup_profiles(),
        config=SyntheticSourceConfig(
            seed=42,
            variation_scale=0.0,
        ),
    )
    observations = generator.generate_timestamp(
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    )
    assert all(
        observation.volume == 150
        for observation in observations
    )
@pytest.mark.parametrize(
    "timestamp,expected_day_type",
    [
        (
            datetime(
                2026,
                10,
                12,
                8,
                15,
            ),
            "workday",
        ),
        (
            datetime(
                2026,
                10,
                16,
                8,
                15,
            ),
            "friday",
        ),
        (
            datetime(
                2026,
                10,
                17,
                8,
                15,
            ),
            "saturday",
        ),
    ],
)
def test_day_type_uses_record_timestamp(
    timestamp: datetime,
    expected_day_type: str,
) -> None:
    assert (
        get_day_type(timestamp)
        == expected_day_type
    )
def test_midnight_record_uses_new_calendar_day() -> None:
    before_midnight = datetime(
        2026,
        10,
        15,
        23,
        45,
    )
    midnight = datetime(
        2026,
        10,
        16,
        0,
        0,
    )
    assert (
        get_day_type(before_midnight)
        == "workday"
    )
    assert (
        get_day_type(midnight)
        == "friday"
    )
# ---------------------------------------------------------------------------
# Randomness, reproducibility, and temporal persistence
# ---------------------------------------------------------------------------
def make_repro_generator(
    seed: int = 42,
    variation_scale: float = 1.0,
) -> SyntheticTrafficGenerator:
    """Create a generator for reproducibility and persistence tests."""
    return SyntheticTrafficGenerator(
        profiles=make_time_profiles(),
        config=SyntheticSourceConfig(
            seed=seed,
            variation_scale=variation_scale,
        ),
    )
def test_same_seed_and_same_call_sequence_produce_same_results() -> None:
    first_generator = make_repro_generator(
        seed=42
    )
    second_generator = make_repro_generator(
        seed=42
    )
    start = datetime(
        2026,
        10,
        12,
        8,
        0,
    )
    end = datetime(
        2026,
        10,
        12,
        9,
        0,
    )
    first_result = (
        first_generator.generate_range(
            start=start,
            end=end,
        )
    )
    second_result = (
        second_generator.generate_range(
            start=start,
            end=end,
        )
    )
    assert first_result == second_result
def test_reset_reproduces_same_sequence() -> None:
    generator = make_repro_generator(
        seed=42
    )
    start = datetime(
        2026,
        10,
        12,
        8,
        0,
    )
    end = datetime(
        2026,
        10,
        12,
        8,
        30,
    )
    first_result = generator.generate_range(
        start=start,
        end=end,
    )
    generator.reset()
    second_result = generator.generate_range(
        start=start,
        end=end,
    )
    assert first_result == second_result
def test_explicit_reset_seed_is_reproducible() -> None:
    first_generator = make_repro_generator(
        seed=42
    )
    second_generator = make_repro_generator(
        seed=42
    )
    first_generator.reset(
        seed=12345
    )
    second_generator.reset(
        seed=12345
    )
    start = datetime(
        2026,
        10,
        12,
        8,
        0,
    )
    end = datetime(
        2026,
        10,
        12,
        8,
        30,
    )
    first_result = (
        first_generator.generate_range(
            start=start,
            end=end,
        )
    )
    second_result = (
        second_generator.generate_range(
            start=start,
            end=end,
        )
    )
    assert first_result == second_result
def test_reset_seed_does_not_change_template_assignment() -> None:
    generator = make_repro_generator(
        seed=42
    )
    original_mapping = dict(
        generator.template_by_detector
    )
    generator.reset(
        seed=12345
    )
    assert (
        generator.template_by_detector
        == original_mapping
    )
def test_filtered_request_does_not_change_future_sequence() -> None:
    full_generator = make_repro_generator(
        seed=42
    )
    filtered_generator = make_repro_generator(
        seed=42
    )
    first_timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    second_timestamp = datetime(
        2026,
        10,
        12,
        8,
        30,
    )
    full_generator.generate_timestamp(
        first_timestamp
    )
    filtered_generator.generate_timestamp(
        first_timestamp,
        detector_ids=[
            2,
            5,
            9,
        ],
    )
    full_next = (
        full_generator.generate_timestamp(
            second_timestamp
        )
    )
    filtered_next = (
        filtered_generator.generate_timestamp(
            second_timestamp
        )
    )
    assert full_next == filtered_next
def test_temporal_state_is_stored_for_all_target_detectors() -> None:
    generator = make_repro_generator(
        seed=42
    )
    generator.generate_timestamp(
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    )
    assert set(
        generator.previous_deviation.keys()
    ) == set(
        range(1, 17)
    )
def test_reset_clears_temporal_state() -> None:
    generator = make_repro_generator(
        seed=42
    )
    generator.generate_timestamp(
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    )
    assert generator.previous_deviation
    generator.reset()
    assert (
        generator.previous_deviation
        == {}
    )
def test_reset_restores_configured_random_state() -> None:
    generator = make_repro_generator(
        seed=42
    )
    initial_random_state = (
        generator.random.getstate()
    )
    generator.generate_timestamp(
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    )
    changed_random_state = (
        generator.random.getstate()
    )
    assert (
        changed_random_state
        != initial_random_state
    )
    generator.reset()
    reset_random_state = (
        generator.random.getstate()
    )
    assert (
        reset_random_state
        == initial_random_state
    )
def test_zero_variation_scale_removes_random_variation() -> None:
    first_generator = make_repro_generator(
        seed=42,
        variation_scale=0.0,
    )
    second_generator = make_repro_generator(
        seed=42,
        variation_scale=0.0,
    )
    first_generator.reset(
        seed=111
    )
    second_generator.reset(
        seed=999
    )
    timestamp = datetime(
        2026,
        10,
        12,
        8,
        15,
    )
    first_result = (
        first_generator.generate_timestamp(
            timestamp
        )
    )
    second_result = (
        second_generator.generate_timestamp(
            timestamp
        )
    )
    assert first_result == second_result
    assert all(
        observation.volume == 100
        for observation in first_result
    )
def test_temporal_persistence_uses_previous_deviation(
    monkeypatch,
) -> None:
    generator = make_repro_generator(
        seed=42
    )
    generator.previous_deviation[1] = 2.0
    monkeypatch.setattr(
        generator.random,
        "gauss",
        lambda mean, standard_deviation: 0.0,
    )
    volume = generator.generate_volume(
        target_detector_id=1,
        timestamp=datetime(
            2026,
            10,
            12,
            8,
            15,
        ),
        shared_noise=0.0,
    )
    assert (
        generator.previous_deviation[1]
        == pytest.approx(1.0)
    )
    assert volume == 110
# ---------------------------------------------------------------------------
# Scenarios and validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "scenario,expected_volume",
    [
        ("low", 80),
        ("normal", 100),
        ("high", 120),
    ],
)
def test_scenario_scales_expected_traffic_level(
    scenario: str,
    expected_volume: int,
) -> None:
    profiles = make_time_profiles()
    generator = SyntheticTrafficGenerator(
        profiles=profiles,
        config=SyntheticSourceConfig(
            seed=42,
            scenario=scenario,
            variation_scale=0.0,
        ),
    )
    observations = generator.generate_timestamp(
        datetime(
            2026,
            10,
            12,
            8,
            15,
        )
    )
    assert all(
        observation.volume == expected_volume
        for observation in observations
    )
@pytest.mark.parametrize(
    "correlation",
    [
        -0.01,
        1.01,
    ],
)
def test_invalid_shared_correlation_is_rejected(
    correlation: float,
) -> None:
    profiles = make_time_profiles()
    profiles.profile_summary[
        "cross_detector_dependence"
    ][
        "mean_residual_correlation_after_removing_time_of_day_and_day_level"
    ] = correlation
    with pytest.raises(
        ValueError,
        match="Shared detector correlation must be between 0 and 1",
    ):
        SyntheticTrafficGenerator(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
@pytest.mark.parametrize(
    "persistence",
    [
        -0.1,
        1.0,
        1.1,
    ],
)
def test_invalid_temporal_persistence_is_rejected(
    persistence: float,
) -> None:
    profiles = make_time_profiles()
    profiles.temporal_autocorrelation_summary[
        "adjusted_lag1_correlation"
    ] = persistence
    generator = SyntheticTrafficGenerator(
        profiles=profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    with pytest.raises(
        ValueError,
        match="must be between 0 and 1",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
def test_missing_detector_time_profile_is_rejected() -> None:
    profiles = make_time_profiles()
    modified_profiles = replace(
        profiles,
        detector_time_of_day_profile=(
            profiles.detector_time_of_day_profile[
                profiles.detector_time_of_day_profile[
                    "time_of_day"
                ]
                != "08:15"
            ].copy()
        ),
    )
    generator = SyntheticTrafficGenerator(
        profiles=modified_profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    with pytest.raises(
        ValueError,
        match="No detector profile found",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
def test_missing_overall_time_profile_is_rejected() -> None:
    profiles = make_time_profiles()
    modified_profiles = replace(
        profiles,
        overall_time_of_day_profile=(
            profiles.overall_time_of_day_profile[
                profiles.overall_time_of_day_profile[
                    "time_of_day"
                ]
                != "08:15"
            ].copy()
        ),
    )
    generator = SyntheticTrafficGenerator(
        profiles=modified_profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    with pytest.raises(
        ValueError,
        match="No overall time-of-day profile found",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
def test_missing_day_type_profile_is_rejected() -> None:
    profiles = make_time_profiles()
    modified_profiles = replace(
        profiles,
        day_type_time_profile=(
            profiles.day_type_time_profile.iloc[
                0:0
            ].copy()
        ),
    )
    generator = SyntheticTrafficGenerator(
        profiles=modified_profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    with pytest.raises(
        ValueError,
        match="No workday profile found",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
def test_missing_temporal_persistence_profile_is_rejected() -> None:
    profiles = make_time_profiles()
    modified_profiles = replace(
        profiles,
        temporal_autocorrelation_summary=(
            profiles.temporal_autocorrelation_summary.iloc[
                0:0
            ].copy()
        ),
    )
    generator = SyntheticTrafficGenerator(
        profiles=modified_profiles,
        config=SyntheticSourceConfig(
            seed=42
        ),
    )
    with pytest.raises(
        ValueError,
        match="No temporal persistence profile found",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
def test_zero_reference_mean_is_rejected() -> None:
    profiles = make_time_profiles()
    profiles.detector_volume_summary[
        "mean_volume"
    ] = 0.0
    with pytest.raises(
        ValueError,
        match="invalid average traffic volume",
    ):
        assign_reference_templates(
            profiles=profiles,
            config=SyntheticSourceConfig(
                seed=42
            ),
        )
def test_empty_detector_filter_is_rejected() -> None:
    generator = make_time_generator()
    with pytest.raises(
        ValueError,
        match="At least one detector ID is required",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            ),
            detector_ids=[],
        )
@pytest.mark.parametrize(
    "interval_minutes",
    [
        0,
        -15,
    ],
)
def test_non_positive_interval_is_rejected(
    interval_minutes: int,
) -> None:
    generator = SyntheticTrafficGenerator(
        profiles=make_time_profiles(),
        config=SyntheticSourceConfig(
            seed=42,
            interval_minutes=interval_minutes,
        ),
    )
    with pytest.raises(
        ValueError,
        match="interval_minutes must be greater than zero",
    ):
        generator.generate_timestamp(
            datetime(
                2026,
                10,
                12,
                8,
                15,
            )
        )
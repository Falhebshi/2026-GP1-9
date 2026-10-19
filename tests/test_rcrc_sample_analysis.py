from datetime import date
import json
from math import sqrt

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from analysis.rcrc_sample import rcrc_sample_analysis as analysis
from analysis.rcrc_sample.rcrc_sample_analysis import (
    build_daily_volume_summary,
    build_day_adjusted_residual_correlation_matrix,
    build_day_type_time_profile,
    build_detector_time_of_day_profile,
    build_temporal_autocorrelation_summary,
    build_time_of_day_profile,
    build_turning_summary,
    validate_rcrc_sample,
    validate_time_coverage,
)


def observations(timestamps, volumes, detector_id=1):
    """Artificial observations; no private RCRC data is used."""
    return pd.DataFrame(
        {
            "Site ID": 1,
            "detector_id": detector_id,
            "Date  & Time": pd.to_datetime(timestamps),
            "volume": volumes,
            "description": f"TEST-EB-L{detector_id}-T",
        }
    )


@pytest.mark.parametrize(
    "day,day_name,next_day_name,day_type,next_day_type",
    [
        ("2026-10-08", "Thursday", "Friday", "workday", "friday"),
        ("2026-10-09", "Friday", "Saturday", "friday", "saturday"),
        ("2026-10-10", "Saturday", "Sunday", "saturday", "workday"),
    ],
)
def test_midnight_counts_belong_to_the_day_the_interval_started(
    day, day_name, next_day_name, day_type, next_day_type
):
    start = pd.Timestamp(day)
    next_day = start + pd.Timedelta(days=1)
    df = observations(
        [
            start + pd.Timedelta(hours=23, minutes=45),
            next_day,
            next_day + pd.Timedelta(minutes=15),
        ],
        [10, 20, 30],
    )

    daily = build_daily_volume_summary(df)
    assert daily["date"].tolist() == [start.date(), next_day.date()]
    assert daily["day_name"].tolist() == [day_name, next_day_name]
    assert daily["total_volume"].tolist() == [30, 30]

    profile = analysis.add_interval_fields(df)
    midnight = profile.loc[profile["time_of_day"] == "00:00"].iloc[0]
    assert midnight["day_type"] == day_type
    assert midnight["slot_index"] == 95
    assert midnight["volume"] == 20
    first = profile.loc[profile["time_of_day"] == "00:15"].iloc[0]
    assert first["day_type"] == next_day_type
    assert first["slot_index"] == 0
    assert first["volume"] == 30


@pytest.mark.parametrize(
    "builder,group_columns",
    [
        (build_time_of_day_profile, []),
        (build_detector_time_of_day_profile, ["detector_id"]),
        (build_day_type_time_profile, ["day_type"]),
    ],
)
def test_profiles_follow_all_96_intervals_with_midnight_last(builder, group_columns):
    # Two complete traffic days: Thursday and Friday, each ending at midnight.
    timestamps = pd.date_range("2026-10-08 00:15", periods=192, freq="15min")
    df = pd.concat(
        [observations(timestamps, list(range(1, 193)), detector_id=i) for i in (1, 2)],
        ignore_index=True,
    ).iloc[::-1]
    profile = builder(df)

    expected_labels = pd.date_range(
        "2026-10-08 00:15", periods=96, freq="15min"
    ).strftime("%H:%M").tolist()
    groups = (
        [group for _, group in profile.groupby(group_columns)]
        if group_columns
        else [profile]
    )
    if builder is build_day_type_time_profile:
        assert set(profile["day_type"]) == {"workday", "friday"}
    for group in groups:
        assert group["slot_index"].tolist() == list(range(96))
        assert group["time_of_day"].tolist() == expected_labels


def test_a_complete_traffic_day_does_not_create_a_partial_following_day():
    timestamps = pd.date_range("2026-10-08 00:15", periods=96, freq="15min")
    daily = build_daily_volume_summary(observations(timestamps, [1] * 96))

    assert daily["date"].tolist() == [date(2026, 10, 8)]
    assert daily["total_volume"].tolist() == [96]


@pytest.mark.parametrize("weeks", [1, 2])
def test_day_type_counts_are_distinct_dates_and_are_saved_and_printed(
    weeks, monkeypatch, tmp_path, capsys
):
    timestamps = pd.date_range(
        "2026-10-05 00:15", periods=weeks * 7 * 96, freq="15min"
    )
    df = pd.concat(
        [observations(timestamps, [volume] * len(timestamps), detector)
         for detector, volume in [(1, 8), (2, 16)]],
        ignore_index=True,
    )
    before = df.copy(deep=True)

    profile = build_day_type_time_profile(df)

    expected_counts = {"workday": 5 * weeks, "friday": weeks, "saturday": weeks}
    assert len(profile) == 3 * 96
    assert profile["day_count"].tolist() == profile["day_type"].map(expected_counts).tolist()
    assert (profile["mean_volume"] == 12).all()
    assert (profile["normalized_shape"] == 1).all()
    assert_frame_equal(df, before)

    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis.save_day_type_time_profile(profile)

    saved = pd.read_csv(tmp_path / "day_type_time_profile.csv")
    # CSV preserves values, but does not encode pandas integer widths.
    assert_frame_equal(saved, profile, check_dtype=False)
    output = capsys.readouterr().out
    for day_type, count in expected_counts.items():
        line = next(line for line in output.splitlines() if line.startswith(day_type))
        assert f"days={count} " in line
    assert "only one day" not in output


def test_day_type_count_assigns_final_midnight_to_the_previous_day():
    timestamps = pd.date_range("2026-10-08 00:15", periods=96, freq="15min")
    profile = build_day_type_time_profile(observations(timestamps, [1] * 96))

    assert set(profile["day_type"]) == {"workday"}
    assert profile["day_count"].tolist() == [1] * 96
    assert profile.iloc[-1]["time_of_day"] == "00:00"


@pytest.fixture
def residual_observations():
    timestamps = [
        "2026-10-08 23:45", "2026-10-09 00:00", "2026-10-09 00:15",
        "2026-10-09 23:45", "2026-10-10 00:00", "2026-10-10 00:15",
        "2026-10-10 23:45", "2026-10-11 00:00", "2026-10-11 00:15",
    ]
    return pd.concat(
        [
            observations(pd.to_datetime(timestamps) - pd.Timedelta(days=4), [8, 12, 21, 15, 35, 18, 22, 43, 31]),
            observations(pd.to_datetime(timestamps) - pd.Timedelta(days=4), [12, 17, 8, 31, 21, 18, 27, 37, 12], 2),
        ],
        ignore_index=True,
    )


def test_day_adjusted_correlations_use_the_previous_day_for_midnight(
    residual_observations,
):
    result = build_day_adjusted_residual_correlation_matrix(residual_observations)

    # Independently calculated with per-detector observation indexes grouped
    # into traffic days [0,1], [2,3,4], [5,6,7], [8], rather than timestamp days.
    assert result.loc[1, 2] == pytest.approx(-0.2015691112842361)


def test_adjusted_persistence_uses_the_previous_day_for_midnight(
    residual_observations,
):
    result = build_temporal_autocorrelation_summary(residual_observations)

    assert result["adjusted_lag1_correlation"].tolist() == pytest.approx(
        [-0.24797343611105155, -0.8822989405080134]
    )
    # Chronological raw observations still produce the same raw correlations.
    assert result["raw_lag1_correlation"].tolist() == pytest.approx(
        [0.23594472416106338, -0.1638821100056317]
    )


@pytest.fixture
def zero_slot_observations(residual_observations):
    df = residual_observations.copy(deep=True)
    midnight = df["Date  & Time"].dt.strftime("%H:%M") == "00:00"
    df.loc[midnight, "volume"] = 0
    return df


def test_zero_slot_means_keep_correlation_input_numeric(
    monkeypatch, zero_slot_observations
):
    original_corr = pd.DataFrame.corr
    checked_inputs = []

    def numeric_corr(frame, *args, **kwargs):
        assert all(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes)
        # An all-zero slot still has a real zero residual, rather than a
        # missing value, when other slots supply the day's factor.
        midnight = frame.index.strftime("%H:%M") == "00:00"
        assert (frame.loc[midnight] == 0).all().all()
        checked_inputs.append(True)
        return original_corr(frame, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "corr", numeric_corr)
    result = build_day_adjusted_residual_correlation_matrix(zero_slot_observations)

    assert checked_inputs
    assert result.loc[1, 2] == pytest.approx(-0.24873280334094502)


def test_zero_slot_means_keep_autocorrelation_input_numeric(
    monkeypatch, zero_slot_observations
):
    original_autocorr = pd.Series.autocorr
    checked_inputs = []

    def numeric_autocorr(series, *args, **kwargs):
        assert pd.api.types.is_numeric_dtype(series.dtype)
        if series.name == "adjusted_residual":
            assert series.notna().all()
        checked_inputs.append(True)
        return original_autocorr(series, *args, **kwargs)

    monkeypatch.setattr(pd.Series, "autocorr", numeric_autocorr)
    result = build_temporal_autocorrelation_summary(zero_slot_observations)

    assert checked_inputs
    assert result["adjusted_lag1_correlation"].tolist() == pytest.approx(
        [-0.4158071479949647, -0.40280442427067187]
    )


@pytest.mark.parametrize(
    "builder",
    [
        build_daily_volume_summary,
        build_time_of_day_profile,
        build_detector_time_of_day_profile,
        build_day_type_time_profile,
        build_day_adjusted_residual_correlation_matrix,
        build_temporal_autocorrelation_summary,
    ],
)
def test_analysis_preserves_source_timestamps_and_input_fields(
    builder, residual_observations
):
    before = residual_observations.copy(deep=True)
    builder(residual_observations)
    assert_frame_equal(residual_observations, before)


@pytest.mark.parametrize(
    "description",
    [
        "P1", "P1-EB", "P1-EB-L2", "P1-EB-L2-", "P1-EB-L2- -STB",
        "-EB-L2-T", "P1- -L2-T", "P1-EB- -T", "", None, pd.NA,
    ],
)
def test_turning_summary_rejects_incomplete_rows_among_valid_descriptions(description):
    df = pd.DataFrame(
        {"description": ["P1-EB-L1-T-STB", description], "volume": [100, 50]}
    )

    message = (
        "description must contain string values"
        if description is None or description is pd.NA
        else "non-empty.*codes"
    )
    with pytest.raises(ValueError, match=message):
        build_turning_summary(df)


@pytest.mark.parametrize("turn_code", ["U", "through", "t"])
def test_turning_summary_still_rejects_unsupported_turn_codes(turn_code):
    df = pd.DataFrame(
        {"description": [f"P1-EB-L1-{turn_code}-STB"], "volume": [100]}
    )

    with pytest.raises(ValueError, match="Unexpected turn codes"):
        build_turning_summary(df)


def test_turning_summary_strips_parts_and_preserves_volume_and_source_descriptions():
    df = pd.DataFrame(
        {
            "description": [
                " P1 - EB - L1 - T - STB ", "P1-EB-L2-L-STB",
                " P1 - EB - L3 - R ", "P2-WB-L1-T-STB",
            ],
            "volume": [100, 50, 25, 75],
        }
    )
    before = df.copy(deep=True)

    summary = build_turning_summary(df)

    assert_frame_equal(df, before)
    assert summary["approach_code"].tolist() == ["P1-EB"] * 3 + ["P2-WB"]
    assert summary["turn"].tolist() == ["left", "through", "right", "through"]
    assert summary["total_volume"].tolist() == [50, 100, 25, 75]
    assert summary["total_volume"].sum() == df["volume"].sum()
    assert summary["share_of_site_volume_pct"].sum() == pytest.approx(100)
    assert summary.groupby("approach_code")["share_within_approach_pct"].sum().tolist() == (
        pytest.approx([100, 100])
    )


def test_turning_summary_retains_a_valid_zero_count():
    df = pd.DataFrame(
        {"description": ["P1-EB-L1-L-STB", "P1-EB-L2-T-STB"], "volume": [0, 100]}
    )

    summary = build_turning_summary(df)

    assert summary["turn"].tolist() == ["left", "through"]
    assert summary["total_volume"].tolist() == [0, 100]
    assert summary["share_of_site_volume_pct"].tolist() == [0, 100]


def test_source_validation_rejects_a_missing_turn_code_before_profiling():
    df = observations(["2026-10-08 08:15", "2026-10-08 08:30"], [100, 50])
    df.loc[1, "description"] = "P1-EB-L2"

    with pytest.raises(ValueError, match="non-empty.*codes"):
        validate_rcrc_sample(df)


@pytest.mark.parametrize("existing_outputs", [False, True])
def test_main_rejects_bad_descriptions_before_creating_or_overwriting_outputs(
    monkeypatch, tmp_path, existing_outputs
):
    df = observations(["2026-10-08 08:15", "2026-10-08 08:30"], [100, 50])
    df.loc[1, "description"] = "P1-EB-L2"
    output_dir = tmp_path / "profiles"
    if existing_outputs:
        output_dir.mkdir()
        (output_dir / "detector_volume_summary.csv").write_text("previous valid result\n")
    before = {p.name: p.read_bytes() for p in output_dir.glob("*")}
    monkeypatch.setattr(analysis, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(analysis, "load_rcrc_sample", lambda: df)

    with pytest.raises(ValueError, match="non-empty.*codes"):
        analysis.main()

    assert output_dir.exists() is existing_outputs
    assert {p.name: p.read_bytes() for p in output_dir.glob("*")} == before


@pytest.fixture
def complete_week():
    timestamps = pd.date_range("2026-10-05 00:15", periods=7 * 96, freq="15min")
    return pd.concat(
        [observations(timestamps, [12] * len(timestamps), i) for i in (1, 2)],
        ignore_index=True,
    )


def test_validation_accepts_a_complete_unsorted_week_without_changing_it(complete_week):
    df = complete_week.iloc[::-1].copy()
    df["volume"] = df["volume"].astype(float)
    df.loc[df.index[0], "volume"] = 0.0
    before = df.copy(deep=True)

    validate_rcrc_sample(df)
    validate_time_coverage(df)

    assert_frame_equal(df, before)


def test_validation_rejects_multiple_sites(complete_week):
    complete_week.loc[complete_week["detector_id"] == 2, "Site ID"] = 2

    with pytest.raises(ValueError, match="exactly one site"):
        validate_rcrc_sample(complete_week)


def test_validation_rejects_multiple_descriptions_for_one_detector(complete_week):
    complete_week.loc[0, "description"] = "TEST-EB-L1-L"

    with pytest.raises(ValueError, match="exactly one description"):
        validate_rcrc_sample(complete_week)


@pytest.mark.parametrize("volume", [12.5, float("inf"), float("-inf"), True, 12 + 1j])
def test_validation_rejects_non_count_volumes(complete_week, volume):
    complete_week["volume"] = volume

    with pytest.raises(ValueError, match="volume|Volume"):
        validate_rcrc_sample(complete_week)


@pytest.mark.parametrize("description", [123, 12.5, b"TEST-EB-L1-T", True, [], {}])
def test_validation_rejects_non_string_descriptions(complete_week, description):
    complete_week["description"] = complete_week["description"].astype(object)
    complete_week.at[0, "description"] = description

    with pytest.raises(ValueError, match="description must contain string values"):
        validate_rcrc_sample(complete_week)


@pytest.mark.parametrize("dtype", [object, "str", "string"])
def test_validation_accepts_descriptions_with_different_string_dtypes(complete_week, dtype):
    complete_week["description"] = complete_week["description"].astype(dtype)

    validate_rcrc_sample(complete_week)


@pytest.mark.parametrize("edge", ["start", "end"])
def test_coverage_rejects_different_detector_ranges(complete_week, edge):
    detector = complete_week[complete_week["detector_id"] == 2]
    # Removing a whole day leaves each detector individually complete.
    removed = detector.index[:96] if edge == "start" else detector.index[-96:]
    df = complete_week.drop(removed)
    validate_rcrc_sample(df)

    with pytest.raises(ValueError, match="same start and end"):
        validate_time_coverage(df)


@pytest.mark.parametrize("offset", ["7min", "1s", "1ms", "1us", "1ns"])
def test_coverage_rejects_unaligned_timestamps_even_with_regular_gaps(complete_week, offset):
    complete_week["Date  & Time"] += pd.Timedelta(offset)

    with pytest.raises(ValueError, match="quarter-hour"):
        validate_time_coverage(complete_week)


@pytest.mark.parametrize("edge", ["start", "end"])
def test_coverage_accepts_a_shared_partial_boundary_day(complete_week, edge):
    timestamps = complete_week["Date  & Time"]
    boundary = timestamps.min() if edge == "start" else timestamps.max()
    df = complete_week.loc[timestamps != boundary]

    validate_rcrc_sample(df)
    validate_time_coverage(df)


def test_midnight_to_2345_retains_both_partial_days_and_all_volume():
    timestamps = pd.date_range("2026-10-05 00:00", periods=96, freq="15min")
    df = observations(timestamps, [1] * 96)

    validate_rcrc_sample(df)
    validate_time_coverage(df)
    before = df.copy(deep=True)
    daily = build_daily_volume_summary(df)

    assert daily["date"].tolist() == [date(2026, 10, 4), date(2026, 10, 5)]
    assert daily["observed_intervals"].tolist() == [1, 95]
    assert daily["total_volume"].tolist() == [1, 95]
    assert daily["total_volume"].sum() == df["volume"].sum()
    assert_frame_equal(df, before)


def test_coverage_accepts_one_complete_interval_end_day():
    timestamps = pd.date_range("2026-10-05 00:15", periods=96, freq="15min")
    df = observations(timestamps, [1] * 96)

    validate_rcrc_sample(df)
    validate_time_coverage(df)


def test_coverage_rejects_a_missing_interior_interval(complete_week):
    df = complete_week.drop(index=48)

    with pytest.raises(ValueError, match="invalid time gaps"):
        validate_time_coverage(df)


@pytest.mark.parametrize("existing_outputs", [False, True])
def test_main_rejects_interior_gaps_before_writing_outputs(
    monkeypatch, tmp_path, complete_week, existing_outputs
):
    df = complete_week.drop(index=48)
    output_dir = tmp_path / "profiles"
    if existing_outputs:
        output_dir.mkdir()
        (output_dir / "detector_volume_summary.csv").write_text("previous valid result\n")
    before = {p.name: p.read_bytes() for p in output_dir.glob("*")}
    monkeypatch.setattr(analysis, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(analysis, "load_rcrc_sample", lambda: df)

    with pytest.raises(ValueError, match="invalid time gaps"):
        analysis.main()

    assert output_dir.exists() is existing_outputs
    assert {p.name: p.read_bytes() for p in output_dir.glob("*")} == before


def test_residual_variability_uses_the_same_adjustments_as_the_matrices():
    timestamps = [
        "2026-10-05 23:45", "2026-10-06 00:00",
        "2026-10-06 23:45", "2026-10-07 00:00",
    ]
    df = pd.concat(
        [observations(timestamps, [10, 30, 30, 50]),
         observations(timestamps, [20, 40, 20, 80], 2)],
        ignore_index=True,
    )
    before = df.copy(deep=True)

    summary = analysis.build_residual_variability_summary(df)

    assert summary["detector_id"].tolist() == [1, 2]
    assert summary["description"].tolist() == ["TEST-EB-L1-T", "TEST-EB-L2-T"]
    assert summary["residual_count"].tolist() == [4, 4]
    assert summary["fitted_slot_count"].tolist() == [2, 2]
    assert summary["residual_degrees_of_freedom"].tolist() == [2, 2]
    # Slot-only residuals: A=[-10,-10,10,10], B=[0,-20,0,20].
    assert summary["residual_std"].tolist() == pytest.approx(
        [sqrt(200), 20]
    )
    # Ratio-of-sums daily factors are 5/7 and 9/7. Adjusted residuals:
    # A=[-30/7,10/7,30/7,-10/7], B=[40/7,-20/7,-40/7,20/7].
    raw_residual_corr = analysis.build_residual_correlation_matrix(df)
    adjusted_corr = build_day_adjusted_residual_correlation_matrix(df)
    assert raw_residual_corr.loc[1, 2] == pytest.approx(1 / sqrt(2))
    assert adjusted_corr.loc[1, 2] == pytest.approx(-7 / (5 * sqrt(2)))
    assert_frame_equal(df, before)


def test_residual_exports_preserve_undefined_statistics(monkeypatch, tmp_path):
    timestamps = ["2026-10-05 00:15", "2026-10-06 00:15"]
    df = pd.concat(
        [observations(timestamps, [0, 0], i) for i in (1, 2)],
        ignore_index=True,
    )
    summary = analysis.build_residual_variability_summary(df)
    assert summary["residual_count"].tolist() == [2, 2]
    assert summary["residual_std"].tolist() == [0, 0]
    assert summary["residual_degrees_of_freedom"].tolist() == [1, 1]

    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis.save_residual_correlation_matrices(
        analysis.build_residual_correlation_matrix(df),
        build_day_adjusted_residual_correlation_matrix(df),
    )
    analysis.save_residual_variability_summary(summary)

    for filename in [
        "residual_correlation_matrix.csv", "day_adjusted_residual_correlation_matrix.csv",
    ]:
        matrix = pd.read_csv(tmp_path / filename, index_col=0)
        assert matrix.index.tolist() == [1, 2]
        assert matrix.columns.tolist() == ["1", "2"]
        assert matrix.isna().all().all()
    saved = pd.read_csv(tmp_path / "detector_residual_variability_summary.csv")
    assert_frame_equal(saved, summary)


def test_residual_standard_deviation_is_undefined_with_only_one_observation():
    df = observations(["2026-10-08 00:15"], [12])
    summary = analysis.build_residual_variability_summary(df)

    assert summary["residual_count"].tolist() == [1]
    assert summary["residual_degrees_of_freedom"].tolist() == [0]
    assert summary["residual_std"].isna().all()


def test_main_saves_all_outputs_for_partial_boundary_days_without_changing_compact_json(
    monkeypatch, tmp_path, complete_week
):
    df = complete_week.copy()
    df["Date  & Time"] -= pd.Timedelta(minutes=15)
    for detector_id, base, period in [(1, 20, 3), (2, 40, 4)]:
        rows = df["detector_id"] == detector_id
        df.loc[rows, "volume"] = [
            base + i % 7 + (i // 96 % period) * (1 + i % period)
            for i in range(int(rows.sum()))
        ]
    before = df.copy(deep=True)
    monkeypatch.setattr(analysis, "load_rcrc_sample", lambda: df)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)

    analysis.main()

    assert len(list(tmp_path.iterdir())) == 14
    daily = pd.read_csv(tmp_path / "daily_volume_summary.csv")
    assert daily["observed_intervals"].tolist() == [1] + [96] * 6 + [95]
    assert daily["total_volume"].sum() == df["volume"].sum()
    for filename, expected in [
        ("residual_correlation_matrix.csv", analysis.build_residual_correlation_matrix(df)),
        ("day_adjusted_residual_correlation_matrix.csv",
         build_day_adjusted_residual_correlation_matrix(df)),
    ]:
        saved = pd.read_csv(tmp_path / filename, index_col=0)
        saved.columns = saved.columns.astype(int)
        saved.columns.name = "detector_id"
        assert_frame_equal(saved, expected)
    saved_std = pd.read_csv(tmp_path / "detector_residual_variability_summary.csv")
    assert_frame_equal(saved_std, analysis.build_residual_variability_summary(df))
    summary = json.loads((tmp_path / "rcrc_profile_summary.json").read_text())
    assert set(summary) == {
        "methodology", "source", "overall_volume", "cross_detector_dependence", "temporal_persistence",
    }
    assert summary["cross_detector_dependence"][
        "mean_residual_correlation_after_removing_time_of_day_and_day_level"
    ] == pytest.approx(analysis.calculate_mean_pairwise_correlation(
        build_day_adjusted_residual_correlation_matrix(df)
    ))
    assert_frame_equal(df, before)

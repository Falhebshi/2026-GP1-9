from math import sqrt
import importlib
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from analysis.rcrc_sample import rcrc_sample_analysis as analysis


def reference_week(detector_count=1):
    """Five complete workdays followed by Friday/Saturday; artificial data only."""
    timestamps = pd.date_range("2026-10-04 00:15", periods=7 * 96, freq="15min")
    rows = []
    for detector in range(1, detector_count + 1):
        for i, timestamp in enumerate(timestamps):
            day, slot = divmod(i, 96)
            base = 100 + detector * 3 + slot % 4 * 10
            if day < 5:
                volume = base + [-2, -1, 0, 1, 2][day]
            elif day == 5:
                volume = 2 * base + (500 if slot == 0 else 0)
            else:
                volume = int(0.7 * base) + (300 if slot == 48 else 0)
            rows.append([1, detector, timestamp, volume, f"TEST-EB-L{detector}-T"])
    return pd.DataFrame(rows, columns=analysis.EXPECTED_COLUMNS)


def test_day_factor_is_ratio_of_sums_over_matching_observed_intervals():
    # Workday slot means are 1 and 100. First day's ratios are 2 and 1.
    df = pd.DataFrame({
        "Site ID": 1, "detector_id": 1,
        "Date  & Time": pd.to_datetime([
            "2026-10-05 00:15", "2026-10-05 00:30",
            "2026-10-06 00:15", "2026-10-06 00:30",
        ]),
        "volume": [2, 100, 0, 100], "description": "TEST-EB-L1-T",
    })
    before = df.copy(deep=True)
    result = analysis.build_residual_observations(df)
    assert result["day_factor"].tolist() == pytest.approx([102 / 101] * 2 + [100 / 101] * 2)
    assert result["day_factor"].iloc[0] != pytest.approx(1.5)
    assert result["adjusted_residual"].iloc[0] == pytest.approx(2 - 102 / 101)
    assert_frame_equal(df, before)


def test_zero_expected_daily_total_is_explicitly_undefined():
    df = reference_week()
    df["volume"] = 0
    result = analysis.build_residual_observations(df)
    assert result["day_factor"].isna().all()
    assert result["adjusted_residual"].isna().all()
    assert result["residual"].eq(0).all()


def test_workday_slot_sample_sd_excludes_weekends_without_double_correction():
    df = reference_week()
    before = df.copy(deep=True)
    profile = analysis.build_detector_time_of_day_profile(df)
    assert profile["workday_observation_count"].tolist() == [5] * 96
    assert profile["std_volume"].tolist() == pytest.approx([sqrt(2.5)] * 96)
    assert profile.iloc[0]["mean_volume"] == 103
    weekend = analysis.add_interval_fields(df)["day_type"] != "workday"
    df.loc[weekend, "volume"] *= 100
    assert_frame_equal(profile, analysis.build_detector_time_of_day_profile(df))
    assert_frame_equal(
        analysis.build_time_of_day_profile(before), analysis.build_time_of_day_profile(df)
    )


def test_pooled_workday_noise_accounts_for_96_fitted_means():
    summary = analysis.build_residual_variability_summary(reference_week())
    row = summary.iloc[0]
    assert row["residual_count"] == 480
    assert row["fitted_slot_count"] == 96
    assert row["residual_degrees_of_freedom"] == 384
    assert row["residual_sum_squares"] == 960
    assert row["residual_std"] == pytest.approx(sqrt(960 / 384))


def test_weekend_ratios_are_smoothed_deterministically_and_preserve_broad_levels():
    df = reference_week()
    before = df.copy(deep=True)
    profile = analysis.build_day_type_time_profile(df)
    assert_frame_equal(profile, analysis.build_day_type_time_profile(df.iloc[::-1]))
    workday = profile[profile["day_type"] == "workday"]
    assert workday["mean_volume"].tolist() == workday["observed_mean_volume"].tolist()
    for day_type in ["friday", "saturday"]:
        group = profile[profile["day_type"] == day_type]
        assert group["smoothing_window_slots"].eq(5).all()
        assert not np.allclose(group["mean_volume"], group["observed_mean_volume"])
        assert group["mean_volume"].mean() == pytest.approx(group["observed_mean_volume"].mean())
    friday = profile[profile["day_type"] == "friday"]
    # Slot 0's spike affects slot 95 through circular smoothing.
    assert friday.iloc[-1]["mean_volume"] > friday.iloc[-1]["observed_mean_volume"]
    assert friday["mean_volume"].mean() > workday["mean_volume"].mean()
    saturday = profile[profile["day_type"] == "saturday"]
    assert saturday["mean_volume"].mean() < workday["mean_volume"].mean()
    assert_frame_equal(df, before)


def test_circular_mean_has_exact_five_slot_window():
    ratios = pd.Series([6.0] + [1.0] * 95, index=range(96))
    result = analysis.smooth_circular_slot_ratios(ratios)
    expected = pd.Series([2.0 if i in {94, 95, 0, 1, 2} else 1.0 for i in range(96)])
    pd.testing.assert_series_equal(result, expected)


def test_missing_workday_reference_is_reported():
    df = reference_week()
    weekend = analysis.add_interval_fields(df)["day_type"] != "workday"
    with pytest.raises(ValueError, match="workday reference"):
        analysis.build_day_type_time_profile(df.loc[weekend])


def test_positive_weekend_with_zero_workday_reference_is_not_guessed():
    df = reference_week()
    p = analysis.add_interval_fields(df)
    df.loc[(p["day_type"] == "workday") & p["slot_index"].eq(0), "volume"] = 0
    with pytest.raises(ValueError, match="zero workday reference"):
        analysis.build_day_type_time_profile(df)


def test_extreme_review_uses_expected_slot_scale_and_pooled_detector_iqr(tmp_path, monkeypatch):
    df = reference_week(2)
    p = analysis.add_interval_fields(df)
    df = df.loc[p["day_type"] == "workday"].copy()
    # A repeatable slot profile with one unusual observed count in detector 1.
    p = analysis.add_interval_fields(df)
    df["volume"] = (100 + p["slot_index"] % 10 * 10).astype("int64")
    spike = df.index[(df["detector_id"] == 1) & p["slot_index"].eq(40)][-1]
    df.loc[spike, "volume"] += 800
    other = df["detector_id"] == 2
    df.loc[other, "volume"] += np.repeat([-5, -2, 0, 2, 5], 96)
    before = df.copy(deep=True)

    summary, flags = analysis.build_extreme_value_review(df)

    flagged = flags.loc[flags["Date  & Time"] == df.loc[spike, "Date  & Time"]]
    row = flagged.loc[flagged["detector_id"] == 1].iloc[0]
    assert row["volume"] == 900
    assert row["expected_volume"] == 260
    assert row["standardized_residual"] == pytest.approx(640 / sqrt(260))
    first = summary.loc[summary["detector_id"] == 1].iloc[0]
    assert first["q1"] == first["q3"] == first["iqr"] == 0
    assert first["valid_standardized_count"] == 480
    assert first["extreme_count"] == 5
    assert summary.loc[summary["detector_id"] == 2, "iqr"].iloc[0] > 0
    assert first["extreme_count"] == len(flags.loc[flags["detector_id"] == 1])
    assert_frame_equal(df, before)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis.save_extreme_value_summary(summary)
    analysis.save_extreme_value_flagged_rows(flags)
    saved = pd.read_csv(tmp_path / "extreme_value_flagged_rows.csv", parse_dates=["Date  & Time"])
    assert_frame_equal(saved, flags)


def test_no_flags_still_writes_headers_and_zero_expected_counts(tmp_path, monkeypatch):
    df = reference_week()
    df["volume"] = 0
    summary, flags = analysis.build_extreme_value_review(df)
    assert flags.empty
    assert summary["extreme_count"].eq(0).all()
    assert summary["zero_expected_count"].eq(672).all()
    assert summary["valid_standardized_count"].eq(0).all()
    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis.save_extreme_value_flagged_rows(flags)
    saved = pd.read_csv(tmp_path / "extreme_value_flagged_rows.csv")
    assert saved.empty
    assert saved.columns.tolist() == flags.columns.tolist()


def test_positive_observation_with_zero_expected_is_explicit_review_flag():
    df = reference_week(2)
    p = analysis.add_interval_fields(df)
    # Detector 2 supplies the non-zero aggregate workday reference.
    zero_template = df["detector_id"].eq(1) & p["day_type"].eq("workday") & p["slot_index"].eq(10)
    df.loc[zero_template, "volume"] = 0
    summary, flags = analysis.build_extreme_value_review(df)
    zero_flags = flags[flags["flag_reason"] == "positive_volume_with_zero_expected"]
    assert len(zero_flags) == 2
    assert zero_flags["expected_volume"].eq(0).all()
    assert zero_flags["standardized_residual"].isna().all()


def test_regenerated_profiles_load_and_generate_reproducibly(tmp_path, monkeypatch):
    """Run with JAADAH_SYNTHETIC_REPO when the generator is on a companion branch."""
    source_repo = Path(os.environ.get("JAADAH_SYNTHETIC_REPO", analysis.REPO_ROOT))
    if not (source_repo / "traffic_source/synthetic/generator.py").exists():
        pytest.skip("Generator is on its companion branch; set JAADAH_SYNTHETIC_REPO.")
    monkeypatch.syspath_prepend(str(source_repo))
    generator_module = importlib.import_module("traffic_source.synthetic.generator")
    config_module = importlib.import_module("traffic_source.synthetic.config")
    df = reference_week(18)
    values = []
    for detector in range(1, 19):
        for i in range(672):
            day, slot = divmod(i, 96)
            base = 200 + detector * 3 + slot // 12 * 10
            if day < 5:
                volume = base + (day - 2) * 15 * (1 + slot // 24 % 2)
            else:
                volume = round(base * (1.5 if day == 5 else 0.8))
            values.append(volume)
    df["volume"] = values
    monkeypatch.setattr(analysis, "load_rcrc_sample", lambda: df)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis.main()
    for constant, filename in [
        ("PROFILE_SUMMARY_PATH", "rcrc_profile_summary.json"),
        ("DETECTOR_VOLUME_SUMMARY_PATH", "detector_volume_summary.csv"),
        ("DETECTOR_TIME_OF_DAY_PROFILE_PATH", "detector_time_of_day_profile.csv"),
        ("OVERALL_TIME_OF_DAY_PROFILE_PATH", "time_of_day_profile.csv"),
        ("DAY_TYPE_TIME_PROFILE_PATH", "day_type_time_profile.csv"),
        ("TEMPORAL_AUTOCORRELATION_SUMMARY_PATH", "temporal_autocorrelation_summary.csv"),
    ]:
        monkeypatch.setattr(generator_module, constant, tmp_path / filename)
    profiles = generator_module.load_profiles()
    config = config_module.SyntheticSourceConfig(seed=42)
    first = generator_module.SyntheticTrafficGenerator(profiles, config)
    second = generator_module.SyntheticTrafficGenerator(profiles, config)
    start, end = pd.Timestamp("2026-10-15 23:45"), pd.Timestamp("2026-10-18 00:15")
    observations = first.generate_range(start, end)
    assert observations == second.generate_range(start, end)
    assert len(observations) == 194 * len(generator_module.TARGET_DETECTORS)
    assert all(isinstance(row.volume, int) and row.volume >= 0 for row in observations)
    assert first.shared_correlation == profiles.profile_summary["cross_detector_dependence"][
        "mean_residual_correlation_after_removing_time_of_day_and_day_level"
    ]

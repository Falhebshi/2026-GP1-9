import json
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

PRIVATE_DATA_DIR = REPO_ROOT.parent / "jaadah-private-data"

INPUT_FILE = PRIVATE_DATA_DIR / "rcrc_sample.xlsx"

OUTPUT_DIR = (
    PRIVATE_DATA_DIR
    / "processed"
    / "rcrc_sample"
)


def format_local_path(path: Path) -> str:
    """Display local data paths relative to the shared GitHub folder when possible."""

    try:
        return str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Source structure
# ---------------------------------------------------------------------------

DATA_SHEET = "Data"
OBSERVATION_INTERVAL_MINUTES = 15
WEEKEND_SMOOTHING_WINDOW_SLOTS = 5
PROFILE_METHODOLOGY_VERSION = 2

EXPECTED_COLUMNS = [
    "Site ID",
    "detector_id",
    "Date  & Time",
    "volume",
    "description",
]

# Jaadah analysis assumption:
# "Date  & Time" is treated as the END of the 15-minute observation
# interval for internal consistency. This interpretation has not been
# confirmed as an official RCRC timestamp convention.
#
# Example: a record timestamped 12:00 represents [11:45, 12:00).
#
# The original timestamp value is preserved and is used as the
# time-of-day profile label. Calendar grouping and slot ordering use a
# separate interval_start, so midnight belongs to the preceding day.


def add_interval_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Derive calendar and slot fields without changing source timestamps."""

    profiled = df.copy()
    interval_start = profiled["Date  & Time"] - pd.Timedelta(
        minutes=OBSERVATION_INTERVAL_MINUTES
    )
    profiled["interval_start"] = interval_start
    profiled["date"] = interval_start.dt.date
    profiled["day_name"] = interval_start.dt.day_name()
    profiled["day_type"] = np.select(
        [interval_start.dt.dayofweek.eq(4), interval_start.dt.dayofweek.eq(5)],
        ["friday", "saturday"],
        default="workday",
    )
    profiled["time_of_day"] = profiled["Date  & Time"].dt.strftime("%H:%M")
    profiled["slot_index"] = (
        interval_start.dt.hour * 60 + interval_start.dt.minute
    ) // OBSERVATION_INTERVAL_MINUTES

    return profiled


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rcrc_sample() -> pd.DataFrame:
    """Load the local RCRC sample without modifying the source file."""

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "RCRC sample not found.\n"
            f"Expected local file at: {format_local_path(INPUT_FILE)}\n"
            "Place rcrc_sample.xlsx inside the jaadah-private-data "
            "folder beside the project repository."
        )

    df = pd.read_excel(
        INPUT_FILE,
        sheet_name=DATA_SHEET,
        engine="openpyxl",
    )

    return df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def parse_description_parts(descriptions: pd.Series) -> pd.DataFrame:
    """Parse and validate description codes without modifying source values."""

    if not descriptions.map(lambda value: isinstance(value, str)).all():
        raise ValueError("description must contain string values.")

    parts = descriptions.str.split("-", expand=True)
    required_codes_message = (
        "Description values must contain non-empty phase, direction, "
        "lane, and turn codes."
    )

    if parts.shape[1] < 4:
        raise ValueError(required_codes_message)

    parts = parts.apply(lambda column: column.str.strip())
    required_parts = parts.iloc[:, :4]
    incomplete = required_parts.isna().any(axis=1) | required_parts.eq("").any(axis=1)

    if incomplete.any():
        raise ValueError(
            f"{required_codes_message} Incomplete records: {int(incomplete.sum())}"
        )

    found_turn_codes = set(parts[3].unique())
    if not found_turn_codes.issubset({"L", "T", "R"}):
        raise ValueError(
            "Unexpected turn codes found: "
            f"{sorted(found_turn_codes)}"
        )

    return parts


def validate_rcrc_sample(df: pd.DataFrame) -> None:
    """Validate basic schema and data-quality assumptions."""

    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(
            "Unexpected RCRC columns.\n"
            f"Expected: {EXPECTED_COLUMNS}\n"
            f"Found:    {list(df.columns)}"
        )

    if df.empty:
        raise ValueError("RCRC sample contains no records.")

    if df.isna().any().any():
        missing = df.isna().sum()
        raise ValueError(
            f"Missing values detected:\n{missing[missing > 0]}"
        )

    # Check strings before duplicate detection, which requires hashable values.
    parse_description_parts(df["description"])

    if df.duplicated().any():
        raise ValueError(
            f"Duplicate rows detected: {df.duplicated().sum()}"
        )

    duplicate_detector_times = df.duplicated(
        subset=["detector_id", "Date  & Time"]
    ).sum()

    if duplicate_detector_times > 0:
        raise ValueError(
            "Duplicate detector/timestamp records detected: "
            f"{duplicate_detector_times}"
        )

    if (
        not pd.api.types.is_numeric_dtype(df["volume"])
        or pd.api.types.is_bool_dtype(df["volume"])
        or pd.api.types.is_complex_dtype(df["volume"])
    ):
        raise ValueError("volume must contain real numeric vehicle counts.")

    if not np.isfinite(df["volume"]).all():
        raise ValueError("volume must contain finite vehicle counts.")

    if (df["volume"] % 1 != 0).any():
        raise ValueError("volume must contain whole-number vehicle counts.")

    if (df["volume"] < 0).any():
        raise ValueError(
            f"Negative traffic volumes detected: "
            f"{(df['volume'] < 0).sum()}"
        )

    if not pd.api.types.is_datetime64_any_dtype(df["Date  & Time"]):
        raise ValueError("Date  & Time was not loaded as datetime data.")
    if not pd.api.types.is_numeric_dtype(df["Site ID"]):
        raise ValueError("Site ID must be numeric.")

    if not pd.api.types.is_numeric_dtype(df["detector_id"]):
        raise ValueError("detector_id must be numeric.")

    if df["Site ID"].nunique() != 1:
        raise ValueError("RCRC sample must contain exactly one site.")

    description_counts = df.groupby("detector_id")["description"].nunique()
    if (description_counts != 1).any():
        raise ValueError("Each detector must have exactly one description.")


def validate_time_coverage(df: pd.DataFrame) -> None:
    """Require aligned, shared, uninterrupted coverage; allow partial boundary days."""

    expected_interval = pd.Timedelta(minutes=OBSERVATION_INTERVAL_MINUTES)
    timestamps = df["Date  & Time"]

    if df.empty:
        raise ValueError("RCRC sample contains no records.")

    if not timestamps.eq(
        timestamps.dt.floor(f"{OBSERVATION_INTERVAL_MINUTES}min")
    ).all():
        raise ValueError(
            "Timestamps must fall exactly on quarter-hour boundaries "
            "(:00, :15, :30, :45), with no seconds or fractions."
        )

    detector_ranges = df.groupby("detector_id")["Date  & Time"].agg(["min", "max"])
    if (detector_ranges.nunique() != 1).any():
        raise ValueError("All detectors must cover the same start and end time.")

    problems = []

    for detector_id, detector_df in df.groupby("detector_id"):
        detector_df = detector_df.sort_values("Date  & Time")

        time_differences = detector_df["Date  & Time"].diff().dropna()

        invalid_gaps = time_differences[
            time_differences != expected_interval
        ]

        if not invalid_gaps.empty:
            problems.append(
                f"{detector_id}: {len(invalid_gaps)} invalid time gaps"
            )

    if problems:
        raise ValueError(
            "Incomplete 15-minute coverage detected:\n"
            + "\n".join(problems)
        )


# ---------------------------------------------------------------------------
# Basic profiling
# ---------------------------------------------------------------------------

def print_basic_summary(df: pd.DataFrame) -> None:
    """Print high-level information about the RCRC sample."""

    timestamps = df["Date  & Time"]

    print("\nRCRC SAMPLE — BASIC SUMMARY")
    print("=" * 50)

    print(f"Records:            {len(df):,}")
    print(f"Sites:              {df['Site ID'].nunique()}")
    print(f"Site IDs:           {sorted(df['Site ID'].unique().tolist())}")
    print(f"Detectors:          {df['detector_id'].nunique()}")
    print(f"Descriptions:       {df['description'].nunique()}")

    print(f"First timestamp:    {timestamps.min()}")
    print(f"Last timestamp:     {timestamps.max()}")

    print(f"Missing values:     {int(df.isna().sum().sum())}")
    print(f"Duplicate rows:     {int(df.duplicated().sum())}")
    print(
        f"Duplicate detector/times: "
        f"{int(df.duplicated(subset=['detector_id', 'Date  & Time']).sum())}"
    )
    print(f"Negative volumes:   {int((df['volume'] < 0).sum())}")

    records_per_detector = df.groupby("detector_id").size()

    print(
        "Records/detector:   "
        f"min={records_per_detector.min()}, "
        f"max={records_per_detector.max()}"
    )

    print("=" * 50)


# ---------------------------------------------------------------------------
# Detector volume profiling
# ---------------------------------------------------------------------------

def build_detector_volume_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize 15-minute traffic volumes for each detector."""

    summary = (
        df.groupby(
            ["detector_id", "description"],
            as_index=False,
        )
        .agg(
            records=("volume", "size"),
            total_volume=("volume", "sum"),
            mean_volume=("volume", "mean"),
            median_volume=("volume", "median"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values("detector_id")
    )

    return summary


def save_detector_volume_summary(summary: pd.DataFrame) -> None:
    """Save the detector-level volume profile for later synthetic generation."""

    output_file = OUTPUT_DIR / "detector_volume_summary.csv"

    summary.to_csv(
        output_file,
        index=False,
    )

    print("\nDETECTOR VOLUME SUMMARY")
    print("=" * 100)

    print(
        summary.to_string(
            index=False,
            float_format=lambda value: f"{value:.2f}",
        )
    )

    print("=" * 100)
    print(f"\nSaved: {format_local_path(output_file)}")


# ---------------------------------------------------------------------------
# Time-of-day profiling
# ---------------------------------------------------------------------------

def build_time_of_day_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the workday reference by 15-minute interval-end time.

    The source timestamp is preserved as the profile label.
    For example, time_of_day 12:00 represents [11:45, 12:00).
    """

    profiled = add_interval_fields(df)
    profiled = profiled.loc[profiled["day_type"] == "workday"]

    profile = (
        profiled.groupby(["slot_index", "time_of_day"], as_index=False)
        .agg(
            mean_volume=("volume", "mean"),
            median_volume=("volume", "median"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values("slot_index")
    )

    return profile


def save_time_of_day_profile(profile: pd.DataFrame) -> None:
    """Save the 15-minute time-of-day profile."""

    output_file = OUTPUT_DIR / "time_of_day_profile.csv"

    profile.to_csv(
        output_file,
        index=False,
    )

    print("\nTIME-OF-DAY PROFILE")
    print("=" * 75)

    print(
        profile.to_string(
            index=False,
            float_format=lambda value: f"{value:.2f}",
        )
    )

    print("=" * 75)
    print(f"\nSaved: {format_local_path(output_file)}")

    
# ---------------------------------------------------------------------------
# Detector-specific time-of-day profiling
# ---------------------------------------------------------------------------

def build_detector_time_of_day_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Estimate detector-slot means and sample SD from workdays only.

    std_volume uses pandas' ddof=1: do not multiply it by 5/4 again.
    Weekend generation reuses this workday stochastic variability.
    """

    profiled = add_interval_fields(df)
    profiled = profiled.loc[profiled["day_type"] == "workday"]

    profile = (
        profiled.groupby(
            ["detector_id", "description", "slot_index", "time_of_day"],
            as_index=False,
        )
        .agg(
            workday_observation_count=("volume", "count"),
            mean_volume=("volume", "mean"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values(
            ["detector_id", "slot_index"]
        )
    )

    return profile


def save_detector_time_of_day_profile(
    profile: pd.DataFrame,
) -> None:
    """Save detector-specific 15-minute daily profiles."""

    output_file = (
        OUTPUT_DIR
        / "detector_time_of_day_profile.csv"
    )

    profile.to_csv(
        output_file,
        index=False,
    )

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )


# ---------------------------------------------------------------------------
# Day-level profiling
# ---------------------------------------------------------------------------

def build_daily_volume_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize observed traffic by interval-start date, including partial days."""

    profiled = add_interval_fields(df)

    summary = (
        profiled.groupby(
            ["date", "day_name"],
            as_index=False,
        )
        .agg(
            observed_intervals=("Date  & Time", "nunique"),
            total_volume=("volume", "sum"),
            mean_volume=("volume", "mean"),
            median_volume=("volume", "median"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values("date")
    )

    return summary


def save_daily_volume_summary(summary: pd.DataFrame) -> None:
    """Save daily traffic-volume statistics."""

    output_file = OUTPUT_DIR / "daily_volume_summary.csv"

    summary.to_csv(
        output_file,
        index=False,
    )

    print("\nDAILY VOLUME SUMMARY")
    print("Totals cover observed intervals only; 96 intervals represent a complete day.")
    print("=" * 90)

    print(
        summary.to_string(
            index=False,
            float_format=lambda value: f"{value:.2f}",
        )
    )

    print("=" * 90)
    print(f"\nSaved: {format_local_path(output_file)}")


# ---------------------------------------------------------------------------
# Detector correlation analysis
# ---------------------------------------------------------------------------

def build_detector_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate correlations between detector volume time series."""

    pivoted = df.pivot(
        index="Date  & Time",
        columns="detector_id",
        values="volume",
    )

    return pivoted.corr()


def save_detector_correlation_matrix(
    correlation_matrix: pd.DataFrame,
) -> None:
    """Save detector-to-detector volume correlations."""

    output_file = OUTPUT_DIR / "detector_correlation_matrix.csv"

    correlation_matrix.to_csv(output_file)

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )



# ---------------------------------------------------------------------------
# Residual correlation analysis
# ---------------------------------------------------------------------------

def build_residual_observations(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Derive residuals around workday templates and smoothed weekend levels."""

    profiled = add_interval_fields(df)

    workday_means = build_detector_time_of_day_profile(df).set_index(
        ["detector_id", "slot_index"]
    )["mean_volume"]
    keys = pd.MultiIndex.from_frame(profiled[["detector_id", "slot_index"]])
    profiled["workday_slot_expected"] = workday_means.reindex(keys).to_numpy()
    day_profile = build_day_type_time_profile(df).set_index(["day_type", "slot_index"])
    day_keys = pd.MultiIndex.from_frame(profiled[["day_type", "slot_index"]])
    profiled["slot_expected"] = (
        profiled["workday_slot_expected"]
        * day_profile["day_type_adjustment"].reindex(day_keys).to_numpy()
    )

    profiled["residual"] = (
        profiled["volume"] - profiled["slot_expected"]
    )

    # Ratio of sums weights busy slots appropriately. Both totals cover the
    # same observed intervals, including partial boundary days.
    observed_total = profiled.groupby("date")["volume"].transform("sum")
    expected_total = profiled.groupby("date")["slot_expected"].transform("sum")
    profiled["day_factor"] = (
        observed_total / expected_total.replace(0, np.nan)
    )
    profiled["adjusted_expected"] = (
        profiled["slot_expected"] * profiled["day_factor"]
    )
    profiled["adjusted_residual"] = (
        profiled["volume"] - profiled["adjusted_expected"]
    )

    return profiled


def build_residual_correlation_matrix(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Correlate detector variation after removing normal time-of-day patterns."""

    profiled = build_residual_observations(df)

    residuals = profiled.pivot(
        index="Date  & Time",
        columns="detector_id",
        values="residual",
    )

    return residuals.corr()


def print_residual_correlation_summary(
    correlation_matrix: pd.DataFrame,
) -> None:
    """Print strongest, weakest, and mean residual detector correlations."""

    corr = correlation_matrix.copy()

    corr.index = corr.index.astype(str)
    corr.columns = corr.columns.astype(str)

    pairs = []

    columns = corr.columns.tolist()

    for i, detector_a in enumerate(columns):
        for detector_b in columns[i + 1:]:
            pairs.append(
                {
                    "detector_a": detector_a,
                    "detector_b": detector_b,
                    "correlation": corr.loc[
                        detector_a,
                        detector_b,
                    ],
                }
            )

    pairs_df = pd.DataFrame(pairs)

    print("\nSTRONGEST RESIDUAL CORRELATIONS")
    print("=" * 55)
    print(
        pairs_df.nlargest(
            10,
            "correlation",
        ).to_string(
            index=False,
            float_format=lambda value: f"{value:.3f}",
        )
    )

    print("\nWEAKEST RESIDUAL CORRELATIONS")
    print("=" * 55)
    print(
        pairs_df.nsmallest(
            10,
            "correlation",
        ).to_string(
            index=False,
            float_format=lambda value: f"{value:.3f}",
        )
    )

    print(
        "\nMean residual correlation: "
        f"{pairs_df['correlation'].mean():.3f}"
    )


def build_day_adjusted_residual_correlation_matrix(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Measure detector co-movement after removing time-of-day and day-level effects."""

    profiled = build_residual_observations(df)

    residuals = profiled.pivot(
        index="Date  & Time",
        columns="detector_id",
        values="adjusted_residual",
    )

    return residuals.corr()


def save_residual_correlation_matrices(
    residual_correlation: pd.DataFrame,
    day_adjusted_correlation: pd.DataFrame,
) -> None:
    """Save full residual correlations, retaining detector labels and missing values."""

    for filename, matrix in (
        ("residual_correlation_matrix.csv", residual_correlation),
        ("day_adjusted_residual_correlation_matrix.csv", day_adjusted_correlation),
    ):
        output_file = OUTPUT_DIR / filename
        matrix.to_csv(output_file)
        print(f"\nSaved: {format_local_path(output_file)}")


def build_residual_variability_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Pool workday slot residuals using N minus fitted slot means as degrees of freedom.

    This is distinct from per-slot std_volume, which already uses ddof=1.
    No second correction is applied to those per-slot sample SDs. An adjusted
    residual SD is not exported as an unbiased noise estimate: fitting the
    additional shared daily factors needs a different degrees-of-freedom model.
    """

    profiled = add_interval_fields(df)
    workdays = profiled.loc[profiled["day_type"] == "workday"].copy()
    means = workdays.groupby(["detector_id", "slot_index"])["volume"].transform("mean")
    workdays["squared_residual"] = (workdays["volume"] - means) ** 2
    summary = workdays.groupby("detector_id", as_index=False).agg(
        description=("description", "first"),
        residual_count=("volume", "count"),
        fitted_slot_count=("slot_index", "nunique"),
        residual_sum_squares=("squared_residual", "sum"),
    )
    summary["residual_degrees_of_freedom"] = (
        summary["residual_count"] - summary["fitted_slot_count"]
    )
    summary["residual_std"] = np.sqrt(
        summary["residual_sum_squares"]
        / summary["residual_degrees_of_freedom"].replace(0, np.nan)
    )
    return summary.sort_values("detector_id").reset_index(drop=True)


def save_residual_variability_summary(summary: pd.DataFrame) -> None:
    """Save residual variability as a private analysis reference."""

    output_file = OUTPUT_DIR / "detector_residual_variability_summary.csv"
    summary.to_csv(output_file, index=False)
    print(f"\nSaved: {format_local_path(output_file)}")


def calculate_mean_pairwise_correlation(
    correlation_matrix: pd.DataFrame,
) -> float:
    """Calculate the mean correlation across unique detector pairs."""

    pairwise_values = []
    columns = correlation_matrix.columns.tolist()

    for index, detector_a in enumerate(columns):
        for detector_b in columns[index + 1:]:
            value = correlation_matrix.loc[
                detector_a,
                detector_b,
            ]

            if pd.notna(value):
                pairwise_values.append(float(value))

    if not pairwise_values:
        raise ValueError(
            "No valid detector-pair correlations are available."
        )

    return sum(pairwise_values) / len(pairwise_values)


def build_profile_summary(
    df: pd.DataFrame,
    residual_correlation: pd.DataFrame,
    day_adjusted_correlation: pd.DataFrame,
    temporal_summary: pd.DataFrame,
) -> dict:
    """Build a compact machine-readable summary of the traffic profile."""

    return {
        "methodology": {
            "version": PROFILE_METHODOLOGY_VERSION,
            "weekend_smoothing": "centered circular mean of weekend/workday ratios",
            "weekend_smoothing_window_slots": WEEKEND_SMOOTHING_WINDOW_SLOTS,
            "noise_reference": "workdays only; slot sample SD ddof=1 reused on weekends",
            "pooled_residual_variance_denominator": "workday observations minus fitted slot means",
            "day_factor": "sum(observed) / sum(expected), matching observed coverage",
            "random_daily_level_distribution": "not estimated",
        },
        "source": {
            "site_id": int(df["Site ID"].iloc[0]),
            "record_count": int(len(df)),
            "detector_count": int(df["detector_id"].nunique()),
            "interval_minutes": OBSERVATION_INTERVAL_MINUTES,
        },
        "overall_volume": {
            "mean_volume_per_detector_per_15_min_interval": float(
                df["volume"].mean()
            ),
        },
        "cross_detector_dependence": {
            "mean_residual_correlation_after_removing_time_of_day": (
                calculate_mean_pairwise_correlation(
                    residual_correlation
                )
            ),
            "mean_residual_correlation_after_removing_time_of_day_and_day_level": (
                calculate_mean_pairwise_correlation(
                    day_adjusted_correlation
                )
            ),
        },
        "temporal_persistence": {
            "mean_raw_lag1_correlation": float(
                temporal_summary[
                    "raw_lag1_correlation"
                ].mean()
            ),
            "mean_adjusted_lag1_correlation": float(
                temporal_summary[
                    "adjusted_lag1_correlation"
                ].mean()
            ),
        },
    }


def save_profile_summary(profile_summary: dict) -> None:
    """Save the compact traffic-profile summary."""

    output_file = OUTPUT_DIR / "rcrc_profile_summary.json"

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            profile_summary,
            file,
            indent=2,
        )

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )

# ---------------------------------------------------------------------------
# Extreme-value review
# ---------------------------------------------------------------------------

def build_extreme_value_review(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Flag standardized slot deviations for review; never alter observations.

    sqrt(expected) is a practical scaling assumption, not a fitted Poisson
    model. Zero expected values have undefined scores; positive observations
    at those slots are flagged explicitly instead of dividing by zero.
    """

    profiled = build_residual_observations(df)
    profiled["expected_volume"] = profiled["slot_expected"]
    profiled["standardized_residual"] = (
        (profiled["volume"] - profiled["expected_volume"])
        / np.sqrt(profiled["expected_volume"].replace(0, np.nan))
    )
    summaries = []
    flagged = []
    flag_columns = EXPECTED_COLUMNS + [
        "expected_volume", "standardized_residual", "lower_bound", "upper_bound", "flag_reason",
    ]
    for detector_id, detector_df in profiled.groupby("detector_id"):
        scores = detector_df["standardized_residual"].dropna()
        q1 = scores.quantile(0.25)
        q3 = scores.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 3 * iqr
        upper_bound = q3 + 3 * iqr
        zero_expected = detector_df["expected_volume"].eq(0)
        unexpected_positive = zero_expected & detector_df["volume"].gt(0)
        extreme_mask = (
            detector_df["standardized_residual"].lt(lower_bound)
            | detector_df["standardized_residual"].gt(upper_bound)
            | unexpected_positive
        )
        rows = detector_df.loc[extreme_mask].copy()
        rows["lower_bound"] = lower_bound
        rows["upper_bound"] = upper_bound
        rows["flag_reason"] = np.where(
            rows["expected_volume"].eq(0),
            "positive_volume_with_zero_expected", "outside_standardized_3iqr",
        )
        flagged.append(rows[flag_columns])
        summaries.append(
            {
                "detector_id": detector_id,
                "description": detector_df["description"].iloc[0],
                "q1": q1,
                "q3": q3,
                "iqr": iqr,
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
                "extreme_count": int(extreme_mask.sum()),
                "valid_standardized_count": int(scores.count()),
                "zero_expected_count": int(zero_expected.sum()),
                "observed_min": detector_df["volume"].min(),
                "observed_max": detector_df["volume"].max(),
            }
        )

    summary = pd.DataFrame(summaries).sort_values("detector_id").reset_index(drop=True)
    flagged_rows = pd.concat(flagged, ignore_index=True)[flag_columns]
    return summary, flagged_rows


def build_extreme_value_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return the per-detector standardized-review summary."""

    return build_extreme_value_review(df)[0]


def save_extreme_value_flagged_rows(flagged_rows: pd.DataFrame) -> None:
    """Save review records, including an empty CSV with headers if none are flagged."""

    output_file = OUTPUT_DIR / "extreme_value_flagged_rows.csv"
    flagged_rows.to_csv(output_file, index=False)
    print(f"\nSaved: {format_local_path(output_file)}")


def save_extreme_value_summary(summary: pd.DataFrame) -> None:
    """Save the conservative extreme-value review."""

    output_file = OUTPUT_DIR / "extreme_value_summary.csv"

    summary.to_csv(
        output_file,
        index=False,
    )

    print("\nEXTREME-VALUE REVIEW")
    print("=" * 110)

    print(
        summary.to_string(
            index=False,
            float_format=lambda value: f"{value:.2f}",
        )
    )

    print("=" * 110)
    print(
        f"\nTotal flagged observations: "
        f"{summary['extreme_count'].sum()}"
    )

    print(f"Saved: {format_local_path(output_file)}")


# ---------------------------------------------------------------------------
# Jaadah-inferred approach and turning shares
# ---------------------------------------------------------------------------

def build_turning_summary(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Infer approach/direction and turn codes from RCRC descriptions.

    The interpretation is based on the positional structure of the
    hyphen-separated description fields. It must not be presented as an
    official RCRC coding definition.
    """

    profiled = df.copy()

    parts = parse_description_parts(profiled["description"])

    profiled["phase_code"] = parts[0]
    profiled["direction_code"] = parts[1]
    profiled["lane_code"] = parts[2]
    profiled["turn_code"] = parts[3]

    profiled["approach_code"] = (
        profiled["phase_code"]
        + "-"
        + profiled["direction_code"]
    )

    turn_names = {
        "L": "left",
        "T": "through",
        "R": "right",
    }

    profiled["turn"] = profiled["turn_code"].map(turn_names)

    summary = (
        profiled.groupby(
            ["approach_code", "turn"],
            as_index=False,
        )
        .agg(
            total_volume=("volume", "sum"),
        )
    )

    summary["approach_total_volume"] = (
        summary.groupby("approach_code")["total_volume"]
        .transform("sum")
    )

    site_total_volume = summary["total_volume"].sum()

    summary["share_within_approach_pct"] = (
        summary["total_volume"]
        / summary["approach_total_volume"]
        * 100
    )

    summary["share_of_site_volume_pct"] = (
        summary["total_volume"]
        / site_total_volume
        * 100
    )

    turn_order = {
        "left": 0,
        "through": 1,
        "right": 2,
    }

    summary["_turn_order"] = summary["turn"].map(turn_order)

    summary = (
        summary.sort_values(
            ["approach_code", "_turn_order"]
        )
        .drop(columns="_turn_order")
        .reset_index(drop=True)
    )

    return summary


def save_turning_summary(
    summary: pd.DataFrame,
) -> None:
    """Save Jaadah-inferred approach and turning proportions."""

    output_file = (
        OUTPUT_DIR
        / "inferred_approach_turning_summary.csv"
    )

    summary.to_csv(
        output_file,
        index=False,
    )

    print("\nJAADAH-INFERRED APPROACH / TURNING SUMMARY")
    print("=" * 100)

    print(
        summary.to_string(
            index=False,
            float_format=lambda value: f"{value:.2f}",
        )
    )

    print("=" * 100)
    print(
        "\nNOTE: Direction and turning meanings are inferred from "
        "the RCRC description strings and are not treated as an "
        "official RCRC coding definition."
    )

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )

# ---------------------------------------------------------------------------
# Temporal persistence analysis
# ---------------------------------------------------------------------------

def build_temporal_autocorrelation_summary(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Measure 15-minute persistence after removing normal temporal patterns."""

    profiled = build_residual_observations(df)

    rows = []

    for detector_id, detector_df in profiled.groupby("detector_id"):
        detector_df = detector_df.sort_values("Date  & Time")

        raw_lag1 = detector_df["volume"].autocorr(lag=1)

        adjusted_lag1 = detector_df[
            "adjusted_residual"
        ].autocorr(lag=1)

        rows.append(
            {
                "detector_id": detector_id,
                "description": detector_df["description"].iloc[0],
                "raw_lag1_correlation": raw_lag1,
                "adjusted_lag1_correlation": adjusted_lag1,
            }
        )

    return pd.DataFrame(rows).sort_values("detector_id")


def save_temporal_autocorrelation_summary(
    summary: pd.DataFrame,
) -> None:
    """Save and display 15-minute persistence results."""

    output_file = (
        OUTPUT_DIR
        / "temporal_autocorrelation_summary.csv"
    )

    summary.to_csv(
        output_file,
        index=False,
    )

    print("\n15-MINUTE TEMPORAL PERSISTENCE")
    print("=" * 85)

    print(
        summary.to_string(
            index=False,
            float_format=lambda value: f"{value:.3f}",
        )
    )

    print("=" * 85)

    print(
        "\nMean raw lag-1 correlation: "
        f"{summary['raw_lag1_correlation'].mean():.3f}"
    )

    print(
        "Mean adjusted lag-1 correlation: "
        f"{summary['adjusted_lag1_correlation'].mean():.3f}"
    )

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )


# ---------------------------------------------------------------------------
# Day-type time-of-day shape
# ---------------------------------------------------------------------------

def smooth_circular_slot_ratios(ratios: pd.Series) -> pd.Series:
    """Average five adjacent quarter-hour ratios, wrapping slot 95 to slot 0."""

    slots_per_day = 24 * 60 // OBSERVATION_INTERVAL_MINUTES
    full = ratios.reindex(range(slots_per_day))
    half = WEEKEND_SMOOTHING_WINDOW_SLOTS // 2
    wrapped = pd.concat([full.iloc[-half:], full, full.iloc[:half]], ignore_index=True)
    smoothed = wrapped.rolling(
        WEEKEND_SMOOTHING_WINDOW_SLOTS, center=True, min_periods=1
    ).mean().iloc[half:half + slots_per_day]
    smoothed.index = full.index
    return smoothed.reindex(ratios.index)


def build_day_type_time_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Use workday means and smoothed weekend/workday ratios as expected shapes.

    The deterministic five-slot (75-minute) circular smoother suppresses
    single-day spikes. Rescaling preserves the observed weekend mean level.
    observed_mean_volume retains the unsmoothed statistic for review.
    """

    profiled = add_interval_fields(df)
    day_counts = profiled.groupby("day_type")["date"].nunique()
    profile = profiled.groupby(
        ["day_type", "slot_index", "time_of_day"], as_index=False
    ).agg(
        observed_mean_volume=("volume", "mean"),
        slot_day_count=("date", "nunique"),
    )
    workday = profile.loc[profile["day_type"] == "workday"].set_index("slot_index")[
        "observed_mean_volume"
    ]
    if workday.empty:
        raise ValueError("A workday reference is required to estimate expected profiles.")
    profile["workday_mean_volume"] = profile["slot_index"].map(workday)
    if profile["workday_mean_volume"].isna().any():
        raise ValueError("Workday reference is missing slots required by the day-type profiles.")
    profile["mean_volume"] = profile["observed_mean_volume"]
    profile["smoothing_window_slots"] = 1
    for day_type in ("friday", "saturday"):
        rows = profile["day_type"] == day_type
        group = profile.loc[rows].set_index("slot_index")
        if group.empty:
            continue
        reference = group["workday_mean_volume"]
        observed = group["observed_mean_volume"]
        if (reference.eq(0) & observed.gt(0)).any():
            raise ValueError(
                "Cannot estimate a weekend/workday ratio for positive weekend "
                "traffic with a zero workday reference."
            )
        ratios = (observed / reference.replace(0, np.nan)).fillna(1.0)
        expected = reference * smooth_circular_slot_ratios(ratios)
        if expected.mean() > 0:
            expected *= observed.mean() / expected.mean()
        profile.loc[rows, "mean_volume"] = expected.to_numpy()
        profile.loc[rows, "smoothing_window_slots"] = WEEKEND_SMOOTHING_WINDOW_SLOTS
    profile["day_type_adjustment"] = (
        profile["mean_volume"] / profile["workday_mean_volume"].replace(0, np.nan)
    ).fillna(1.0)
    profile["day_count"] = profile["day_type"].map(day_counts)
    profile["day_type_mean_volume"] = profile.groupby("day_type")["mean_volume"].transform("mean")
    profile["normalized_shape"] = (
        profile["mean_volume"] / profile["day_type_mean_volume"].replace(0, np.nan)
    )
    profile["_day_order"] = profile["day_type"].map({"workday": 0, "friday": 1, "saturday": 2})
    return profile.sort_values(["_day_order", "slot_index"]).drop(
        columns="_day_order"
    ).reset_index(drop=True)


def save_day_type_time_profile(
    profile: pd.DataFrame,
) -> None:
    """Save broad day-type traffic-shape profiles."""

    output_file = (
        OUTPUT_DIR
        / "day_type_time_profile.csv"
    )

    profile.to_csv(
        output_file,
        index=False,
    )

    print("\nDAY-TYPE TRAFFIC SHAPE")
    print("Day counts include observed dates; boundary dates may be partial.")
    print("=" * 75)

    for day_type, group in profile.groupby(
        "day_type",
        sort=False,
    ):
        peak = group.loc[
            group["normalized_shape"].idxmax()
        ]

        trough = group.loc[
            group["normalized_shape"].idxmin()
        ]

        print(
            f"{day_type:10s} "
            f"days={int(group['day_count'].iloc[0])} "
            f"peak={peak['time_of_day']} "
            f"({peak['normalized_shape']:.2f}x), "
            f"lowest={trough['time_of_day']} "
            f"({trough['normalized_shape']:.2f}x)"
        )

    print("=" * 75)

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_rcrc_sample()

    validate_rcrc_sample(df)
    validate_time_coverage(df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print_basic_summary(df)

    detector_summary = build_detector_volume_summary(df)
    save_detector_volume_summary(detector_summary)

    time_profile = build_time_of_day_profile(df)
    save_time_of_day_profile(time_profile)

    detector_time_profile = build_detector_time_of_day_profile(df)
    save_detector_time_of_day_profile(detector_time_profile)

    daily_summary = build_daily_volume_summary(df)
    save_daily_volume_summary(daily_summary)

    correlation_matrix = build_detector_correlation_matrix(df)
    save_detector_correlation_matrix(correlation_matrix)

    residual_correlation = build_residual_correlation_matrix(df)
    print_residual_correlation_summary(residual_correlation)

    day_adjusted_correlation = (
        build_day_adjusted_residual_correlation_matrix(df)
    )

    print("\nDAY-ADJUSTED RESIDUAL CORRELATIONS")
    print_residual_correlation_summary(day_adjusted_correlation)

    save_residual_correlation_matrices(
        residual_correlation, day_adjusted_correlation
    )
    residual_variability = build_residual_variability_summary(df)
    save_residual_variability_summary(residual_variability)

    extreme_summary, flagged_rows = build_extreme_value_review(df)
    save_extreme_value_summary(extreme_summary)
    save_extreme_value_flagged_rows(flagged_rows)

    turning_summary = build_turning_summary(df)
    save_turning_summary(turning_summary)

    temporal_summary = build_temporal_autocorrelation_summary(df)
    save_temporal_autocorrelation_summary(temporal_summary)

    day_type_profile = build_day_type_time_profile(df)
    save_day_type_time_profile(day_type_profile)


    profile_summary = build_profile_summary(
    df=df,
    residual_correlation=residual_correlation,
    day_adjusted_correlation=day_adjusted_correlation,
    temporal_summary=temporal_summary,
)

    save_profile_summary(profile_summary)



    print(
        "\nSchema, data quality, and 15-minute coverage "
        "validation passed."
    )


if __name__ == "__main__":
    main()



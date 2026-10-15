import json
from pathlib import Path

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
# time-of-day profile label; timestamps are not shifted backward.


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

    if not pd.api.types.is_numeric_dtype(df["volume"]):
        raise ValueError("volume must be numeric.")

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

    if not pd.api.types.is_string_dtype(df["description"]):
        raise ValueError("description must contain string values.")

    


def validate_time_coverage(df: pd.DataFrame) -> None:
    """Verify that every detector has a complete 15-minute time series."""

    expected_interval = pd.Timedelta(minutes=15)

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
    Calculate average traffic volume by 15-minute interval-end time.

    The source timestamp is preserved as the profile label.
    For example, time_of_day 12:00 represents [11:45, 12:00).
    """

    profiled = df.copy()

    profiled["time_of_day"] = profiled["Date  & Time"].dt.strftime("%H:%M")

    profile = (
        profiled.groupby("time_of_day", as_index=False)
        .agg(
            mean_volume=("volume", "mean"),
            median_volume=("volume", "median"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values("time_of_day")
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
    """Calculate the average 15-minute daily profile for each detector."""

    profiled = df.copy()

    profiled["time_of_day"] = (
        profiled["Date  & Time"].dt.strftime("%H:%M")
    )

    profile = (
        profiled.groupby(
            ["detector_id", "description", "time_of_day"],
            as_index=False,
        )
        .agg(
            mean_volume=("volume", "mean"),
            std_volume=("volume", "std"),
            min_volume=("volume", "min"),
            max_volume=("volume", "max"),
        )
        .sort_values(
            ["detector_id", "time_of_day"]
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
    """Summarize traffic volumes by calendar day."""

    profiled = df.copy()

    profiled["date"] = profiled["Date  & Time"].dt.date
    profiled["day_name"] = profiled["Date  & Time"].dt.day_name()

    summary = (
        profiled.groupby(
            ["date", "day_name"],
            as_index=False,
        )
        .agg(
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

def build_residual_correlation_matrix(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Correlate detector variation after removing normal time-of-day patterns."""

    profiled = df.copy()

    profiled["time_of_day"] = (
        profiled["Date  & Time"].dt.strftime("%H:%M")
    )

    profiled["expected_volume"] = (
        profiled.groupby(
            ["detector_id", "time_of_day"]
        )["volume"]
        .transform("mean")
    )

    profiled["residual"] = (
        profiled["volume"] - profiled["expected_volume"]
    )

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

    profiled = df.copy()

    profiled["date"] = profiled["Date  & Time"].dt.date
    profiled["time_of_day"] = (
        profiled["Date  & Time"].dt.strftime("%H:%M")
    )

    # Normal expected volume for this detector at this clock time.
    profiled["slot_expected"] = (
        profiled.groupby(
            ["detector_id", "time_of_day"]
        )["volume"]
        .transform("mean")
    )

    # Relative volume compared with the detector's usual slot level.
    profiled["relative_volume"] = (
        profiled["volume"]
        / profiled["slot_expected"].replace(0, pd.NA)
    )

    # Overall traffic multiplier for each calendar day.
    day_factors = (
        profiled.groupby("date")["relative_volume"]
        .transform("mean")
    )

    profiled["adjusted_expected"] = (
        profiled["slot_expected"] * day_factors
    )

    profiled["adjusted_residual"] = (
        profiled["volume"]
        - profiled["adjusted_expected"]
    )

    residuals = profiled.pivot(
        index="Date  & Time",
        columns="detector_id",
        values="adjusted_residual",
    )

    return residuals.corr()


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
        "source": {
            "site_id": int(df["Site ID"].iloc[0]),
            "record_count": int(len(df)),
            "detector_count": int(df["detector_id"].nunique()),
            "interval_minutes": 15,
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

def build_extreme_value_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Flag unusually extreme detector volumes for review.

    Values are not removed or modified. A conservative 3×IQR rule is used
    independently for each detector.
    """

    summaries = []

    for detector_id, detector_df in df.groupby("detector_id"):
        volumes = detector_df["volume"]

        q1 = volumes.quantile(0.25)
        q3 = volumes.quantile(0.75)
        iqr = q3 - q1

        lower_bound = max(0, q1 - 3 * iqr)
        upper_bound = q3 + 3 * iqr

        extreme_mask = (
            (volumes < lower_bound)
            | (volumes > upper_bound)
        )

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
                "observed_min": volumes.min(),
                "observed_max": volumes.max(),
            }
        )

    return pd.DataFrame(summaries).sort_values("detector_id")


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

def build_inferred_turning_summary(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Infer approach/direction and turn codes from RCRC descriptions.

    The interpretation is based on the positional structure of the
    hyphen-separated description fields. It must not be presented as an
    official RCRC coding definition.
    """

    profiled = df.copy()

    parts = profiled["description"].str.split("-", expand=True)

    if parts.shape[1] < 4:
        raise ValueError(
            "Description values do not contain the expected code structure."
        )

    profiled["phase_code"] = parts[0]
    profiled["direction_code"] = parts[1]
    profiled["lane_code"] = parts[2]
    profiled["turn_code"] = parts[3]

    valid_turn_codes = {"L", "T", "R"}

    found_turn_codes = set(
        profiled["turn_code"].dropna().unique()
    )

    if not found_turn_codes.issubset(valid_turn_codes):
        raise ValueError(
            "Unexpected inferred turn codes found: "
            f"{sorted(found_turn_codes)}"
        )

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


def save_inferred_turning_summary(
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

    profiled = df.copy()

    profiled["date"] = profiled["Date  & Time"].dt.date
    profiled["time_of_day"] = (
        profiled["Date  & Time"].dt.strftime("%H:%M")
    )

    profiled["slot_expected"] = (
        profiled.groupby(
            ["detector_id", "time_of_day"]
        )["volume"]
        .transform("mean")
    )

    profiled["relative_volume"] = (
        profiled["volume"]
        / profiled["slot_expected"].replace(0, pd.NA)
    )

    profiled["day_factor"] = (
        profiled.groupby("date")["relative_volume"]
        .transform("mean")
    )

    profiled["adjusted_expected"] = (
        profiled["slot_expected"]
        * profiled["day_factor"]
    )

    profiled["adjusted_residual"] = (
        profiled["volume"]
        - profiled["adjusted_expected"]
    )

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

def build_day_type_time_profile(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Compare normalized daily traffic shapes by broad day type.

    Workday represents Sunday-Thursday.
    Friday and Saturday are retained separately.

    Friday and Saturday each occur only once in this sample, so their
    profiles are descriptive rather than stable long-term estimates.
    """

    profiled = df.copy()

    profiled["day_name"] = (
        profiled["Date  & Time"].dt.day_name()
    )

    profiled["time_of_day"] = (
        profiled["Date  & Time"].dt.strftime("%H:%M")
    )

    def classify_day(day_name: str) -> str:
        if day_name in {
            "Sunday",
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
        }:
            return "workday"

        if day_name == "Friday":
            return "friday"

        if day_name == "Saturday":
            return "saturday"

        raise ValueError(f"Unexpected day name: {day_name}")

    profiled["day_type"] = (
        profiled["day_name"].map(classify_day)
    )

    profile = (
        profiled.groupby(
            ["day_type", "time_of_day"],
            as_index=False,
        )
        .agg(
            mean_volume=("volume", "mean"),
        )
    )

    # Mean level across all 96 slots for each day type.
    profile["day_type_mean_volume"] = (
        profile.groupby("day_type")["mean_volume"]
        .transform("mean")
    )

    # 1.0 = normal level for that day type.
    profile["normalized_shape"] = (
        profile["mean_volume"]
        / profile["day_type_mean_volume"]
    )

    day_order = {
        "workday": 0,
        "friday": 1,
        "saturday": 2,
    }

    profile["_day_order"] = (
        profile["day_type"].map(day_order)
    )

    profile = (
        profile.sort_values(
            ["_day_order", "time_of_day"]
        )
        .drop(columns="_day_order")
        .reset_index(drop=True)
    )

    return profile


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
            f"peak={peak['time_of_day']} "
            f"({peak['normalized_shape']:.2f}x), "
            f"lowest={trough['time_of_day']} "
            f"({trough['normalized_shape']:.2f}x)"
        )

    print("=" * 75)

    print(
        "\nFriday and Saturday each represent only one day "
        "in this sample; interpret their shapes descriptively."
    )

    print(
        f"\nSaved: "
        f"{format_local_path(output_file)}"
    )



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_rcrc_sample()

    validate_rcrc_sample(df)
    validate_time_coverage(df)

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

    extreme_summary = build_extreme_value_summary(df)
    save_extreme_value_summary(extreme_summary)

    turning_summary = build_inferred_turning_summary(df)
    save_inferred_turning_summary(turning_summary)

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



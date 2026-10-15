# RCRC Sample Analysis

## Overview

Jaadah uses an authorized RCRC traffic sample as a **development reference** for understanding the structure and behavior of detector-level traffic data.

The sample is not from Jaadah's target intersection. It is therefore not used to estimate traffic demand for the case-study intersection or to represent its measured traffic conditions.

Instead, the analysis is used to understand properties that are useful when designing the synthetic traffic source, including:

- detector-level differences in traffic volume,
- 15-minute time-of-day patterns,
- differences between day types,
- variation shared across detector streams,
- temporal persistence between consecutive intervals,
- and the structure of the source data itself.

The analysis is implemented in:

```text
analysis/rcrc_sample/rcrc_sample_analysis.py
```

The source workbook and every output derived from it are stored outside the Git repository.

---

## Role in the Jaadah Pipeline

The analysis supports the development of the synthetic traffic source.

Conceptually:

```text
Authorized RCRC Sample
        │
        ▼
RCRC Sample Analysis
        │
        │ derived traffic characteristics
        ▼
Synthetic Traffic Source
        │
        ▼
Traffic Ingestion
        │
        ▼
Jaadah Traffic Pipeline
```

The analysis does not directly produce SUMO demand and does not configure the traffic simulation.

Its purpose is to identify statistical and structural characteristics that can inform synthetic detector-level traffic generation while real observations from the target study area are unavailable.

---

## Data and Repository Boundaries

The private traffic sample is intentionally kept outside the repository.

Authorized team members should use the following local structure:

```text
GitHub/
├── 2026-GP1-9/
│   └── analysis/
│       └── rcrc_sample/
│           └── rcrc_sample_analysis.py
│
└── jaadah-private-data/
    ├── rcrc_sample.xlsx
    └── processed/
        └── rcrc_sample/
```

The repository contains:

```text
analysis code
documentation
public tests and project code
```

The repository does **not** contain:

```text
the original RCRC workbook
derived traffic profiles
derived statistics or summaries
```

This keeps the analysis reproducible for authorized team members without publishing restricted traffic-data artifacts.

---

## Expected Source Structure

The analysis expects the workbook to contain a worksheet named:

```text
Data
```

with the following columns:

| Column | Purpose |
|---|---|
| `Site ID` | Source site identifier |
| `detector_id` | Detector identifier |
| `Date  & Time` | Observation timestamp |
| `volume` | Recorded traffic volume |
| `description` | Source detector description |

The script reads the workbook but does not modify it.

---

## Timestamp Interpretation

For Jaadah's internal analysis, each source timestamp is treated as the **end of a 15-minute observation interval**.

For example:

```text
Timestamp: 08:15
```

is interpreted by the analysis as representing the interval:

```text
08:00 <= observation period < 08:15
```

This is a **Jaadah analysis assumption**.

It must not be presented as an official RCRC timestamp convention unless that interpretation is separately confirmed by RCRC.

---

## Validation Before Analysis

The script validates the source before generating any profiles.

It checks that:

- all required columns are present,
- the dataset is not empty,
- required values are not missing,
- exact duplicate rows are absent,
- duplicate detector/timestamp pairs are absent,
- traffic volumes are numeric,
- traffic volumes are non-negative,
- timestamps are loaded as datetime values,
- site identifiers are numeric,
- detector identifiers are numeric,
- detector descriptions are strings,
- and each detector follows complete 15-minute timestamp spacing.

If any required validation fails, the script stops instead of continuing with potentially unreliable input.

This separation between **validation** and **profiling** helps ensure that generated statistics are based on structurally consistent source data.

---

# Analysis Performed

## 1. Detector-Level Volume Profiles

For each detector, the script calculates descriptive traffic statistics including:

```text
record count
total volume
mean
median
standard deviation
minimum
maximum
```

These profiles capture differences in traffic magnitude between detector streams.

This is useful for synthetic generation because the synthetic source should not assign the same traffic baseline to every detector.

---

## 2. Time-of-Day Profiles

The analysis calculates traffic behavior across 15-minute periods of the day.

Two forms are produced:

- an overall time-of-day profile across the source data,
- and detector-specific time-of-day profiles.

These profiles describe how expected traffic volume changes across the day.

They provide the synthetic source with a reference for representing patterns such as higher and lower traffic periods rather than generating traffic around a constant daily mean.

---

## 3. Day and Day-Type Profiles

The script summarizes traffic by calendar day and also groups observations into the following day types:

```text
Workday: Sunday–Thursday
Friday
Saturday
```

Normalized time-of-day profiles are generated for these groups.

This allows the analysis to distinguish changes in both:

- overall daily traffic level,
- and traffic shape across the day.

The resulting day-type patterns are used only as development-time reference behavior and should not be interpreted as measured behavior at Jaadah's target intersection.

---

## 4. Cross-Detector Dependence

Traffic streams at an intersection do not necessarily vary independently.

To examine this, the analysis calculates detector-to-detector correlation in several forms.

### Raw correlation

Correlation is first calculated directly from detector traffic-volume series.

### Time-of-day-adjusted residual correlation

Expected time-of-day behavior is removed before correlation is calculated again.

This helps distinguish shared short-term variation from correlation that exists simply because multiple detectors rise and fall during similar periods of the day.

### Day- and time-adjusted residual correlation

A further calculation removes both:

- expected time-of-day effects,
- and broad day-level effects.

The resulting residual relationships provide a reference for how much random variation may still be shared across detector streams.

These values inform the stochastic behavior of the synthetic source.

---

## 5. Temporal Persistence

The analysis calculates lag-1 autocorrelation for each detector.

Lag-1 autocorrelation measures how strongly the current 15-minute traffic observation is related to the immediately preceding observation.

The script calculates:

- raw lag-1 autocorrelation,
- and an adjusted version after expected temporal patterns are removed.

This provides a reference for synthetic generation because consecutive traffic observations should not necessarily behave as independent random draws.

---

## 6. Extreme-Value Review

The script applies a conservative:

```text
3 × IQR
```

rule independently to each detector to flag unusually extreme observations.

The purpose is diagnostic.

Flagged observations are **not** automatically:

- deleted,
- capped,
- replaced,
- or modified.

This avoids altering the private source data based only on a statistical threshold.

The resulting summary is intended to help reviewers understand whether individual detector streams contain unusually large deviations.

---

## 7. Inferred Approach and Turning Structure

The script also examines the positional structure of the source `description` field.

From that structure, Jaadah derives provisional:

```text
approach categories
turning categories
```

These semantics are **inferred by Jaadah**.

They are not treated as an official interpretation of the RCRC detector coding scheme unless separately confirmed by RCRC.

The inferred turning structure is used only as a development reference for understanding how detector streams may relate to directional traffic.

It is not used as measured turning demand for Jaadah's target intersection.

---

# Generated Outputs

Running the analysis writes derived outputs to:

```text
../jaadah-private-data/processed/rcrc_sample/
```

The generated files are:

| File | Purpose |
|---|---|
| `daily_volume_summary.csv` | Daily traffic-volume summary |
| `day_type_time_profile.csv` | Normalized time-of-day profiles by day type |
| `detector_correlation_matrix.csv` | Detector-to-detector volume correlations |
| `detector_time_of_day_profile.csv` | 15-minute traffic profiles for each detector |
| `detector_volume_summary.csv` | Detector-level descriptive statistics |
| `extreme_value_summary.csv` | Summary of observations flagged by the extreme-value review |
| `inferred_approach_turning_summary.csv` | Jaadah-inferred directional and turning structure |
| `rcrc_profile_summary.json` | Compact summary of characteristics used by the synthetic source |
| `temporal_autocorrelation_summary.csv` | Detector temporal-persistence statistics |
| `time_of_day_profile.csv` | Overall 15-minute time-of-day profile |

All of these files are derived from the private traffic sample and remain outside version control.

---

## Reproducing the Analysis

The private workbook must first exist at:

```text
../jaadah-private-data/rcrc_sample.xlsx
```

From the repository root, run:

```bash
python analysis/rcrc_sample/rcrc_sample_analysis.py
```

If source validation succeeds, the processed outputs are created under:

```text
../jaadah-private-data/processed/rcrc_sample/
```

If the workbook cannot be found or validation fails, the script stops and reports the problem rather than generating incomplete profiles.

---

# Relationship to the Synthetic Traffic Source

The analysis and synthetic source have separate responsibilities.

```text
RCRC analysis
    │
    │ extracts reference characteristics
    ▼
Synthetic generator
    │
    │ creates new detector observations
    ▼
Synthetic traffic source
```

The analysis provides reference characteristics such as:

- detector-specific traffic levels,
- time-of-day variation,
- day-type behavior,
- cross-detector dependence,
- temporal persistence,
- and source-structure information.

The synthetic source then uses those characteristics to generate **new synthetic observations**.

It does not replay the private source records.

It also does not expose the original workbook through its API.

The implementation of the synthetic source is documented separately in:

```text
docs/synthetic_traffic_source.md
```

---

## What the Synthetic Source Preserves

The derived profiles are used to help the synthetic source reproduce broad structural properties observed in the reference sample.

These include:

```text
different baselines across detector streams
15-minute time-of-day variation
broad differences between day types
shared stochastic variation across detectors
detector-specific stochastic variation
temporal persistence between consecutive intervals
non-negative integer traffic counts
reproducible generation through controlled random seeds
```

The goal is not to reproduce the original observations exactly.

The goal is to produce traffic that behaves plausibly enough for development and integration of the Jaadah pipeline.

---

# Assumptions and Limitations

## The sample is not from the target intersection

The most important limitation is that the RCRC sample does not represent Jaadah's case-study intersection.

Therefore, values derived from it must not be interpreted as measurements of the target study area.

This includes:

```text
traffic magnitude
turning proportions
time-of-day patterns
day-type patterns
correlation values
autocorrelation values
```

These values are used only as development references.

---

## The sample has limited temporal coverage

The available sample covers a limited period.

Consequently, the analysis cannot establish long-term seasonal behavior or claim that the observed patterns are representative of Riyadh traffic in general.

---

## Detector semantics are partly inferred

The interpretation of directional and turning information from the `description` field is provisional.

Until the source coding semantics are confirmed by RCRC, Jaadah must describe these classifications as **inferred**, not official.

---

## Observed volume is not automatically equivalent to demand

Detector traffic counts represent observed traffic volume.

Under congested conditions, observed throughput may differ from the number of vehicles that wanted to pass through the location.

For this reason, detector volume should not automatically be interpreted as unconstrained traffic demand.

---

## Timestamp semantics remain an internal assumption

The interval-end interpretation used by Jaadah supports consistent processing of the sample and synthetic source.

However, it remains an internal analysis assumption unless independently confirmed by RCRC.

---

# Reproducibility and Privacy

This workflow is designed to achieve two goals at the same time:

```text
reproducible analysis for authorized team members
+
no publication of restricted traffic data
```

The repository contains the analysis logic, while private inputs and derived outputs remain physically outside it.

This allows the project to document and review the complete analytical method without publishing the underlying traffic sample.

---

## Summary

The RCRC sample analysis provides Jaadah with a structured and reproducible method for studying detector-level traffic behavior during development.

Its role is to extract **reference characteristics**, not to estimate the traffic conditions of the target intersection.

The resulting profiles inform the synthetic traffic source while maintaining a strict separation between:

```text
private source data
derived private artifacts
public project code
synthetic generated observations
target-intersection traffic data
```

This boundary is important throughout the project: conclusions derived from the sample must remain clearly distinguished from measurements of Jaadah's actual case-study intersection.
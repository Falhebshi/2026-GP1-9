# RCRC Sample Analysis

## Purpose

This document describes Jaadah's analysis workflow for an authorized RCRC traffic sample used to inform the design of the synthetic traffic source during development.

The source sample is not from Jaadah's target intersection. It is used only as a reference for source structure, temporal behavior, detector-level variation, and stochastic traffic properties while target observed traffic data is unavailable.

The private source data and all outputs derived from it are intentionally stored outside the Git repository.

## Private Data Layout

For safety, authorized team members should place the private data directory beside the repository rather than inside it.

Expected local structure:

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

The repository contains only the analysis code and documentation. The workbook and generated analysis outputs are not tracked by Git.

## Source Structure

The analysis expects the workbook to contain a sheet named `Data` with the following columns:

- `Site ID`
- `detector_id`
- `Date  & Time`
- `volume`
- `description`

The analysis does not modify the source workbook.

Jaadah currently treats the source timestamp as the end of a 15-minute observation interval for internal consistency. This is a Jaadah analysis assumption and must not be presented as an official RCRC timestamp convention unless confirmed by RCRC.

## Validation

Before profiling, the script validates that:

- the expected columns are present;
- the dataset is not empty;
- required values are not missing;
- exact duplicate rows are absent;
- duplicate detector/timestamp pairs are absent;
- traffic volumes are numeric and non-negative;
- timestamp values are loaded as datetime values;
- site and detector identifiers are numeric;
- descriptions are strings; and
- each detector has complete 15-minute spacing.

The script stops with an error if these checks fail.

## Analysis Performed

### Detector-Level Volume Profiles

For each detector, the script calculates descriptive statistics such as record count, total volume, mean, median, standard deviation, minimum, and maximum.

These profiles help preserve differences in traffic level between detector streams rather than assigning one identical baseline to all synthetic streams.

### Time-of-Day Profiles

The script calculates an overall 15-minute time-of-day traffic profile and detector-specific 15-minute time-of-day profiles.

### Day and Day-Type Profiles

The script summarizes traffic by calendar day and constructs normalized traffic-shape profiles for workdays (Sunday through Thursday), Friday, and Saturday.

### Cross-Detector Dependence

The script calculates detector-to-detector correlations and residual correlation after removing expected time-of-day patterns. A second adjusted calculation removes both time-of-day and broad day-level effects.

### Temporal Persistence

The script measures lag-1 autocorrelation for each detector, including an adjusted version after expected temporal patterns are removed.

### Extreme-Value Review

A conservative `3 × IQR` rule is applied independently to each detector to flag unusually extreme observations for review. Flagged observations are not automatically removed, capped, or modified.

### Inferred Turning Structure

The script parses the positional structure of the source `description` field to derive provisional approach and turning categories.

This interpretation is Jaadah-inferred and must not be presented as an official RCRC coding definition unless the semantics are confirmed by RCRC.

The inferred turning information is used only as a development reference. It is not treated as observed turning demand for Jaadah's target intersection.

## Generated Outputs

When the analysis is executed, the following files are written outside the repository under:

```text
../jaadah-private-data/processed/rcrc_sample/
```

Generated files include:

```text
daily_volume_summary.csv
day_type_time_profile.csv
detector_correlation_matrix.csv
detector_time_of_day_profile.csv
detector_volume_summary.csv
extreme_value_summary.csv
inferred_approach_turning_summary.csv
rcrc_profile_summary.json
temporal_autocorrelation_summary.csv
time_of_day_profile.csv
```

These files are derived from the private RCRC sample and must not be committed to the repository.

## Reproduce the Analysis

Ensure the private workbook exists at:

```text
../jaadah-private-data/rcrc_sample.xlsx
```

From the repository root, run:

```bash
python analysis/rcrc_sample/rcrc_sample_analysis.py
```

If validation succeeds, the generated outputs will be written to:

```text
../jaadah-private-data/processed/rcrc_sample/
```

## Relationship to Synthetic Traffic Generation

The analysis is used to identify structural properties that the synthetic source should preserve, including detector-specific baseline differences, 15-minute time-of-day variation, broad day-type behavior, shared variation across detector streams, detector-specific stochastic variation, temporal persistence, non-negative integer vehicle counts, and reproducibility through controlled random seeds.

The synthetic source does not expose or reproduce the original private records. It uses derived traffic characteristics as development-time reference behavior.

## Limitations

The source sample is limited in duration and is not from Jaadah's target intersection. Therefore, its traffic levels, turning proportions, correlation values, and temporal patterns should not be interpreted as measurements of the target study area or as universal traffic parameters.

Jaadah-inferred detector semantics remain provisional until confirmed by RCRC.

Detector counts represent observed traffic volume and should not automatically be interpreted as unconstrained traffic demand under congested conditions.

## Analysis Outcome

This workflow provides a reproducible method for extracting development-time traffic characteristics while keeping the private source workbook and all derived outputs physically outside the Git repository.

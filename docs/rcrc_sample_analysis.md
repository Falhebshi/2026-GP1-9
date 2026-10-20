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

The current reference contains one week: 18 detectors with 672 quarter-hour
observations each, equivalent to five workdays (Sunday–Thursday), one Friday
and one Saturday. Under the interval-end convention, boundary observations
span partial calendar dates; these are not additional complete sample days.
This is too little evidence to establish detailed weekend shapes or a robust
separate distribution of random daily traffic levels. All fitted parameters
are development references, not universal traffic properties.

The sample’s interval-end timestamps span 28 April 2024 at 00:00 through 4 May 2024 at 23:45, using the assumed Asia/Riyadh timezone (UTC+03:00). Under Jaadah’s interval-end interpretation, the corresponding interval-start coverage also includes the final 15-minute interval of 27 April and ends before the final interval of 4 May.

The sample period falls outside Ramadan and the major nationwide Eid holidays. However, it includes a KSU extended-weekend academic break on Thursday, 2 May 2024. The current analysis still classifies that Thursday as a workday; the effect of the academic break is not isolated from the workday reference. Therefore, the five observed workdays should not be assumed to represent a completely typical academic week.
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

which **has exactly these five columns, in this order**:

| Column | Purpose |
|---|---|
| `Site ID` | Source site identifier |
| `detector_id` | Detector identifier |
| `Date  & Time` | Observation timestamp |
| `volume` | Recorded traffic volume |
| `description` | Source detector description |

Column names must match exactly, including the two spaces between `Date` and
`& Time`. Extra columns, missing columns and a different column order are
rejected by validation.

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

The source timestamp is preserved. Calendar dates, weekdays and day types are
derived from a separate `interval_start` equal to the timestamp minus 15 minutes.
For example, a record ending at Friday 00:00 belongs to Thursday's traffic and
uses the workday classification. This rule also applies to the daily factors
used in day-adjusted correlations and adjusted temporal persistence.

Time-of-day profiles retain their interval-end `time_of_day` labels and include
an explicit `slot_index` derived from the interval start. Slots run from 0 to 95:
slot 0 ends at 00:15 and slot 95 ends at 00:00 the next day. Overall,
detector-specific and day-type profiles are sorted by this index within each
group, so the midnight-ending interval appears last. Consumers should select
profiles by label or slot index rather than assuming alphabetical time order.

Changing the calendar grouping requires regenerating the derived profiles with
the corrected script. Any synthetic-source consumer must also classify an
interval-ending observation by its interval-start day, especially at midnight.

---

## Validation Before Analysis

The script validates the source before generating any profiles.

It checks that:

- all required columns are present,
- the dataset is not empty,
- required values are not missing,
- exact duplicate rows are absent,
- duplicate detector/timestamp pairs are absent,
- traffic volumes are finite, whole-number numeric counts (including values such as `12.0`),
- traffic volumes are non-negative,
- timestamps are loaded as datetime values,
- site identifiers are numeric,
- exactly one site is present,
- detector identifiers are numeric,
- every detector description is a string, checked explicitly with `isinstance(value, str)`,
- each detector has exactly one description,
- descriptions contain non-empty inferred phase, direction, lane and turn codes,
- inferred turn codes are `L`, `T` or `R`,
- timestamps fall exactly on `:00`, `:15`, `:30` or `:45`, with no seconds or fractions,
- all detectors cover the same start and end time,
- and each detector follows uninterrupted 15-minute timestamp spacing.

Under the interval-end convention, a complete traffic day contains 96 records
per detector, timestamped from `00:15` through `00:00` the following day.
Partial days at the beginning and end of the recorded series are allowed.
All detectors must still share the same coverage, with no gaps inside it.
Validation does not round volumes, fill gaps or drop records.

A series beginning at `00:00` and ending at `23:45` retains its first observation
under the preceding traffic day. The final traffic day lacks the interval ending
at the following midnight. A seven-day series with those boundaries therefore
covers one interval of the preceding day, six complete days and 95 intervals
of the last day. Every observation is retained under the interval-end assumption.

If any required validation fails, the script stops instead of continuing with potentially unreliable input.

All source and time-coverage checks run before creating the output directory
or saving any profiles. Invalid input raises an error instead of silently
excluding records or overwriting earlier results.

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

- an overall workday time-of-day reference,
- and detector-specific workday time-of-day profiles.

Only Sunday–Thursday observations enter these two profiles. In particular,
`detector_time_of_day_profile.csv` uses workday `mean_volume` and sample
`std_volume` (`ddof=1`), with `workday_observation_count` recording the actual
number of observations per detector-slot. The current sample has five per
slot. No extra `5/4` multiplier is applied: the per-slot sample SD already uses
the `n−1` denominator. The generator reuses this workday noise magnitude on
Friday and Saturday as a development assumption; weekend noise cannot be
separately estimated from one example of each. All-week descriptive volume
statistics remain in `detector_volume_summary.csv`.

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

`daily_volume_summary.csv` includes `observed_intervals`, the number of distinct
timestamps for each interval-start date across detectors. A complete day has
96 intervals; counts such as 1 or 95 identify partial boundary days. Daily
totals sum only the observed traffic and are not extrapolated to 24 hours.
They should be compared with their coverage in view.

Workday slot means form the expected temporal reference. For each weekend
type, the observed aggregate detector-slot mean is divided by the matching
workday mean. These ratios are smoothed with a centered five-slot rolling
mean (75 minutes), wrapping the 96-slot daily template at midnight. This
wraps within the same day-type template, not into a neighbouring day's data.
Multiplying the workday curve by the smoothed ratio gives the weekend
expected curve, rescaled to preserve that weekend type's observed mean level.
Broad weekend differences remain, while single-slot spikes are reduced.

This deterministic smoothing is a modelling assumption, not evidence of a
well-estimated weekend pattern. `observed_mean_volume` preserves the raw
aggregate statistic; `mean_volume`, `day_type_mean_volume` and
`normalized_shape` describe the expected curve consumed by the generator.
`workday_mean_volume`, `day_type_adjustment` and `smoothing_window_slots`
make its construction explicit. A zero workday mean with zero weekend mean
has neutral adjustment and zero expected volume. Positive weekend traffic
against a zero aggregate workday reference raises an error rather than
inventing a ratio.

Each profile row includes `day_count`: the number of distinct interval-start
dates observed for that day type. Multiple detectors do not multiply this
count, and midnight observations belong to the preceding traffic day. Partial
boundary dates are included, so `day_count` is not a count of complete days.
`slot_day_count` records distinct contributing dates for each slot. In this
sample, Saturday's boundary observations belong to two partial Saturdays,
but each Saturday slot still has only one observed example.
The counts are saved in `day_type_time_profile.csv` and printed alongside each
day type's peak and lowest slot. They are computed from the input rather than
assuming a one-week workbook; two complete weeks contain 10 workdays, two
Fridays and two Saturdays.

Descriptive profiles and daily adjustment factors retain all observations,
including partial boundary dates; the stochastic slot-noise estimates use
workdays only. Statistics for partial dates reflect their observed slots;
missing boundary intervals are not imputed.

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

Expected detector traffic is its workday slot mean multiplied by the smoothed
day-type adjustment. This expected behavior is removed before correlation is
calculated again, keeping broad weekend differences out of the residual baseline.

This helps distinguish shared short-term variation from correlation that exists simply because multiple detectors rise and fall during similar periods of the day.

### Day- and time-adjusted residual correlation

A further calculation removes both:

- expected time-of-day effects,
- and broad day-level effects.

For each interval-start date, the shared day factor is
`sum(observed volume) / sum(expected volume)`, across detectors and the same
observed intervals. This gives busy slots appropriate weight instead of
averaging ratios that give a quiet night slot equal weight. Expected volume
is multiplied by that factor before subtraction. The same construction feeds
adjusted correlations and temporal persistence. Partial-day totals cover only
their observed slots.

The resulting residual relationships provide a reference for how much random variation may still be shared across detector streams.

Both full residual correlation matrices are saved with detector IDs on both
axes, alongside the existing raw correlation matrix. The compact JSON retains
the mean pairwise correlations; these averages do not preserve every
detector-pair relationship.

When a day's expected total is zero, its factor and adjusted residuals are
undefined (`NaN`), not a fabricated multiplier. Zero observations and zero
slot expectations remain intact. Matrix entries use available paired residuals.
The 672 observations per detector are useful for describing co-movement, but
serial dependence means they are not necessarily 672 independent observations.

### Detector residual variability

`detector_residual_variability_summary.csv` contains one row per detector with
its description and a pooled workday noise estimate. `residual_std` is
`sqrt(residual_sum_squares / residual_degrees_of_freedom)`, where degrees of
freedom equal `residual_count − fitted_slot_count`. For five complete workdays,
that is `480 − 96 = 384`, because each slot mean was estimated from these data.
Counts and degrees of freedom are computed from the actual coverage, not
hardcoded. Units are vehicles per 15-minute interval.

This is a separate estimate from the per-slot sample SD. It does not apply a
second correction to those SDs. The old `day_adjusted_residual_std` and
`day_adjusted_residual_count` fields are removed: a simple pooled `N−1` SD
after fitting additional shared daily factors is not exported as an unbiased
noise estimate. No generator consumer used those fields.

Undefined correlations and standard deviations are saved as empty CSV cells.
For example, the pooled workday SD requires positive residual degrees of freedom,
and a constant residual series has undefined correlation. Missing values must
not be interpreted as zero variability or zero dependence. A measured constant
residual series with enough observations does have a standard deviation of zero.

The full residual matrices and residual variability summary are analysis
references. The current synthetic generator uses the mean adjusted correlation
and slot-level volume standard deviations, as described below.

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

Each observation is standardized against the same detector/day-type slot
expectation used by the residual analysis:

```text
standardized_residual = (volume − expected_volume) / sqrt(expected_volume)
```

This is practical review scaling, not a claim that traffic follows a Poisson
model. Valid scores from all available observations are pooled separately for
each detector. Q1, Q3 and IQR are calculated on those scores; scores outside
`Q1 − 3×IQR` through `Q3 + 3×IQR` are flagged. Negative lower bounds are valid
on this standardized scale.

Zero expected values have undefined scores and are counted separately.
Positive observed volume with zero expected volume gets an explicit
`positive_volume_with_zero_expected` review flag. A zero observation with
zero expectation is not automatically flagged. The summary retains
`extreme_count` and adds `valid_standardized_count` and `zero_expected_count`.
`extreme_value_flagged_rows.csv` saves the actual original records, their
expected values, scores, bounds and flag reasons. Even with no flags, this
file is written with its expected headers.

The flagging method and noise/profile assumptions are methodology version 2.
Measured correlation, persistence and flag-count results are regenerated into
the private outputs rather than hardcoded into this document. Re-running on
another workbook must recompute them; old numeric results are not reused.

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

Whitespace around parsed description parts is trimmed for interpretation while
the original source descriptions remain unchanged. Every record must have the
four required non-empty codes; a missing turn code is rejected before grouping.
Unsupported turn codes also raise an error rather than being guessed or dropped.

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
| `day_adjusted_residual_correlation_matrix.csv` | Full detector-pair correlations after time-of-day and shared day-level adjustment |
| `detector_correlation_matrix.csv` | Detector-to-detector volume correlations |
| `detector_residual_variability_summary.csv` | Pooled workday residual SD, sum of squares, counts and fitted-slot degrees of freedom |
| `detector_time_of_day_profile.csv` | Workday detector-slot means, sample SD and observation counts |
| `detector_volume_summary.csv` | Detector-level descriptive statistics |
| `extreme_value_summary.csv` | Summary of observations flagged by the extreme-value review |
| `extreme_value_flagged_rows.csv` | Original flagged records with slot expectations, standardized scores, bounds and reasons |
| `inferred_approach_turning_summary.csv` | Jaadah-inferred directional and turning structure |
| `rcrc_profile_summary.json` | Compact summary of characteristics used by the synthetic source |
| `residual_correlation_matrix.csv` | Full detector-pair correlations after removing time-of-day means |
| `temporal_autocorrelation_summary.csv` | Detector temporal-persistence statistics |
| `time_of_day_profile.csv` | Aggregate workday 15-minute reference profile |

All of these files are derived from the private traffic sample and remain outside version control.

There are 14 output files. Existing filenames are retained; the flagged-row
CSV is new. The compact JSON keeps its existing statistical keys and adds
`methodology` version 2, smoothing/noise assumptions and daily-factor method.
Regenerate the entire set together. The separate synthetic-source PR must
validate this version and the new workday-noise and smoothed-shape columns.
Generator loader changes are not part of this analysis PR.

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

The following subset defines the consumer contract for the separate
`feature/synthetic-traffic-source` PR, which generates **new synthetic observations**.
This PR changes the analysis and its outputs; generator integration is reviewed
and delivered in that companion PR.

| File | Consumer use |
|---|---|
| `rcrc_profile_summary.json` | Overall mean volume and one mean day-adjusted residual correlation for shared variation |
| `detector_volume_summary.csv` | Select reference-detector templates and normalize their average volume |
| `detector_time_of_day_profile.csv` | Workday detector-slot mean and workday sample `std_volume`, reused for all day types |
| `time_of_day_profile.csv` | Aggregate workday slot reference level |
| `day_type_time_profile.csv` | Workday and smoothed weekend expected levels and normalized shapes |
| `temporal_autocorrelation_summary.csv` | Per-detector adjusted lag-1 persistence |

The generator does not currently read either full residual matrix or
`detector_residual_variability_summary.csv`. Saving these outputs makes the
detailed analysis available for review and future calibration; it does not
introduce a full detector-pair covariance model. Slot-level `std_volume` now
uses only workday observations. The companion PR must consume those SDs,
validate methodology version 2 and select day type from the interval-start day,
so a midnight-ending record belongs to the preceding day type. Template
selection, scenario scales and seeded innovations are outside this analysis PR.
There is no explicit random daily-level multiplier in the inspected generator, and no robust
separate daily random-level distribution is estimated from five workdays.
A producer's deterministic daily seed is for reproducibility, not such a factor.

Analysis tests run independently of the generator checkout. The optional
cross-branch integration test runs when `JAADAH_SYNTHETIC_REPO` points to the
companion checkout; otherwise it reports a skip. It verifies the contract
without adding generator source changes to this PR.

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

The sample is only the one-week window documented above. The Friday profile
comes from **3 May 2024 alone**. The Saturday profile has only **one observation
per slot**, equivalent to one day's data: its midnight-ending slot belongs to
27 April and its other 95 slots to 4 May under the interval-end convention.
Those two partial dates do not provide two independent Saturday profiles.

Neither weekend profile is replicated across weeks. Smoothing reduces local
spikes but does not add independent days of evidence. Differences within this
week can be described; week-to-week variation, a stable repeating weekly
pattern and seasonal variation cannot be inferred from this sample. Ramadan,
holiday and school-term effects cannot be estimated separately either. The
school-break overlap further limits interpreting these profiles as typical
traffic, and they are not representative measurements of Riyadh generally.

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

**Console output is also private derived data.** Printed tables, correlations,
flagged-record details, summaries and diagnostic messages can expose source
information even when no CSV is attached. Do not paste unredacted output or
terminal screenshots into PRs, issues, shared discussions or shared logs; do
not commit it or expose real-workbook runs in CI logs. Any captured stdout or
stderr must remain in restricted local files outside version control, with
the same handling as the private derived outputs. For PR verification, share
artificial-fixture test results or a reviewed, redacted pass/fail summary.

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

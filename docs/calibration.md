# SUMO Calibration and Validation 

Calibration checks that the simulated intersection behaves like the real one, by measuring SUMO the same way RCRC measured the road: with a detector at each of the 12 stop-bar positions of site 1444.

## Acceptance criteria

Agreed on 19 Nov 2026 after two team reviews. The values the code uses are in `jaadah/calibration/parameters.py`.

| Item | Rule |
|---|---|
| Measures | Volume and occupancy per detector per 15 minutes: RCRC site 1444 (12 stop-bar detectors) against SUMO induction loops at the mapped positions |
| Compared unit | One detector-hour: the sum of four 15-minute counts |
| Eligible | All four observed intervals reported and none imputed, and every seed has all four simulated intervals |
| Days | Only days after the late-August demand increase; the National Day week (20–26 Sep 2026) is left out, and so is any day with more than 10% of its test-hour intervals imputed, counted over all 12 detectors |
| Split | Whole weeks, calibration weeks first, validation weeks later, with the same mix of workdays, Fridays and Saturdays: 30 Aug – 12 Sep for calibration and 27 Sep – 3 Oct for validation (2 + 1 weeks), or 30 Aug – 19 Sep and 27 Sep – 10 Oct (3 + 2) if runs are fast |
| Hours | The two busiest hours of each day type (workday, Friday, Saturday, all 12 detectors summed), at least 3 hours apart, found on the calibration weeks only and kept fixed for validation; listed in `TEST_HOUR_STARTS`. Quiet hours are left out because GEH is more lenient at low volumes. A test hour belongs to the calendar day it falls in: Friday 00:00–01:00 is Thursday-night traffic, Saturday 00:00–01:00 is Friday night |
| Warm-up | Each test-hour run starts 15 minutes before the hour, with its demand loaded, and ends 15 minutes after it, as a baseline run does. Loop periods start at the run start, so they line up with the source's 15-minute intervals |
| Pass (primary) | GEH < 5 for at least 85% of eligible detector-hours, checked separately on the calibration and the validation set. This pass rate on all eligible hours is the result. The number of eligible detector-hours is reported; a set with fewer than 100 is called indicative |
| Within capacity | Reported next to the result. A detector-hour is within capacity when the observed hourly volume of its lane group is at or below that lane group's capacity under the network's signal plan: saturation flow × effective green / cycle, as the KPI engine calculates it. Failing hours over capacity are a signal-plan limitation, not a driver-behaviour one: the real controller is actuated and can give an approach more green than the fixed plan. This rule was set before the full results were seen |
| Reported, not pass/fail | Observed against simulated occupancy, 15-minute GEH and errors, time-series plots. Occupancy is not pass/fail because it depends on the signal plan: the real controller is actuated, the model runs one fixed plan. It is compared as a pattern (when it rises and falls), not as exact values, because a SUMO loop is not the same length as the real detector |
| Seeds | Tuning on seed 42. Acceptance uses, for each detector-hour, the GEH of the mean simulated count over 4 seeds; the pass rate of each seed and the spread between seeds are reported |
| Tuned | SUMO driver parameters `tau`, `sigma`, `minGap`, `accel`, `decel`, `speedFactor`; lane-change parameters only if lane-level counts stay off |
| Not tuned | Demand (it comes from the counts), the signal plan, the slip and bypass share assumptions |
| Stop tuning | When the target is met, or when a round improves the pass share by less than 1 percentage point; what was reached is reported either way |

```text
GEH = sqrt(2 (M - C)^2 / (M + C))     M = simulated, C = observed, vehicles per hour
C = 600, M = 660  ->  GEH = 2.39  (match)
C = 600, M = 780  ->  GEH = 6.85  (no match)
```

The target GEH < 5 for at least 85% of hourly flows follows the Wisconsin DOT calibration criteria reproduced as an example in FHWA (2004), Table 4 (based on UK guidelines). FHWA (2019) uses broader criteria. The combination above is Jaadah's own protocol, not one FHWA prescribes.

- Dowling, R., Skabardonis, A. and Alexiadis, V. (2004). *Traffic Analysis Toolbox Volume III: Guidelines for Applying Traffic Microsimulation Modeling Software.* FHWA-HRT-04-040, FHWA, June 2004.
- Wunderlich, K., Vasudevan, M. and Wang, P. (2019). *TAT Volume III: Guidelines for Applying Traffic Microsimulation Modeling Software, 2019 Update to the 2004 Version.* FHWA-HOP-18-036, FHWA, April 2019.

**Limitations.** No travel times or queue lengths were observed, so delay and queues are checked only indirectly, through occupancy. Detector positions are modelled, not surveyed. Source time stamps are assumed to mark interval ends. The model runs a fixed signal plan where the real one is actuated. Slip and bypass demand rests on assumed shares.

## Results 

Calibration (30 Aug – 12 Sep 2026) and validation (27 Sep – 3 Oct 2026) were both run with 4 seeds and SUMO's default driver settings. No parameter was tuned, for the reasons below. The figures stay outside the repository, with the other RCRC-derived numbers, in `../jaadah-private-data/processed/calibration/results/calibration_final.*` and `validation_final.*`.

- **Validation meets the target; calibration falls just short of it.** On all eligible detector-hours, validation reaches the 85% target and calibration misses it by a single detector-hour. Both sets are within sampling uncertainty of the 85% line, and the model behaves the same way on the unseen validation week as on the calibration weeks.
- **Within capacity, both sets exceed the target.**
- **The seeds agree closely.** The pass rates of the 4 seeds differ by about one percentage point, so 4 seeds are enough.
- **North and South match almost completely; East matches well; West does not.**

The misses have two causes, and neither is driver behaviour, so tuning the driver settings would only hide them:

1. **Signal plan.** At its busiest hours, the West approach carries more traffic than the fixed Webster plan's green can serve, so SUMO passes fewer vehicles than were counted. The real controller is actuated and can give that approach more green. This is a limitation of the single fixed plan; see issue #70 (actuated signal).
2. **Shared-lane split.** Where the plan has capacity, the remaining misses are on the East and West approaches: each approach's total matches, but vehicles are distributed differently across the lanes, in opposite directions on the two approaches, around the shared lanes `LANE_E_2` and `LANE_W_2`. This follows from the proportional split of the shared-lane counts between the left-turn and through movements, which is a demand assumption: RCRC supplied no turning counts. The split is not tuned, because the same detectors build the demand and check it, so fitting it to the score would be circular. A sensitivity check and a field count are proposed as future work.

## What is built

| Module | What it does |
|---|---|
| `jaadah/calibration/detectors.py` | Selects the source's detectors at a site from `network_mappings.json` and writes a SUMO additional file with one induction loop (E1) per detector, at the mapped `sumo_lane_id` and `sumo_position_m`, period 900 s. A detector without a position is an error, not a skip. |
| `jaadah/calibration/e1_output.py` | Reads the loops' output into `DetectorInterval` records: detector, interval end in Riyadh time, vehicle count (`nVehContrib`) and occupancy (%). |
| `jaadah/calibration/geh.py` | Sums four 15-minute counts into an hourly count, compares observed with the mean of the seeds' simulated counts, and computes GEH, the pass share and whether the target is met. |
| `traffic_source/rcrc_replay/config.py` | `ReplayConfig.from_environment()`: the replay offset can be set with `JAADAH_REPLAY_OFFSET_WEEKS` (see `rcrc_replay_source.md`). |
| `jaadah/calibration/peak_hours.py` | The day type of a date and its two test hours, in Riyadh time. |
| `jaadah/calibration/vehicle_type.py` | Checks driver settings (only the attributes in `TUNABLE_VEHICLE_ATTRIBUTES`) and writes a copy of a route file with them set on its vehicle type. |
| `simulation/scripts/run_calibration.py` | Runs every test hour of a range of days, for each seed, scores the model, and marks each detector-hour within or over its lane group's capacity using the KPI engine (`backend/analytics/kpi/capacity.py`). The capacity part lives in the script because `jaadah/` must not import from `backend/`. |

## Running a calibration

```powershell
$env:JAADAH_REPLAY_OFFSET_WEEKS = "0"
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002     # in its own terminal
python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12
python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12 --set tau=1.2 --set sigma=0.4 --seeds 42 43 44 45 --jobs 2
```

For each test hour and seed the runner:

1. reads the hour, with its warm-up and clearance, from the replay source and builds the SUMO demand with the same steps as `run_baseline.py` (ingestion, demand transformation, departure planning, demand writer, demand checks). An hour whose demand cannot be built is skipped and listed, never filled in;
2. keeps the generated demand in `../jaadah-private-data/processed/calibration/demand/<mapping_version>/` and reuses it on later runs, so tuning only reruns SUMO. The observations for all test hours, with their 35-day history, are read from the replay source once and sliced per hour (the source returns rows ordered by interval end, so a slice equals a separate request), and the seed-independent steps (ingestion, history, demand transformation) are done once per hour; only departure planning and the demand files are per seed;
3. runs SUMO with the induction loops and without FCD output, with the same settings as a baseline run (`--begin 0`, step 0.4 s, the seed, `--random false`). Settings given with `--set` go on a copy of the route file; the generated demand is never changed;
4. compares each detector-hour with the observed counts, on the mean of the seeds, and once per seed;
5. calculates each lane group's capacity for the hour with the KPI engine, from the hour's movement demand and the signal plan in the network, and compares it with the lane group's observed volume (the sum of its detectors' counts).

It shows each SUMO run as it finishes, then prints the share of eligible detector-hours with GEH below 5 (all hours, which is the result, and within capacity), per approach and, with several seeds, per seed with the spread. A set with fewer than 100 detector-hours is marked indicative. It writes the detail (one row per detector-hour, with observed and simulated count, GEH, occupancy, lane group, its observed volume and capacity, and whether it is within capacity) and a summary to `../jaadah-private-data/processed/calibration/results/<label>.csv` and `.json`. These files hold numbers derived from RCRC data, so they stay in the private data folder.

The runner reuses `run_baseline.py`'s constants and building blocks but repeats its short ingestion-to-demand sequence, because `run_baseline.py` runs SUMO in the same function. The tuning itself (choosing which settings to try) is done by hand with `--set`.

## Charts

```powershell
python analysis/calibration/calibration_charts.py
```

`analysis/calibration/calibration_charts.py` reads `calibration_final.csv` and `validation_final.csv` (other files with `--calibration` and `--validation`) and draws two figures, calibration and validation side by side:

- `observed_vs_simulated`: one point per detector-hour (mean of the seeds), the line of perfect agreement and the band where GEH < 5; within-capacity hours are blue circles and over-capacity hours orange triangles, so the distinction does not rely on colour alone;
- `geh_distribution`: the number of detector-hours per GEH bin of 1, stacked by within and over capacity, with the GEH = 5 threshold marked and everything from 15 up in one bar.

Each is written as PNG (300 dpi) and SVG to `../jaadah-private-data/processed/calibration/figures/`, because the figures show RCRC-derived values. The script needs `matplotlib` (in `requirements.txt`).

## Rules and why

- **Loop IDs** are `E1_<site>_<detector>` (e.g. `E1_1444_144409`). They are SUMO-side IDs; the reader turns them back into source detector IDs, so nothing outside this package sees them.
- **Intervals align with the source.** Every Jaadah run starts on a 15-minute boundary and E1 aggregation starts at simulation second 0, so each 900 s period is one source interval. Intervals are labelled by their end, like source time stamps.
- **Count = `nVehContrib`**, the vehicles whose front passed the loop in the interval.
- **Hourly count = the sum of four 15-minute counts**, GEH is defined on hourly flows.
- **Missing is never zero.** A detector-hour is compared only if all four observed intervals were reported and every seed has all four simulated intervals. A reported 0 is kept.
- **Seeds are averaged before GEH**: one GEH per detector-hour on the mean simulated count.
- **No comparisons is not a pass**: `pass_share` and `meets_target` return `None`.
- **No RCRC values in the repo.** Tests use invented counts; results and statistics stay in the private data folder, outside the repository.

## Detector positions

The positions are the modelled lane end minus 1 m, copied from the synthetic placement (`network_mapping.md`), not surveyed locations. Calibration results must name this as a limitation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q jaadah/calibration tests/test_rcrc_replay_offset.py tests/test_run_calibration.py tests/test_calibration_charts.py
```

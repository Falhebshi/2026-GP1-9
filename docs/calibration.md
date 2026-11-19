# SUMO Calibration and Validation 

Calibration checks that the simulated intersection behaves like the real one, by measuring SUMO the same way RCRC measured the road: with a detector at each of the 12 stop-bar positions of site 1444.

## Acceptance criteria (proposed)

Proposed on 19 Nov 2026 and not yet approved. The values the code uses are in `jaadah/calibration/parameters.py`.

| Item | Rule |
|---|---|
| Measures | Volume and occupancy per detector per 15 minutes: RCRC site 1444 (12 stop-bar detectors) against SUMO induction loops at the mapped positions |
| Compared unit | One detector-hour: the sum of four 15-minute counts |
| Eligible | All four observed intervals reported and none imputed, and every seed has all four simulated intervals |
| Days | Only days after the late-August demand increase; the National Day week (20–26 Sep 2026) and days with more than 10% imputed intervals are left out |
| Split | Whole weeks, calibration weeks first, validation weeks later, with the same mix of workdays, Fridays and Saturdays |
| Hours | The morning and evening peak hour of each day type (workday, Friday, Saturday), taken from the calibration days |
| Pass (primary) | GEH < 5 for at least 85% of eligible detector-hours, checked separately on the calibration and the validation set |
| Reported, not pass/fail | Observed against simulated occupancy, 15-minute GEH and errors, time-series plots. Occupancy is not pass/fail because it depends on the signal plan: the real controller is actuated, the model runs one fixed plan |
| Seeds | Tuning on seed 42; acceptance on the mean simulated count of 4 seeds |
| Tuned | SUMO driver parameters `tau`, `sigma`, `minGap`, `accel`, `decel`, `speedFactor`; lane-change parameters only if lane-level counts stay off |
| Not tuned | Demand (it comes from the counts), the signal plan, the slip and bypass share assumptions |
| Stop tuning | When the target is met, or when a round improves the pass share by less than 1 percentage point; what was reached is reported either way |

```text
GEH = sqrt(2 (M - C)^2 / (M + C))     M = simulated, C = observed, vehicles per hour
C = 600, M = 660  ->  GEH = 2.39  (match)
C = 600, M = 780  ->  GEH = 6.85  (no match)
```

The 85% rule comes from FHWA, *Traffic Analysis Toolbox Volume III* (Dowling, Skabardonis and Alexiadis, FHWA-HRT-04-040, 2004), which took it from Wisconsin DOT and the UK Design Manual for Roads and Bridges. The 2019 update (FHWA-HOP-18-036) uses broader statistical criteria. The combination above is Jaadah's own protocol, not one FHWA prescribes.

**Limitations.** No travel times or queue lengths were observed, so delay and queues are checked only indirectly, through occupancy. Detector positions are modelled, not surveyed. Source time stamps are assumed to mark interval ends. The model runs a fixed signal plan where the real one is actuated. Slip and bypass demand rests on assumed shares.

## What is built

| Module | What it does |
|---|---|
| `jaadah/calibration/detectors.py` | Selects the source's detectors at a site from `network_mappings.json` and writes a SUMO additional file with one induction loop (E1) per detector, at the mapped `sumo_lane_id` and `sumo_position_m`, period 900 s. A detector without a position is an error, not a skip. |
| `jaadah/calibration/e1_output.py` | Reads the loops' output into `DetectorInterval` records: detector, interval end in Riyadh time, vehicle count (`nVehContrib`) and occupancy (%). |
| `jaadah/calibration/geh.py` | Sums four 15-minute counts into an hourly count, compares observed with the mean of the seeds' simulated counts, and computes GEH, the pass share and whether the target is met. |
| `traffic_source/rcrc_replay/config.py` | `ReplayConfig.from_environment()`: the replay offset can be set with `JAADAH_REPLAY_OFFSET_WEEKS` (see `rcrc_replay_source.md`). |

Not built yet: the runner that executes the calibration and validation days with several seeds, and the parameter tuning.

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
.\.venv\Scripts\python.exe -m pytest -q jaadah/calibration tests/test_rcrc_replay_offset.py
```

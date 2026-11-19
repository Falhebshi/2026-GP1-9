# Live Update Loop

The live update loop keeps the Current Traffic page up to date: each time the traffic source delivers a new 15-minute interval, the loop simulates it, calculates its KPIs and builds its playback, and the page shows it within a minute. It implements option A2 of Issue #48, **short runs chained through saved state**, which the team chose after the five experiments of #48.

```text
traffic source (RCRC replay, port 8002)
   │  every 15 minutes: one new interval
   ▼
simulation/live/demand.py      the new interval's demand, built once and then kept
   ▼
simulation/live/update.py      plan the chain's departures, run one SUMO segment from the last saved state
   ▼
simulation/live/publish.py     KPIs of the last two intervals, their playback, run.json
   ▼
frontend/public/data/INT_001/live/    read by the Current Traffic page
```

Commands, from the repository root, with the RCRC replay source running (see [RCRC replay source](rcrc_replay_source.md)):

```bash
python simulation/scripts/run_live.py --source rcrc          # runs until Ctrl+C
python simulation/scripts/run_live.py --source rcrc --once   # one pass, then exits
```

| Option | Meaning |
| --- | --- |
| `--source`, `--source-url` | `rcrc` (default, `http://127.0.0.1:8002`) or `synthetic` (`:8000`) |
| `--work-dir` | The chains' working files; default `simulation/outputs/live/` |
| `--out` | Where the page reads; default `frontend/public/data/<intersection>/live/` |
| `--poll` | Seconds between passes, default 10 |
| `--seed`, `--mapping`, `--net`, `--sumo-bin` | As for `run_baseline.py`; seed 42 |
| `--verbose` | Log every pass |

Both folders are ignored by git (team decision A on live outputs). The loop logs one line per update, for example `RUN_LIVE_20260819T0245_S42: interval ending 08:15 done in 16 s`.

---

## 1. Why chained runs

A digital twin's simulation must carry on from one interval to the next: the queue at 08:14 is still there at 08:15. #48 compared three ways of keeping that state, on a synthetic day with 79 updates (Experiment 5):

| Option | How | Result |
| --- | --- | --- |
| Anchored replay | Simulate the whole day again at every update | Exact, but each update takes longer than the one before |
| **A2, saved-state chain** (chosen) | Simulate 15 minutes, save SUMO's state, continue from it at the next update | Within 2.8 % of one uninterrupted run, no drift over the day; flat cost |
| A1, one long TraCI session | One SUMO process all day, cars added live | As far from the uninterrupted run as another seed (12.1 %); a crash loses the state |

A2 also leaves a saved state of "now" at every update, which Release 2's forecasts and interventions can start from.

---

## 2. One chain

A **chain** is one run of the live twin. It starts with a 15-minute warm-up and grows by one interval at every update. Each interval is simulated by one **segment**: a bounded SUMO run that loads the state the previous segment saved (`simulation/live/segments.py`).

| | |
| --- | --- |
| Second 0 | The start of the warm-up, as in every Jaadah run, so the KPI engine and the playback builder read a chain as they read a baseline run |
| Run ID | `RUN_LIVE_<second 0>_S<seed>`, e.g. `RUN_LIVE_20260819T0245_S42` |
| Daily chain | Starts at 03:00 (warm-up from 02:45), the quietest hour. A day runs from 03:00 to 03:00, so 01:00 belongs to the day before |
| Other chains | A chain started at another time (the first start, after a pause, after a long stop) begins with the **newest** interval as its warm-up, so the page shows results one interval later instead of after simulating the whole day so far |

### 2.1 Where a segment stops: the 60-second lag

The demand planner starts each vehicle earlier than the time it was counted at the stop line, by its free-flow travel time from the network edge ([SUMO demand generation](sumo_demand_generation.md)); on this network the longest is about 57 s. So some vehicles of the **next** interval must start before the newest interval ends, and their demand is not known yet.

Each segment therefore stops **60 s before** the end of its interval. The next interval's early vehicles then start on time in the next segment instead of late (#48 Experiments 3–5 found this removes every late vehicle). `check_lag` refuses to start if a network change ever makes a free-flow time 60 s or longer.

| Update when the source has delivered | Segment simulates (seconds from 02:45) | |
| --- | --- | --- |
| 03:00 (02:45–03:00) | 0 – 840 | warm-up, nothing published |
| 03:15 (03:00–03:15) | 840 – 1740 | 03:00–03:15 published, provisional |
| 03:30 (03:15–03:30) | 1740 – 2640 | 03:00–03:15 final, 03:15–03:30 provisional |

### 2.2 How SUMO saves and loads state

Checked on SUMO 1.27.1:

- The random number generators are saved with the state (`--save-state.rng`), at 8 decimals (`--save-state.precision`). Without them a reloaded run draws other random numbers than an uninterrupted one would.
- SUMO writes a state for time *t* only if the run goes on past *t*, so a segment runs one step beyond its end and saves the state at its end.
- A segment that loads a state writes the timestep (and signal state) at its begin time again. The earlier segment's copy is kept when outputs are joined (`simulation/live/outputs.py`).
- A segment inserts the departures after its begin time, up to and including its end.
- SUMO is started directly, not stepped through TraCI: a segment needs no control while it runs.

### 2.3 How close a chain is to one uninterrupted run

Checked on 19 Nov 2026 with RCRC demand (a 2-hour weekday morning, 9 segments):

- **Identical through the first reload.** After that, single vehicles start to differ by tiny amounts, because after a reload SUMO times the 3-second yellows (not a whole number of 0.4 s steps) one step differently. The signal cycle moves by one step (0.4 s) once and stays there; it does not drift further.
- **Every KPI result has the same status** (ok, unavailable, not applicable) as in the uninterrupted run. The values differ less than they do between two seeds of the uninterrupted run: about a third as much.

The exact figures are on the team's A2 page, outside the repository (PBI 8, Decision 4).

---

## 3. Demand

Each update builds the movement demand of the **newest interval only**, with the same transformation as every Jaadah run ([Traffic demand transformation](traffic_demand_transformation.md)), and adds it to the chain's demand file (`live_demand.json`). Earlier intervals are never rebuilt.

- **Built once, kept unchanged.** The intervals already simulated must keep the demand they were simulated with. Demand IDs and each record's departures depend only on the movement, the interval and the seed, so adding an interval changes nothing before it. Each update also checks this: the departures already simulated are fingerprinted, and an update whose plan would change them stops with an error instead of running.
- **History.** The 35 whole days before the interval's day, plus that day up to the interval, fetched again at every update (about a second). Whole days give every time slot the same days behind it. The history includes the chain's own day, so a gap is counted back from now (PBI 8, Decision 12).
- **Missing counts** are estimated as in every run: neighbouring detectors first, otherwise the time-slot average scaled by the hour before the gap, for up to 5 intervals. **Only the live loop** then goes on for 3 more intervals with the plain time-slot average (`fallback_gap_intervals=LIVE_FALLBACK_GAP_INTERVALS`, 8 intervals in all). After 5 intervals the hour before no longer helps, but the plain average is as accurate at the 6th interval as at the 1st, so the simulation can keep running through a typical outage. After 8 intervals (2 hours) the day's own deviation from a typical day has faded, so simulating on would only show a typical day, and the loop pauses (section 6). 8 is a project choice, not a value from a standard. Baseline and historical runs keep the gap limit of 5.
- **Estimated intervals.** An interval in which any count was estimated for a silent detector is recorded with its approaches and methods. The page shows "No sensor data" for it instead of KPIs and cars (team decision, option 3: hide estimated results on Current Traffic, keep them in the trends). The simulation still runs on the estimate, so the chain stays continuous and the intervals after the outage start from realistic queues. Allocated shared lanes and the slip and bypass shares are assumptions of every interval, not missing data, so they do not mark an interval.
- **Rejected rows** are left out and reported, as in all ingestion. Their detectors count as not reported, so they are estimated and the interval is marked.

---

## 4. KPIs and playback

After each segment, `publish.py`:

1. joins the outputs: the FCD of the **last 3 segments** (45 minutes), and the trip information and signal states of the whole chain (both small);
2. calculates the KPIs of the **previous and the newest interval**, the newest provisional, with the KPI engine's time window ([KPI engine](kpi_engine.md), section 16.5), and merges them into the day's `kpis.json` and `kpis_all.json`;
3. rebuilds the vehicle files of the same two intervals (`build_interval_payloads` in `simulation/scene_3d/build_playback.py`) and the signal file;
4. writes `run.json` last.

Why these rules:

- **45 minutes of FCD** is the two intervals reported plus one before them, so every vehicle that arrives in them is seen before it enters its measurement zone. A vehicle already inside its zone when this FCD starts entered before it, belongs to an earlier interval, and is left out (`fcd_start_s` in `collect_vehicle_passages`). With these rules the results are **identical** to calculating the whole chain at once: 1,470 of 1,470 in the 19 Nov check.
- **The previous interval is calculated again**: at the last update it was the newest, simulated only up to 60 s before its end, with vehicles still driving. Now it is complete, and its values are final.
- **The planned departures given to the KPIs end where the simulation ends.** A vehicle planned for later has not been simulated yet; it is not "never inserted".
- **The KPI engine is given the chain as a completed run.** It only calculates KPIs of a completed run, and everything it is given has been simulated to its end.
- **Every file is written under a temporary name and renamed**, and `run.json` last, so the page never reads a half-written file and `run.json` always describes files that are already there.
- **The folder holds one run.** When a new chain publishes for the first time, the previous chain's files are removed, `run.json` first, so the page never mixes two runs.

An update takes from about 5 s at night to about 60 s with heavy midday traffic (a weekday on RCRC demand, in the cloud test environment). The time follows the traffic in the last 45 minutes, not the length of the day: about half is building the vehicle playback, a quarter the KPI measurements, a tenth the SUMO segment, and the parts that grow with the day (joining the trip records, the demand files) about 3 %. The 15 minutes between intervals leave a wide margin.

---

## 5. `run.json` of a live run

The playback index of every run (`run.json` in the [3D scene guide](../simulation/scene_3d/README.md)), with `status` `running` and a `live` part:

| Field | Meaning |
| --- | --- |
| `source` | `live` |
| `status` | `running` while the loop runs (also while waiting or paused); `completed` once it has stopped |
| `live.state` | `running` (up to date, or catching up), `starting` (a new chain is warming up, and this `run.json` still describes the previous one), `waiting` (the traffic source cannot be reached, or has no data yet), `paused` (an interval cannot be built, section 6) or `stopped` (the loop was stopped) |
| `live.message` | Why, in words, for the page |
| `live.updated_at` | When the loop last reported (real time); it reports every pass, about every 10 s |
| `live.data_until` | End of the newest interval simulated (data time) |
| `live.simulated_until_s` | Where the simulation stopped, in seconds from `run_start`: `data_until` minus the lag |
| `live.lag_s`, `live.update_interval_s` | 60 and 900 |
| `live.provisional_interval_start_s` | Start of the provisional (newest) interval, in seconds from `run_start` |
| `live.estimated_intervals` | `[{start_s, end_s, approach_ids, methods}]`: intervals with estimated traffic |
| `live.problems` | Only while paused: the demand problems, at most 10 |

`kpis.json` names the provisional interval too (`provisional_interval_start`, [KPI engine](kpi_engine.md), section 16.4). The vehicle file of the warm-up interval is listed in `intervals` but not written: the page shows only the analysis period, as for every run.

---

## 6. Outages, pauses and restarts

| Situation | What the loop does | What the page shows |
| --- | --- | --- |
| A new interval has arrived | Simulates and publishes it | The newest interval, provisional; the one before, final |
| No new interval yet | Reports that it is up to date | Unchanged |
| The traffic source cannot be reached | Keeps its chain, reports `waiting` and tries again at every pass | "The traffic source cannot be reached", with the results so far and a "Not updating" badge |
| Detectors silent, up to 8 intervals | Simulates on estimated traffic and marks the intervals | "No sensor data" for those intervals; no KPIs and no cars |
| An interval cannot be built (silent for more than 2 hours, or too few earlier days of the same type to estimate from) | Pauses, and tries the newest interval at every pass | A warning with the reason; the last results stay |
| Data again after a pause | Starts a new chain with the first interval that can be built as its warm-up | "A new run has started" while it warms up; results again one interval later, from the new chain only |
| 03:00 | Starts the new day's chain | The previous day until 03:15, marked as starting; then the new day from 03:00 |
| The loop is stopped (Ctrl+C) | Writes `state: stopped` | "Live updates have stopped" |
| The loop stops without saying so (the laptop sleeps) | Nothing | After 30 minutes without a report, "Live updates are not arriving" |
| The loop starts again | Continues its chain if it is at most 8 intervals behind, catching up one interval at a time; otherwise starts a new chain at the newest data | The missed intervals appear one by one, or a new chain |

A chain cannot continue across an interval without demand, because SUMO cannot skip simulated time. So after a pause the old chain ends and a new one starts. The page then shows the day only from the restart.

An update that fails (for example SUMO crashing) changes nothing in the chain's record. The loop reports the failure and tries the same update again at the next pass; a segment folder it left behind is removed first. After 3 failures in a row, or at once when the chain itself is inconsistent (its departures would change), the loop starts a new chain at the newest data instead of retrying forever. A traffic source that cannot be reached (stopped, restarting, no network) is not a failed update: nothing was simulated, so the loop keeps its chain, reports `waiting`, and catches up when the source answers again (up to 8 intervals, as after a stop).

---

## 7. Working files and cleaning up

`simulation/outputs/live/` holds `active.json` (the chain the loop is running) and one folder per chain:

```text
RUN_LIVE_20260819T0245_S42/
  chain.json                  the chain's record: second 0, versions, its segments, its estimated intervals
  live_demand.json            the chain's demand, interval by interval
  demand/                     the SUMO demand files of the chain so far (route file, manifest, demand)
  segments/007_0430/          one segment: routes.rou.xml, segment.sumocfg, sumo.log, state.xml.gz, raw/
  update/                     the joined outputs of the last update (FCD, trip information, signal states, manifest)
```

`chain.json` is written whole, under a temporary name and then renamed, after every segment. After each update the loop deletes the FCD of segments older than the last 3, keeps the saved states of the last 4, and deletes a chain's folder 24 hours after its last update. Trip information and signal states are small and kept for the chain. A day of playback in `live/` is about 1 GB (about 10 MB per interval at peak).

---

## 8. Limitations

| Limitation | What would remove it |
| --- | --- |
| A chain is about as close to an uninterrupted run as a third of the difference between two seeds, not identical (section 2.3) | A nightly rebuild of the day with one uninterrupted run (anchored replay), if live and historical results must match exactly |
| After a pause, the page shows the day only from the restart | Keeping several chains of a day on the page (PBI 15's earlier-periods work) |
| At a site whose outages recur at the same time of the week, those time slots have few earlier values, so an outage there may not be estimable even within 8 intervals, and the loop pauses | More history, or a fallback to a related day type |
| The provisional interval's delay is biased low: the vehicles that finish first are the least delayed ([KPI engine](kpi_engine.md), section 16.5) | None needed: it becomes final at the next update |
| Saved states belong to one SUMO version, network and computer type | Start a new chain after any of these changes (the loop does when the record cannot be read) |
| One intersection, one source | A loop per intersection |

---

## 9. Tests

| Test file | Covers |
| --- | --- |
| `tests/test_live_chain.py` | Chain days, run IDs, the lag, which departures a segment inserts, the chain record, joining FCD, signal states and trip information |
| `tests/test_live_segments.py` | Segment times and command; two chained segments against one run with SUMO (same timesteps, identical up to the reload, same vehicles) |
| `tests/test_live_loop.py` | On an invented site 1444 report: the new interval's demand (whole-day history, a silent interval with its slips, the plain average after 5 intervals, nothing after 8); whole passes with SUMO: publishing, a restarted loop continuing its chain, starting again when far behind, an outage estimated, paused and restarted, the 03:00 chain |
| `jaadah/kpi_inputs/kpi_inputs_tests/test_vehicle_passages.py` | A vehicle already inside its zone when a partial FCD starts is left out; anywhere else it is still an error |

All values in tests are invented; none are copied from the RCRC report.

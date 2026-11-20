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

A **chain** is one run of the live twin. It starts with a warm-up (15 minutes at 03:00, up to 3 hours during the day) and grows by one interval at every update. Each interval is simulated by one **segment**: a bounded SUMO run that loads the state the previous segment saved (`simulation/live/segments.py`).

| | |
| --- | --- |
| Second 0 | The start of the warm-up, as in every Jaadah run, so the KPI engine and the playback builder read a chain as they read a baseline run |
| Run ID | `RUN_LIVE_<second 0>_S<seed>`, e.g. `RUN_LIVE_20260819T0245_S42` |
| Daily chain | Starts at 03:00 (warm-up from 02:45), the quietest hour. A day runs from 03:00 to 03:00, so 01:00 belongs to the day before |
| Other chains | A chain started at another time (the first start, after a pause, after a long stop) starts at the newest data instead of simulating the whole day so far. It warms up on the intervals before the newest one, as many as can be built up to 3 hours (`RESTART_WARMUP_INTERVALS`, section 2.5), and shows the newest interval at once. Just after an outage, when the intervals before cannot be built, the newest interval alone is the warm-up and results follow one interval later. A warm-up that crosses 03:00 belongs to the chain: a chain belongs to the day its results start in |

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

Checked with RCRC demand (a 2-hour weekday morning, 9 segments), first with the old 120 s signal plan on 19 Nov 2026 and again with the Webster plan on 20 Nov:

- **Identical through the first reload.** After that, single vehicles start to differ by tiny amounts, because after a reload SUMO times the 3-second yellows (not a whole number of 0.4 s steps) one step differently. The signal cycle moves by one step (0.4 s) once and stays there; it does not drift further.
- **Every KPI result has the same status** (ok, unavailable, not applicable) as in the uninterrupted run: 1,770 of 1,770. The values differ much less than they do between two seeds of the uninterrupted run:

| 90th percentile of the difference in KPI values | Old 120 s plan | Webster plan |
| --- | --- | --- |
| Chain against the uninterrupted run | 4.4 % | 0.6 % |
| Two seeds of the uninterrupted run, for scale | 13.5 % | 6.1–6.5 % |

- **The KPIs of each update** (45 minutes of FCD, section 4) are identical to those of the whole chain calculated at once: 1,470 of 1,470.

### 2.4 Step length: a chain identical to one uninterrupted run

The remaining difference comes from signal times that are not whole multiples of the 0.4 s step (the 3 s yellows, and on the Webster plan also the 27, 41 and 47 s greens): after a reload SUMO rounds them differently. Run with a 0.5 s step, which divides every time of the plan and is exact in binary, the same chain is practically identical to the uninterrupted run (Webster plan, same morning):

| Step | Timesteps that differ | Vehicles with identical trips | KPI results identical |
| --- | --- | --- | --- |
| 0.4 s (current) | 11,012 of 16,081 | 3,665 of 10,046 | 1,526 of 1,770 |
| **0.5 s** | **3 of 16,081** | **9,940 of 10,046** | **1,770 of 1,770** |
| 0.2 s | 17,483 of 40,201 | 4,832 of 10,046 | not measured |

0.2 s divides the plan on paper but is not exact in binary, so rounding returns. A 0.5 s step would also make runs a little faster. It is not adopted: the step length is part of the calibrated model (`docs/calibration.md`), so changing it needs the team's agreement and a new calibration run.

### 2.5 Warm-up of a chain started during the day

A chain that starts during the day (first start, after a pause or a long stop) starts on empty roads. Where an approach is over capacity at a peak (the West approach in the evening, under the fixed signal plan), its queue builds up over a few hours, so the warm-up must begin before that build-up. Mean delay of the vehicles departing 17:30–18:30 on a weekday (18 Aug), 4 seeds, against a run from 03:00:

| Warm-up before 17:30 | Mean delay against the run from 03:00 (4 seeds) |
| --- | --- |
| 15 minutes | 43–46 % lower |
| 60 minutes | 37–40 % lower |
| 2.5 hours | −2 to +3 %, within the spread between seeds (9.5 %) |

So such a chain warms up on up to 3 hours (`RESTART_WARMUP_INTERVALS = 12`) of the data before the newest interval. Warm-up intervals run SUMO only, so this takes a few minutes even at a peak.

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
- **Each folder holds one run, and the page shows the last 24 hours.** When a new chain publishes for the first time, the run in `live/` moves to `live/previous/` (`run.json` leaves `live/` first and arrives in `previous/` last), replacing the run that was there. After every update, the previous run's intervals that are 24 hours older than the newest interval are dropped: its `run.json` first (its analysis period then starts later), then their vehicle files, and the folder once none is left. The page joins both runs on one timeline, so it always shows the last 24 hours, across the 03:00 handover and across a restart; the scene shows one run at a time and switches when a bar of the other run is chosen. If a new run's first publish fails half way, `previous/` is kept.

An update takes from about 5 s at night to about 100 s at the evening peak (a weekday on RCRC demand with the Webster plan, on a 2-core cloud machine):

| Hour (18 Aug) | 07 | 08 | 13 | 14 | 16 | 17 | 18 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Longest update | 38 s | 50 s | 41 s | 52 s | 78 s | 87 s | 100 s |
 The time follows the traffic in the last 45 minutes, not the length of the day: about half is building the vehicle playback, a quarter the KPI measurements, a tenth the SUMO segment, and the parts that grow with the day (joining the trip records, the demand files) about 3 %. The 15 minutes between intervals leave a wide margin.

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
| `live.clock_offset_s` | How far the source's clock is behind the real clock, in seconds: 13 weeks for the replay source (its `replay_time` in `/health`), 0 for a source on real time. The page uses it for the live clock (below) |
| `live.lag_s`, `live.update_interval_s` | 60 and 900 |
| `live.provisional_interval_start_s` | Start of the provisional (newest) interval, in seconds from `run_start` |
| `live.estimated_intervals` | `[{start_s, end_s, approach_ids, methods}]`: intervals with estimated traffic |
| `live.problems` | Only while paused: the demand problems, at most 10 |

### The page's live clock

While it follows the live run, the page plays the traffic at the time it happened in data time, **20 minutes behind it**: the moment shown is the source's "now" (the real time minus `clock_offset_s`) minus 20 minutes. By then that moment has always been simulated: an interval arrives only after it ends, the loop stops 60 s early, an update takes up to about a minute, and the page looks for new files every minute. The scene is moved to that moment at every frame, so reloading the page, a second tab or another laptop all show the same moment, and a tab left in the background is right again when it comes back. A new interval is published a few minutes before the clock reaches it, so the playback runs on without a jump. If the simulation has not reached the moment yet (the loop is late or stopped), the scene waits at the end of what has been simulated; a new chain is shown from its start until the clock catches up. The time on the page is the time of the traffic; the "Live" badge explains the delay in its tooltip. Clicking an earlier interval replays it; clicking the newest interval follows the clock again.

`kpis.json` names the provisional interval too (`provisional_interval_start`, [KPI engine](kpi_engine.md), section 16.4). The vehicle files of the warm-up intervals are listed in `intervals` but not written: the page shows only the analysis period, as for every run.

---

## 6. Outages, pauses and restarts

| Situation | What the loop does | What the page shows |
| --- | --- | --- |
| A new interval has arrived | Simulates and publishes it | The newest interval, provisional; the one before, final |
| No new interval yet | Reports that it is up to date | Unchanged |
| The traffic source cannot be reached | Keeps its chain, reports `waiting` and tries again at every pass | "The traffic source cannot be reached", with the results so far and a "Not updating" badge |
| Detectors silent, up to 8 intervals | Simulates on estimated traffic and marks the intervals | "No sensor data" for those intervals; no KPIs and no cars |
| An interval cannot be built (silent for more than 2 hours, or too few earlier days of the same type to estimate from) | Pauses, and tries the newest interval at every pass | A warning with the reason; the last results stay |
| Data again after a pause | Starts a new chain at the first interval that can be built; the silent hour before cannot be built, so that interval is its warm-up | "A new run has started" while it warms up; results again one interval later, from the new chain only |
| 03:00 | Starts the new day's chain | The previous day until 03:15, marked as starting; then the new day from 03:00, with the previous day still on the timeline until it is 24 hours old |
| The loop is stopped (Ctrl+C) | Writes `state: stopped` | "Live updates have stopped" |
| The loop stops without saying so (the laptop sleeps) | Nothing | After 30 minutes without a report, "Live updates are not arriving" |
| The loop starts again | Continues its chain if it is at most 8 intervals behind, catching up one interval at a time; otherwise starts a new chain at the newest data, warmed up on the 3 hours before | The missed intervals appear one by one, or the new chain's newest interval at once |

A chain cannot continue across an interval without demand, because SUMO cannot skip simulated time. So after a pause the old chain ends and a new one starts. The old chain moves to `live/previous/`, so the page still shows it on the timeline, with a gap where the loop was paused.

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

`chain.json` is written whole, under a temporary name and then renamed, after every segment. After each update the loop deletes the FCD of segments older than the last 3, keeps the saved states of the last 4, and deletes a chain's folder 24 hours after its last update. Trip information and signal states are small and kept for the chain. A day of playback in `live/` and `live/previous/` together is about 2 GB (the fast run below reached 1.9 GB for a weekday).

---

## 8. Limitations

| Limitation | What would remove it |
| --- | --- |
| A chain started during the day matches the day's chain only if its 3-hour warm-up began before a peak's queue started to build (section 2.5); a restart late in a longer over-capacity period, or just after an outage (when the hours before cannot be built), shows less delay | Keep the loop running from 03:00, so the day runs as one chain; an actuated signal plan (issue #70) would keep the queues from building up |
| A chain is very close to an uninterrupted run (about a tenth of the difference between two seeds), but not identical (section 2.3) | A nightly rebuild of the day with one uninterrupted run (anchored replay), if live and historical results must match exactly |
| The page keeps only the run before the newest one: after two restarts in 24 hours, the oldest of the three runs leaves the timeline early | Earlier periods from the history (PBI 15) |
| At a site whose outages recur at the same time of the week, those time slots have few earlier values, so an outage there may not be estimable even within 8 intervals, and the loop pauses | More history, or a fallback to a related day type |
| The provisional interval's delay is biased low: the vehicles that finish first are the least delayed ([KPI engine](kpi_engine.md), section 16.5) | None needed: it becomes final at the next update |
| Saved states belong to one SUMO version, network and computer type | Start a new chain after any of these changes (the loop does when the record cannot be read) |
| One intersection, one source | A loop per intersection |

---

## 9. Tests

**A day in an hour.** `simulation/scripts/tests/run_live_fast.py` runs the loop through a stretch of the replay's report as fast as it can go: it gives the loop the intervals back to back instead of every 15 minutes, with the loop's clock set to the data time. A whole day, with its peaks, the 03:00 handover and the cleaning up, takes about as long as its updates, around an hour. After every update it prints how long the update took, the disk use of the working and page folders, and the memory used, and it writes them to `simulation/outputs/tests/live_fast/report.csv` (ignored by git). It checks what a day-long run would show about the loop, but not the parts that depend on real time: waiting for the source, the page's clock, and removing a chain's working folder 24 hours after its last update (that rule reads the files' real times).

```bash
python simulation/scripts/tests/run_live_fast.py --first 2026-08-18T02:45 --last 2026-08-19T03:30
```

| Test file | Covers |
| --- | --- |
| `tests/test_live_chain.py` | Chain days, run IDs, the lag, which departures a segment inserts, the chain record, joining FCD, signal states and trip information |
| `tests/test_live_segments.py` | Segment times and command; two chained segments against one run with SUMO (same timesteps, identical up to the reload, same vehicles) |
| `tests/test_live_loop.py` | On an invented site 1444 report: the new interval's demand (whole-day history, a silent interval with its slips, the plain average after 5 intervals, nothing after 8); whole passes with SUMO: publishing, a restarted loop continuing its chain, starting again when far behind, an outage estimated, paused and restarted, the 03:00 chain |
| `jaadah/kpi_inputs/kpi_inputs_tests/test_vehicle_passages.py` | A vehicle already inside its zone when a partial FCD starts is left out; anywhere else it is still an error |

All values in tests are invented; none are copied from the RCRC report.

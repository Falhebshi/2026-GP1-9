# Jaadah KPI Engine

## Overview

The KPI engine calculates Jaadah's traffic performance indicators (control delay, level of service, volume-to-capacity ratio, capacity, saturation flow, queue length, queue duration, queue storage ratio and throughput) for the case-study intersection of Prince Turki Al-Awwal Road and Imam Saud Road.

It works on the canonical models described in `data_models.md`: its inputs are standardized simulation outputs and network models, and its output is a list of `KpiResult` records.

Three rules shape the engine:

> **1. Pure calculation.** Every engine function takes canonical models and numbers as input and returns numbers or `KpiResult` records. The engine does not read files, run SUMO or access the database; the simulation pipeline prepares its inputs and the backend stores and serves its outputs. Every function can therefore be tested with values worked out by hand.

> **2. One place for every constant.** Values taken from the Highway Capacity Manual (HCM) 6th edition or chosen for Jaadah are defined once, in `parameters.py`. No other file writes these numbers directly.

> **3. Missing values are never zero.** When a KPI cannot be calculated, its result has status `unavailable` or `not_applicable` and a reason, never a value of 0.

---

## Package Structure

The engine is implemented under:

```text
backend/
├── __init__.py
└── analytics/
    ├── __init__.py
    └── kpi/
        ├── __init__.py
        ├── parameters.py   constants and the level-of-service function
        ├── intervals.py    the 15-minute analysis intervals
        ├── throughput.py   vehicles served per movement
        ├── queue.py        queue length and queue storage ratio per lane
        └── kpi_tests/
            ├── __init__.py
            ├── test_parameters.py
            ├── test_intervals.py
            ├── test_throughput.py
            └── test_queue.py
```

Each engine file's tests are kept with the engine, in `backend/analytics/kpi/kpi_tests/`.

---

# 1. Scope of the Analysis

## 1.1 Analysis intervals

KPIs are calculated per **15-minute interval**, the HCM analysis period.

Each simulation run has three parts, each occurring once: a **warm-up** at the start, while the network fills with vehicles; the **analysis period**; and a **clearance** at the end, which lets vehicles already in the network finish their passage. The 15-minute intervals lie back to back inside the analysis period; nothing is reported for the warm-up or the clearance (see section 4).

```text
| warm-up |  08:00–08:15 | 08:15–08:30 | 08:30–08:45 | 08:45–09:00 | clearance |
          |<------------------ analysis period ------------------>|
```

## 1.2 Movements analysed

The analysis covers the movements at the case-study intersection's stop lines that have `MovementAttributes`: East through and left, West through and left, North left and South through, plus the right-turn slip roads South→East, West→South and North→West.

Right-turn slip roads are unsignalised. They receive simulation delay, queue length, queue duration, queue storage ratio and throughput. Level of service, volume-to-capacity ratio and capacity are reported as `not_applicable`, because these are signalised-intersection measures.

## 1.3 Measurement zones

Each approach has its own measurement zone, measured from the stop line:

| Approach | Upstream | Downstream | Speed limit |
| --- | --- | --- | --- |
| East | 0–388 m | ≈155 m | 90 km/h |
| West | 0–450 m | ≈105 m | 70 km/h |
| North | 0–500 m | ≈65 m | 50 km/h |
| South | 0–500 m | ≈65 m | 50 km/h |

The lane-area (E2) detectors used for queue measurement have the same lengths as the upstream zones.

Lane numbers in Jaadah count from the median (`ApproachLane.lane_index` 1 is the lane next to the median). Field references that count from the kerb are converted before use.

---

# 2. Reporting Rules

## 2.1 Shared lanes

Some KPIs are measured per vehicle and split cleanly by movement (simulation delay, simulation-based level of service, queue duration, throughput). Others are measured per lane (queue length, queue storage ratio) or per lane group (HCM saturation flow, capacity, volume-to-capacity ratio, HCM delay and level of service) and cannot be divided between the movements of a shared lane.

These lane and lane-group KPIs are reported on the lane or lane group where they were measured. Each movement that uses a shared lane also shows that value, marked with `measured_on_lane_id` or `measured_on_lane_group_id`; the dashboard displays it with a "Shared lane" tag.

## 2.2 Lane groups

Lane groups follow HCM 6th edition: adjacent lanes serving the same movements form one group, and a shared lane is always its own group. Lane groups are derived from the `ApproachLane` records each time they are needed, rather than stored, and receive stable identifiers such as `east_L`, `east_LT` and `east_T`.

## 2.3 Queue duration

Queue duration is measured per vehicle (the time it stood still inside the zone, `VehicleDelayRecord.halted_time_s`), so it is reported per movement like delay.

## 2.4 Roll-up

Results are combined from lane and movement level up to approach and intersection level. An approach's queue length is the longest of its lanes; an approach's volume-to-capacity ratio is that of its critical (highest) lane group.

---

# 3. Parameters and Level of Service

Implemented in `backend/analytics/kpi/parameters.py`.

## 3.1 Base saturation flow

The base saturation flow s₀ is **1,900 passenger cars per hour per lane**.

This is the HCM 6th edition value for metropolitan areas with a population of 250,000 or more (1,750 pc/h/ln applies to smaller areas); Riyadh is far above this limit. It is the starting point of the HCM saturation-flow calculation (s = s₀ × N × adjustment factors) and can later be compared with the saturation flow measured in SUMO on single-movement lanes.

## 3.2 Level-of-service thresholds

Level of service is assigned from control delay (seconds per vehicle), using the HCM 6th edition thresholds for signalized intersections:

| LOS | Control delay (s/veh) |
| --- | --- |
| A | ≤ 10 |
| B | > 10 and ≤ 20 |
| C | > 20 and ≤ 35 |
| D | > 35 and ≤ 55 |
| E | > 55 and ≤ 80 |
| F | > 80 |

A delay exactly on a threshold receives the better grade (for example, 10.0 s/veh is LOS A).

## 3.3 Volume-to-capacity override

When a lane group's volume-to-capacity ratio is greater than 1.0, its level of service is F regardless of its delay, because demand exceeds what the lane group can serve.

The override applies only at **lane-group and movement level**. Approach and intersection level of service are determined by control delay alone, as defined in HCM 6th edition (Exhibit 19-8).

---

# 4. Analysis Intervals

Implemented in `backend/analytics/kpi/intervals.py`.

## 4.1 Where the intervals come from

The analysis period is taken from the scenario: `Scenario.start_time` and `Scenario.end_time` are the start and end of the analysis period, the time window shown to the user (for example, an AM peak of 08:00–09:00). The warm-up runs before `start_time` and the clearance after `end_time`.

Every KPI file receives the same list of intervals from this module instead of building its own, so all KPIs of a run are reported over exactly the same intervals.

## 4.2 Interval boundaries

An interval includes its start time and excludes its end time. An event at exactly 08:15:00 belongs to 08:15–08:30, never to 08:00–08:15, so no event is counted in two intervals.

## 4.3 Whole intervals only

The analysis period must be a whole number of 15-minute intervals. If it is not (for example, 50 minutes), an error is raised: the leftover is neither dropped silently nor reported as a shorter interval, because a KPI over 5 minutes is not comparable with KPIs over 15 minutes.

---

# 5. Throughput

Implemented in `backend/analytics/kpi/throughput.py`.

Throughput is the number of vehicles a movement served in an interval, reported in vehicles per hour (a count over a 15-minute interval × 4). It is calculated per movement for each run; approach and intersection throughput are the sums of their movements (section 2.4), and the mean and standard deviation across seeds are calculated in the same way as for every other KPI.

## 5.1 When a vehicle is counted

A vehicle is counted in the interval that contains its **stop-line crossing** (`stop_line_time`), the moment the signal serves it. Counting by zone entry would measure arrivals (demand) rather than service, and counting by zone exit would depend on the length of the downstream zone, which differs by approach.

A vehicle that arrived during the warm-up but crosses the stop line inside the analysis period is counted; a vehicle that crosses during the clearance is not counted in any interval.

## 5.2 Vehicles still in the zone when the run ends

A vehicle that crossed the stop line but had not left the zone when the run ended has an `IncompletePassage` record with a `stop_line_time` and no `VehicleDelayRecord`. It is counted: it was served, and leaving it out would undercount the last interval.

## 5.3 Intervals with no vehicles

When a run covered an interval and no vehicle of a movement crossed the stop line, throughput is reported as **0 veh/h** with status `ok`. This is a measured zero, not a missing value.

## 5.4 Input checks

An error is raised when a record belongs to a different run, uses a movement that is not analysed, or when the same vehicle appears more than once. These indicate a problem in the simulation output and are never silently ignored.

---

# 6. Queue Length and Queue Storage Ratio

Implemented in `backend/analytics/kpi/queue.py`.

## 6.1 Source

Queue length is measured per lane by lane-area (E2) detectors whose output period is one signal cycle, aligned with the cycle start. Each `CycleQueueRecord` therefore gives the longest queue on one lane in one cycle, in metres and in vehicles. Queue length is reported **in both units**, as two results: metres are used for the storage ratio, and vehicles are easier to read on the dashboard.

Queue length is a lane KPI. Shared lanes are reported as described in section 2.1, and an approach's queue is its longest lane (section 2.4). Queue duration is measured per vehicle and is calculated with delay (section 2.3).

## 6.2 Cycles that span an interval boundary

With a 120 s cycle, a 15-minute interval holds 7.5 cycles, so every second interval boundary falls inside a cycle. A cycle belongs to the interval that **contains its `cycle_start`**, giving 7 or 8 cycles per interval. A cycle that starts during the warm-up or clearance is not used, even if it ends inside the analysis period.

## 6.3 Queue per interval

For each lane and interval, the reported queue is the **largest cycle queue** in that interval. Metres and vehicles are each the largest value of the interval's cycles.

## 6.4 95th-percentile queue over the analysis period

For the analysis page, each lane also receives the **95th-percentile cycle queue** over all cycles of the analysis period, calculated with the **nearest-rank method**: the cycle queues are sorted and the value at rank ⌈0.95 × n⌉ is taken. For example, with 20 cycles the 19th smallest queue is reported.

The HCM 6th edition calculates its percentile back of queue analytically and does not prescribe a method for taking a percentile from measured cycles. The nearest-rank method was chosen because the result is always a queue that actually occurred, in whole vehicles, and is simple to explain and to check by hand.

## 6.5 Queue storage ratio

The queue storage ratio is a queue divided by the lane's storage length (`ApproachLane.storage_length_m`). A ratio above 1 means the queue was longer than the storage available, so it spilled back. It is reported:

- **per interval**: the interval's largest cycle queue ÷ storage length;
- **over the analysis period**: the 95th-percentile queue ÷ storage length.

When the storage length of a lane is not known, the queue length is still reported and only the storage ratio is `unavailable`, with the reason "storage length not known".

## 6.6 Missing records are not zero queues

A detector reports every cycle, including cycles with no queue, which are recorded as 0 m. A reported 0 m is a measured zero and is reported as `ok` with a value of 0. When a lane has **no** cycle record in an interval, its data is missing, and its queue is `unavailable` with the reason "no cycle records for this lane in this interval"; it is never reported as 0.

## 6.7 Input checks

An error is raised when a record belongs to a different run, to a lane that is not analysed, or when a lane has two records for the same cycle.
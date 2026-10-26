# Jaadah KPI Engine

## Overview

The KPI engine calculates Jaadah's traffic performance indicators (control delay, level of service, volume-to-capacity ratio, capacity, saturation flow, queue length, queue duration, queue storage ratio and throughput) for the case-study intersection of Prince Turki Al-Awwal Road and Imam Saud Road.

It works on the canonical models described in `data_models.md`: its inputs are standardized simulation outputs and network models, and its outputs are `KpiResult` and `KpiComparison` records.

Three rules shape the engine:

> **1. Pure calculation.** Every engine function takes canonical models and numbers as input and returns numbers or `KpiResult` records. The engine does not read files, run SUMO or access the database; the simulation pipeline prepares its inputs and the backend stores and serves its outputs. Every function can therefore be tested with values worked out by hand.

> **2. One place for every constant.** Values taken from the Highway Capacity Manual (HCM) 7th edition or chosen for Jaadah are defined once, in `parameters.py`. No other file writes these numbers directly.

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
        ├── delay.py        control delay and queue duration per movement
        ├── lane_groups.py  HCM lane groups derived from the approach lanes
        ├── capacity.py     HCM saturation flow, capacity, v/c and critical v/c
        ├── hcm_delay.py    HCM control delay and level of service
        ├── rollup.py       approach and intersection values
        ├── comparison.py   combining runs and comparing scenarios
        └── kpi_tests/
            ├── __init__.py
            ├── test_parameters.py
            ├── test_intervals.py
            ├── test_throughput.py
            ├── test_queue.py
            ├── test_delay.py
            ├── test_lane_groups.py
            ├── test_capacity.py
            ├── test_hcm_delay.py
            ├── test_rollup.py
            ├── test_comparison.py
            └── test_study_area_inputs.py
```

Each engine file's tests are kept with the engine, in `backend/analytics/kpi/kpi_tests/`. `test_study_area_inputs.py` runs the engine on the study area's real network inputs and signal program, prepared by `jaadah/kpi_inputs/` ([KPI measurements](kpi_measurements.md)).

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

The analysis covers the movements at the case-study intersection's stop lines that have `MovementAttributes`: East through and left, West through and left, North left and South left (`MOV_S_W`), plus the right-turn slip roads South→East, West→South and North→West. `MOV_S_W` is classified as a protected left turn: vehicles make a gentle left, although SUMO labels the connection straight (`dir="s"`) because of the skewed geometry (section 13.3).

Right-turn slip roads are unsignalised. They receive simulation delay, queue length, queue duration, queue storage ratio and throughput. Level of service, volume-to-capacity ratio and capacity are reported as `not_applicable`, because these are signalised-intersection measures.

## 1.3 Measurement zones

Each approach has its own measurement zone, measured from the stop line:

| Approach | Upstream | Downstream | Speed limit |
| --- | --- | --- | --- |
| East | 0–388 m | ≈155 m | 90 km/h |
| West | 0–450 m | ≈105 m | 70 km/h |
| North | 0–500 m | ≈65 m | 50 km/h |
| South | 0–500 m | ≈65 m | 50 km/h |

Delay is measured per vehicle over the whole zone. Per-lane queues are measured over each lane's own section (its lane chain), and the full queue of an approach over the whole upstream zone (section 13.1).

Lane numbers in Jaadah count from the median (`ApproachLane.lane_index` 1 is the lane next to the median). Field references that count from the kerb are converted before use.

---

# 2. Reporting Rules

## 2.1 Shared lanes

Some KPIs are measured per vehicle and split cleanly by movement (simulation delay, simulation-based level of service, queue duration, throughput). Others are measured per lane (queue length, queue storage ratio) or per lane group (HCM saturation flow, capacity, volume-to-capacity ratio, HCM delay and level of service) and cannot be divided between the movements of a shared lane.

These lane and lane-group KPIs are reported on the lane or lane group where they were measured. Each movement that uses a shared lane also shows that value, marked with `measured_on_lane_id` or `measured_on_lane_group_id`; the dashboard displays it with a "Shared lane" tag.

## 2.2 Lane groups

Lane groups follow HCM 7th edition (Chapter 19, page 19-43): adjacent lanes serving the same movements form one group, and a shared lane is always its own group. Lane groups are derived from the `ApproachLane` records each time they are needed, rather than stored, and receive stable identifiers such as `APP_E_L`, `APP_E_LT` and `APP_E_T` (section 8.2).

## 2.3 Queue duration

Queue duration is measured per vehicle (the time it stood still inside the zone, `VehicleDelayRecord.halted_time_s`), so it is reported per movement like delay.

## 2.4 Roll-up

Results are combined from lane and movement level up to approach and intersection level: delays are averaged, counts and capacities are added, and volume-to-capacity ratios, queue lengths and storage ratios take the worst value. The full rules are in section 11.

---

# 3. Parameters and Level of Service

Implemented in `backend/analytics/kpi/parameters.py`.

## 3.1 Base saturation flow

The base saturation flow s₀ is **1,900 passenger cars per hour per lane**.

This is the HCM 7th edition value (Exhibit 19-11) for metropolitan areas with a population of 250,000 or more (1,750 pc/h/ln applies to smaller areas); Riyadh is far above this limit. It is the starting point of the HCM saturation-flow calculation (s = s₀ × N × adjustment factors) and can later be compared with the saturation flow measured in SUMO on single-movement lanes.

## 3.2 Level-of-service thresholds

Level of service is assigned from control delay (seconds per vehicle), using the HCM 7th edition thresholds for signalized intersections (Exhibit 19-8):

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

The override applies only at **lane-group and movement level**. Approach and intersection level of service are determined by control delay alone, as defined in the note to Exhibit 19-8 of the HCM 7th edition: "for approach-based and intersectionwide assessments, LOS is defined solely by control delay".

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

Queue length is measured per lane and signal cycle, aligned with the cycle start, from vehicle positions over the lane's section ([KPI measurements](kpi_measurements.md), section 5). Each `CycleQueueRecord` therefore gives the longest queue on one lane in one cycle, in metres and in vehicles. Queue length is reported **in both units**, as two results: metres are used for the storage ratio, and vehicles are easier to read on the dashboard.

Queue length is a lane KPI. Shared lanes are reported as described in section 2.1, and an approach's queue is its longest lane (section 2.4). Queue duration is measured per vehicle and is calculated with delay (section 2.3).

## 6.2 Cycles that span an interval boundary

With a 120 s cycle, a 15-minute interval holds 7.5 cycles, so every second interval boundary falls inside a cycle. A cycle belongs to the interval that **contains its `cycle_start`**, giving 7 or 8 cycles per interval. A cycle that starts during the warm-up or clearance is not used, even if it ends inside the analysis period.

## 6.3 Queue per interval

For each lane and interval, the reported queue is the **largest cycle queue** in that interval. Metres and vehicles are each the largest value of the interval's cycles.

## 6.4 95th-percentile queue over the analysis period

For the analysis page, each lane also receives the **95th-percentile cycle queue** over all cycles of the analysis period, calculated with the **nearest-rank method**: the cycle queues are sorted and the value at rank ⌈0.95 × n⌉ is taken. For example, with 20 cycles the 19th smallest queue is reported.

A record is written for every lane and cycle, even when there is no queue (then the queue is 0), so an interval without records is missing data. If any interval of the period has no records for a lane, that lane's period value is `unavailable` ("no cycle records in at least one interval of the analysis period"): the percentile of the remaining intervals would look like a whole-period value while missing part of the time, possibly the peak. Its approach, movements and the intersection follow through the roll-up (section 11.4).

The HCM 7th edition calculates its percentile back of queue analytically and does not prescribe a method for taking a percentile from measured cycles. The nearest-rank method was chosen because the result is always a queue that actually occurred, in whole vehicles, and is simple to explain and to check by hand.

## 6.5 Queue storage ratio

The queue storage ratio is a queue divided by the lane's storage length (`ApproachLane.storage_length_m`). A ratio above 1 means the queue was longer than the storage available, so it spilled back. It is reported:

- **per interval**: the interval's largest cycle queue ÷ storage length;
- **over the analysis period**: the 95th-percentile queue ÷ storage length.

When the storage length of a lane is not known, the queue length is still reported and only the storage ratio is `unavailable`, with the reason "storage length not known".

## 6.6 Missing records are not zero queues

A record is written for every cycle, including cycles with no queue, which are recorded as 0 m. A reported 0 m is a measured zero and is reported as `ok` with a value of 0. When a lane has **no** cycle record in an interval, its data is missing, and its queue is `unavailable` with the reason "no cycle records for this lane in this interval"; it is never reported as 0.

## 6.7 Input checks

An error is raised when a record belongs to a different run, to a lane that is not analysed, or when a lane has two records for the same cycle.

---

# 7. Control Delay and Queue Duration

Implemented in `backend/analytics/kpi/delay.py`.

## 7.1 Source

Each `VehicleDelayRecord` describes one vehicle's passage through the measurement zone of its approach (section 1.3). The simulation pipeline provides its zone times, its free-flow travel time and the time it stood still; the record calculates its **time loss** (time in the zone − free-flow travel time). How the zone end and the free-flow speed are defined is decided in the simulation pipeline; the engine uses the finished time loss and does not depend on that definition.

For each movement and interval:

- **control delay** (s/veh) is the mean time loss of the vehicles that arrived in the interval;
- **queue duration** (s) is the mean time stopped (`halted_time_s`) of the same vehicles.

Approach and intersection values are vehicle-weighted means of their movements (section 2.4).

## 7.2 Which interval a vehicle's delay belongs to

A vehicle's delay belongs to the interval that contains its **zone entry** (its arrival). This is how the HCM assigns delay, to the demand that arrived in the period, and it matches the rule that vehicles are counted when they enter the zone during the analysis period. A vehicle arriving at 08:14:50 and served at 08:16 has its delay in 08:00–08:15.

This differs on purpose from throughput, which counts a vehicle when it is served (section 5.1). Vehicles that arrive during the warm-up or clearance are not counted.

## 7.3 Queue duration is averaged over all vehicles

Vehicles that did not stop count with 0 s. The value therefore answers "how long does a vehicle on this movement stand still, on average?" and is labelled "average time stopped per vehicle".

Averaging only over vehicles that stopped was not chosen: if an intervention let more vehicles through without stopping, that average could rise although traffic improved, which would make baseline and intervention comparisons misleading.

## 7.4 Vehicles that had not finished when the run ended

A vehicle that entered the zone but was still in it when the run ended has an `IncompletePassage` record and no time loss. Its delay is unknown and probably large. When any vehicle that arrived in an interval is incomplete, that interval's control delay and queue duration for the movement are `unavailable`, with the reason "N vehicle(s) had not finished their passage when the run ended; increase the clearance duration".

Reporting the mean of the completed vehicles instead would understate the delay of exactly the most congested intervals. With a sufficient clearance duration (`SimulationConfig.clearance_duration_s`) no vehicle is left unfinished.

## 7.5 Intervals with no arrivals

When no vehicle of a movement arrived in an interval, a mean delay does not exist. Control delay and queue duration are `not_applicable`, with the reason "no vehicles arrived in this interval". They are not reported as 0, which would mean that vehicles passed without delay. This differs from throughput, where an interval without vehicles is a measured 0 veh/h (section 5.3).

## 7.6 Level of service

Simulation-based level of service is graded from the control delay with the thresholds of section 3.2. Simulation provides no volume-to-capacity ratio, so the grade comes from delay alone. It is graded from the **mean delay across seeds**, after the runs are combined, not from each run separately.

## 7.7 Input checks

An error is raised when a record belongs to a different run, uses a movement that is not analysed, or when the same vehicle appears more than once in the completed and incomplete records together.

---

# 8. Lane Groups

Implemented in `backend/analytics/kpi/lane_groups.py`.

## 8.1 How lane groups are formed

Lane groups follow HCM 7th edition (section 2.2; Chapter 19, page 19-43, Exhibit 19-19). On each approach, the lanes are taken in order from the median outwards (`ApproachLane.lane_index`):

- adjacent lanes that serve exactly the same single movement form one lane group (for example, three through lanes);
- a lane shared by several movements is always its own lane group.

Lane groups are derived from the `ApproachLane` records each time they are needed and are not stored.

| East lanes (from the median) | Serve | Lane group |
| --- | --- | --- |
| 1 | left | `APP_E_L` |
| 2 | left + through (shared) | `APP_E_LT` |
| 3, 4 | through | `APP_E_T` (2 lanes) |

## 8.2 Lane group identifiers

A lane group's ID is its approach's ID, an underscore, and the letters of the movements it serves (**L** left, **T** through, **R** right), always in the order L, T, R; the movement types come from `MovementAttributes`. The ID depends only on which movements the group serves, not on lane numbers, so it stays the same if a lane is added, and it can never disagree with the approach ID.

## 8.3 Uncontrolled lanes

Lanes whose movements are uncontrolled (the right-turn slip lanes) belong to **no lane group**: capacity, volume-to-capacity ratio and HCM level of service do not apply to them (section 1.2). Their lane-level KPIs (queue length, storage ratio) do not need lane groups.

## 8.4 Input checks

An error is raised, naming the lane or approach, when:

- a lane serves a movement that has no `MovementAttributes`;
- a lane serves both signalized and uncontrolled movements (a slip lane only serves its right turn, so this indicates wrong lane data);
- two lanes of an approach have the same `lane_index`;
- two lane groups of an approach would get the same ID (an unusual layout such as through, left, through).

---

# 9. Saturation Flow, Capacity and Volume-to-Capacity Ratio

Implemented in `backend/analytics/kpi/capacity.py`.

These KPIs are **calculated with the HCM method**, independently of the simulation: they describe how many vehicles each lane group could serve with the given lanes and signal timing, and how that compares with the demand. Saturation flow measured in SUMO is used only as a calibration check.

All HCM values in this section were checked against the **HCM 7th edition, Chapter 19 (Signalized Intersections)**; the exhibit or equation is given for each.

## 9.1 Steps

For each lane group (section 8) and interval:

1. **Saturation flow:** s = N × s₀ × f_w × f_HVg × f_p × f_bb × f_a × f_LU × f_LT × f_Lpb × f_Rpb × f_wz × f_ms × f_sp × f_CAV (veh/h): N times the adjusted saturation flow per lane of Equation 19-8, with s₀ = 1,900 pc/h/ln (section 3.1) and N the number of lanes in the group.
2. **Capacity:** c = s × g / C (Equation 19-16), with g the effective green of the group and C the cycle length, both from the scenario's `SignalProgram`. Effective green g = G + Y + Rc − l₁ − l₂ (Equation 19-3), with start-up lost time l₁ = 2.0 s, clearance lost time l₂ = Y + Rc − e and extension of effective green e = 2.0 s; so g = G − l₁ + e, which equals the displayed green G.
3. **Volume-to-capacity ratio:** X = v / c (Equation 19-17), with v the demand flow assigned to the group (section 9.4).
4. **Critical volume-to-capacity ratio of the intersection:** Xc = Σ(v/s)crit × C / (C − L) (Equation 19-30), where (v/s)crit is the highest flow ratio among the lane groups served in each phase and L is the total lost time of the critical phases, each phase losing l₁ + l₂ (5 s with 3 s yellow and 2 s all-red). Jaadah's phases run in sequence, so every phase is critical.

## 9.2 Adjustment factors

| Factor | Value | Reason |
| --- | --- | --- |
| Lane width f_w | 0.96 below 3.05 m (10.0 ft); 1.00 from 3.05 m to 3.93 m (12.9 ft); 1.04 above 3.93 m | Exhibit 19-20, applied to the **average width** of the group's lanes (`ApproachLane.lane_width_m`). The factor may not be used for an average width below 2.44 m (8.0 ft); such a lane group raises an error |
| Heavy vehicles and grade f_HVg | 1.0 | Equations 19-9 and 19-10 give 1.0 for 0 % heavy vehicles and 0 % grade. Jaadah simulates passenger cars only (`VehicleType` = `car`), and the HCM side must assume the same traffic as the simulation (see 9.9); no grade data, so 0 % is assumed |
| Parking f_p | 1.0 | 1.00 when no parking is present (page 19-46); no on-street parking at the stop lines |
| Bus blockage f_bb | 1.0 | Equation 19-12 applies only when stopping buses block the lane group; buses are outside Jaadah's scope |
| Area type f_a | 1.0 | 0.90 is used only where geometry and traffic or pedestrian flows significantly increase headways, as in CBDs (page 19-47); not the case here |
| Lane utilisation f_LU | exclusive through: 1.000 / 0.952 / 0.908 for 1 / 2 / 3 lanes; exclusive left: 1.000 / 0.971 for 1 / 2 lanes; exclusive right: 1.000 / 0.885 for 1 / 2 lanes | Exhibit 19-15 default values. For more lanes than listed, the smallest value of the same type is used (note to Exhibit 19-15), so the North approach's three exclusive left-turn lanes use 0.971. A lane group with one lane, exclusive or shared, has 1.0 |
| Left turns f_LT | 1 / (1 + P_LT × (E_L − 1)), E_L = 1.05 | Equation 19-14 gives f_LT = 1 / E_L = 0.952 for an exclusive protected left-turn lane. For the shared lane, P_LT is the share of left-turning vehicles in the group; see 9.4 for how this relates to the HCM shared-lane procedure (Chapter 31). Protected left turns only (9.3) |
| Pedestrians and bicycles f_Lpb, f_Rpb | 1.0 | 1.0 when no pedestrians or bicycles are present (page 19-48); few pedestrians cross these approaches |
| Work zone f_wz, downstream lane blockage f_ms, sustained spillback f_sp | 1.0 | each is 1.0 when the condition is absent (page 19-49) |
| Connected and automated vehicles f_CAV | 1.0 | HCM 7th edition adjustment (Chapter 31); the simulation contains no such vehicles |

Signalized right turns are not in the analysis (right turns use uncontrolled slip lanes), so no right-turn factor is applied. Every factor that is not calculated from Jaadah data is labelled *modelled assumption* in `input_origins`.

## 9.3 Left-turn phasing

A left turn is treated as **protected** when no phase that serves it also serves a through movement of another approach (the opposing traffic it would have to cross); this is read from `SignalPhase.served_movement_ids` and `Movement.approach_id`. Protected left turns use the left-turn factor above.

**Permitted** left turns (served together with opposing traffic, turning through gaps) are not supported: the capacity, volume-to-capacity ratio and HCM delay of their lane groups are `unavailable`, with the reason "permitted left turns are not supported".

## 9.4 Distributing a movement's demand over its lane groups

`SimulationDemand` gives demand per movement, but a movement can use more than one lane group (for example, East-left uses `APP_E_L` and the shared `APP_E_LT`). The demand is distributed with the HCM procedure for lane group flow rates on approaches with shared lanes (HCM 7th edition, Chapter 31, Section 2, "Lane Group Flow Rate on Multiple-Lane Approaches", Steps A to H, pages 31-23 to 31-30). It is based on the principle that drivers "choose the lane that minimizes their service time at the intersection, where the lane volume-to-saturation flow ratio is used to estimate relative differences in this time among lanes" (Chapter 19, page 19-44): the flow ratios v/s of the lanes are equalized (Equation 31-46).

The calculation, per approach and interval:

1. **Modified left-turn equivalent (Step A).** The average flow per lane that can serve through traffic is v_app = (sum of the approach's demand) / (number of shared and exclusive through lanes) (Equation 31-51). The probability of a lane change is P_lc = 1 − (2 v_app / s_lc − 1)², at least 0, with s_lc = 3,600 / 3.7 s = 973 veh/h/ln (Equation 31-50). The left-turn equivalent used in shared lanes is E_L,m = (E_L − 1) × P_lc + 1 (Equation 31-47). HCM introduced this because pure equalization overestimates the effect of turning vehicles in shared lanes at very low flows (through drivers are not motivated to change lanes) and very high flows (no gaps to change lanes).
2. **Per-lane saturation flows (Step E).** Exclusive through lanes: s_th, the base saturation flow adjusted for all factors of section 9.2 except lane utilisation and turns. Exclusive left-turn lanes: s_th / E_L (Equation 19-14). Shared left-turn and through lane: s_th / (1 + P_L × (E_L,m − 1)), with P_L its share of left-turning vehicles (the form of Equation 31-63; the left turns are protected, section 9.3).
3. **Equalize the flow ratios (Steps F to H).** Each movement's demand is distributed over the lane groups it may use so that they all reach one common flow ratio y* (Equations 31-64 and 31-65), starting from an equal split. Because P_L, and with it the shared lane's saturation flow, depends on the distribution, the calculation is repeated until no lane group's flow changes by more than **0.1 veh/h** (Step H); it stops with an error if this has not happened after 100 rounds.

**Physical limit added by Jaadah.** In Step G, HCM assigns every lane the common flow ratio. When few vehicles turn left, this can assign an exclusive left-turn lane more vehicles than the left-turn demand (for example, about 490 veh/h for 300 left-turners), which is not physically possible; HCM does not state how to handle this case. Jaadah adds the rule that **a lane group never carries more of a movement than that movement's demand, nor less than zero**: the common flow ratio is reached by the lane groups that can reach it, and an exclusive left-turn lane with little demand carries all of it at a lower flow ratio. Whenever HCM's distribution is physically possible, both give the same result.

As a consequence, when few vehicles turn left, they all use the exclusive left-turn lane and the shared lane carries only through traffic; when many turn left, the left-turn lane reaches the common flow ratio and the remaining left-turners use the shared lane.

**Lane utilisation.** The lane-choice calculation uses per-lane saturation flows without the lane-utilisation factor, as Chapter 31 defines them (s_th, page 31-25). The capacity of an exclusive lane group with more than one lane (section 9.1) does include f_LU (Equation 19-8). As a result, the volume-to-capacity ratios of the lane groups of one approach can differ slightly even though their lane-choice flow ratios are equal.

**Limitations.** The procedure assumes that drivers balance the lanes as described, which real drivers do only approximately. It does not model left-turning vehicles blocking the shared lane while they wait for gaps (permitted left turns, not supported, section 9.3) or a short left-turn lane overflowing into the adjacent lane; queue overflow is still visible in the measured queue storage ratio (section 6.5). The distribution is labelled *modelled assumption*.

A fixed split (such as 50/50 or 60/40) was not used, because it would not respond to the demand and could not be justified.

## 9.5 Green time of a lane group

A lane group's effective green g is the total effective green of the phases that serve **all** of its movements. The case-study intersection uses one phase per approach, so every movement of an approach, including both movements of a shared lane, moves in one phase, once per cycle. A signal plan can do otherwise, for example in an intervention; the engine supports one green per cycle and reports the rest as follows.

| Signal pattern | Example | Capacity, v/c | HCM delay | Critical v/c (Xc) |
| --- | --- | --- | --- | --- |
| A movement is served in more than one phase | North left gets 5 s in phase 2 and 5 s in phase 5 | `ok`: g is the sum of the greens (c = s × (g₁ + g₂) / C is correct for capacity) | `unavailable`: "movement served in more than one phase: HCM delay not supported yet" (uniform delay assumes one green per cycle) | `unavailable`: "a movement served in more than one phase would be counted once per phase: not supported yet" |
| A shared lane group whose movements are served in different phases, or with a phase that serves only some of them | East left + through in one phase, then East through alone | `unavailable`: "shared lane whose movements are served in different phases is not supported" (its through vehicles also move in the through-only phase, which g would leave out) | `unavailable` (no capacity) | `unavailable` (a lane group has no result) |

Other lane groups are calculated normally. `LaneGroupCapacity.green_periods` gives the number of phases serving a lane group. Supporting several greens per cycle (uniform delay from the queue accumulation polygon, and counting such a movement once in Xc) is future work.

## 9.6 Values reported for movements

Lane-group results are reported on their lane groups. Each movement also receives its own values, derived from the lane groups it actually uses (those that carry part of its demand, section 9.4):

- **volume-to-capacity ratio**: the ratio of those lane groups. The lane groups of an approach share one green and have equal lane-choice flow ratios (9.4), so their ratios are close; they can differ slightly because capacity includes lane utilisation, and the **highest** ratio is reported;
- **capacity**: the movement's demand divided by its volume-to-capacity ratio;
- **saturation flow**: the movement's demand divided by its flow ratio v/s.

When any lane group the movement uses is shared, the movement's values carry the "Shared lane" tag (section 2.1), with `measured_on_lane_group_id` naming the shared lane group.

When any lane group of the movement has no capacity result (9.3, 9.5, 9.7), the movement's values are `unavailable`. When the movement has no demand in the interval, it uses no lane group, so its values are `not_applicable`, with the reason "no demand in this interval".

The intersection's critical volume-to-capacity ratio Xc is `unavailable` when any lane group has no capacity result. A lane group belongs to a phase's critical-ratio calculation when that phase serves all of its movements.

## 9.7 Demand

The demand v of a movement in an interval is its `SimulationDemand` vehicle count for that interval converted to vehicles per hour (× 4 for 15 minutes). When a movement has no demand record for an interval, the capacity results that depend on it are `unavailable`, never calculated with zero demand.

## 9.8 Origin of the signal timing

The `input_origins` of capacity and volume-to-capacity results follow `SignalProgram.source`: a program with source `observed` is labelled *observed*; `baseline_model` and `intervention` are labelled *modelled assumption*.

## 9.9 Scope limitation: passenger cars only

Because heavy vehicles and buses are outside Jaadah's scope, both the simulation and the HCM calculation describe traffic made of passenger cars only. Real capacity, with trucks and buses present, would be somewhat lower.

---

# 10. HCM Control Delay and Level of Service

Implemented in `backend/analytics/kpi/hcm_delay.py`.

The HCM control delay is a **prediction** from the HCM formulas, calculated from the capacity results of section 9. It is a cross-check of the control delay **measured** in the simulation (section 7): similar values indicate that both are plausible, large differences point to something to check. The HCM notes that simulation tools often define delay differently, especially for oversaturated movements (Chapter 19, page 19-111), so some difference is expected.

## 10.1 The three delay terms

Control delay d = d1 + d2 + d3 (Equation 19-18), per lane group and interval:

- **Uniform delay d1** (Equations 19-19 to 19-21): the delay if vehicles arrived evenly; vehicles arriving on red wait for green. d1 = PF × 0.5 C (1 − g/C)² / (1 − min(1, X) g/C).
- **Progression factor PF** (Equation 19-20): calculated with the platoon ratio 1.0 of arrival type 3, random arrivals (Exhibit 19-13). Arrival type 3 applies to isolated signals or signals more than 3,200 ft apart (Exhibit 19-14); the nearest other signals are 1.3–2.1 km away. With a platoon ratio of 1.0 the equation gives PF = 1 exactly.
- **Incremental delay d2** (Equations 19-26 and 19-27): the extra delay from random cycle-to-cycle variation and from demand exceeding capacity. d2 = 900 T [(X − 1) + √((X − 1)² + 8 k I X / (c T))], with T = 0.25 h, k = 0.50 for pretimed phases (page 19-51) and I = 1.0 for an isolated intersection (Exhibit 19-11).
- **Initial queue delay d3** (Equations 19-44 to 19-49): the extra delay caused by a queue left over from the previous interval (section 10.2).

**Green for the whole cycle.** A lane group whose effective green equals the cycle (one phase with no yellow or all-red) never has red, so it is not signal-controlled, and Equation 19-19 would divide by zero. Its capacity and volume-to-capacity ratio are kept (c = s × g / C = s); its HCM delay is `unavailable`, with the reason "green for the whole cycle: not a signal-controlled movement". The simulation-based delay is still reported.

## 10.2 Queues carried from one interval to the next

The intervals of the analysis period are calculated **in order** (a multiple-period analysis, as the HCM advises when the volume-to-capacity ratio exceeds 1.0, Chapter 19, "Interpretation of Results"). For each lane group:

1. The chain starts at the **start of the warm-up** with no initial queue (Q_b = 0), when the simulated network is also empty, and runs through the warm-up intervals with their demand; only the analysis intervals are reported. HCM and simulation therefore start from the same condition, and the first HCM period is one without a residual queue, as the HCM's guidance for multiple-period analyses requires. The warm-up must therefore be a whole number of 15-minute intervals.
2. The queue left at the end of each interval, the **residual queue** Q_e = Q_b + t_A (v − c_A) (Equation 19-45), is the **initial queue** of the next interval.
3. With an initial queue, the uniform delay is adjusted: for the part of the interval during which the initial queue is still being served (t, Equations 19-37 and 19-38), the lane group operates saturated, and d1 = d_s × t / T + d1,baseline × (T − t) / T (Equation 19-40), where d_s is the uniform delay at X = 1.
4. d3 follows from Equation 19-44. It is 0 when there is no initial queue.

With pretimed control and no permitted left turns, the saturated capacity of a lane group equals its capacity, so the average capacity c_A equals c (Equations 19-42 and 19-43), and the uniform delay of a lane group without an initial queue is its baseline d1 (Equation 19-41).

When a lane group has no demand in an interval, its delay is `not_applicable` ("no demand in this interval"), but its queue still drains at capacity, so the next interval starts with the correct initial queue. When a lane group has no capacity result in an interval (section 9), its HCM delay is `unavailable`, and so is every later interval of that lane group, because its initial queue is then unknown.

## 10.3 Shared lanes

The HCM notes that Equation 19-19 does not give an accurate uniform delay for a shared-lane lane group or a lane group with permitted operation, and refers to the queue accumulation polygon (Chapter 19, page 19-51). That method is needed when the discharge rate changes during the green, as when left-turning vehicles in a shared lane wait for gaps in opposing traffic. At the case-study intersection each approach has its own phase, so left turns are protected and a shared lane discharges at one saturation flow during its green; the queue accumulation polygon is then a single triangle and gives the same uniform delay as Equation 19-19. Equation 19-19 is therefore used for the shared lanes, with their saturation flow from section 9.4. Permitted left turns, for which this would not hold, have no capacity result (section 9.3) and so never reach this calculation.

## 10.4 Level of service and movement values

Each lane group's HCM level of service is graded from its control delay and its volume-to-capacity ratio with the thresholds of section 3.2, including the override of section 3.3 (LOS F when v/c > 1.0).

A movement's HCM delay is the average of the delays of the lane groups it uses, weighted by the movement's flow in each (the weighting of Equation 19-28). Its level of service is graded from that delay and the movement's volume-to-capacity ratio (section 9.6). Approach and intersection HCM delays and levels of service are combined in the roll-up (section 2.4), from delay alone (section 3.3).

---

# 11. Roll-up to Approach and Intersection

Implemented in `backend/analytics/kpi/rollup.py`. The roll-up combines the results of one interval of one run; results of several runs are combined afterwards.

## 11.1 Rules

| KPI | Movement | Approach | Intersection |
|---|---|---|---|
| Measured control delay | section 7 | mean of its movements, weighted by completed vehicles | mean of all movements, weighted by completed vehicles |
| Queue duration | section 7 | as measured control delay | as measured control delay |
| Throughput | section 5 | sum of its movements | sum of all movements |
| Queue length (m and veh) | longest of the lanes it uses | longest of its lanes | longest of all lanes |
| Queue storage ratio | highest of the lanes it uses | highest of its lanes | highest of all lanes |
| HCM control delay | section 10.4 | mean of its lane groups, weighted by lane-group demand (Equation 19-28) | mean of all lane groups, weighted by demand (Equation 19-29) |
| HCM level of service | section 10.4 | from the approach delay alone | from the intersection delay alone |
| Volume-to-capacity ratio | section 9.6 | highest of its lane groups | critical v/c ratio Xc (section 9) |
| Capacity | section 9.6 | sum of its lane groups | not reported |

Averages are weighted so that a busy movement counts more than a quiet one: an approach where 300 vehicles waited 10 s and 100 vehicles waited 50 s has a mean delay of (300 × 10 + 100 × 50) / 400 = 20 s, the delay of the average vehicle, not 30 s. Ratios and queues are never averaged, because an average would hide the lane that overflows.

Measured levels of service are graded after the runs are combined (section 7.6).

## 11.2 Queue values and the lane they come from

A queue length or storage ratio names the lane it was measured on (`measured_on_lane_id`). For a movement this is the longest of the lanes that serve it; the result is tagged **Shared lane** only when that lane is shared with another movement. Metres and vehicles are each the longest separately, so they can come from different lanes. When two lanes are equal, the first in lane order is named.

## 11.3 Uncontrolled right turns

The uncontrolled right-turn slips (section 1) are **included** in the measured delay, queue duration, throughput, queue length and storage ratio of their approach and of the intersection; these results carry `uncontrolled_movements = included` ("includes uncontrolled right turns" on the dashboard). They are **excluded** from the HCM delay, because they have no lane group (section 8.3); the HCM delays of an approach with a slip, and of the intersection, carry `uncontrolled_movements = excluded` ("excludes uncontrolled right turns"). The model accepts only `included` on simulation results and only `excluded` on HCM results. A slip has no volume-to-capacity ratio or capacity.

## 11.4 Missing and not-applicable parts

- If **any** part of an approach or the intersection is `unavailable`, the combined value is `unavailable` ("a part of this element has no result"). A partial value would look complete but leave out the missing part.
- Parts that are `not_applicable` (for example a movement with no arrivals) are left out. If no part is left, the combined value is `not_applicable`.
- A lane with no cycle records, or with no known storage length, makes the queue or storage ratio of its movements, its approach and the intersection `unavailable`.
- All movements must belong to one intersection; otherwise the roll-up raises an error.

---

# 12. Combining Runs and Comparing Scenarios

Implemented in `backend/analytics/kpi/comparison.py`. The results are the models `KpiResult` and `KpiComparison` (`data_models.md` section 6).

## 12.1 Combining the runs of one scenario

Each seed is one repetition of the experiment and counts once. For each KPI, element and interval:

- **Value:** the mean over the runs that have a value.
- **Spread:** the sample standard deviation (divided by n − 1) when two or more runs have a value; none with one run. Example: 30, 34 and 38 s give 34 ± 4.0 s.
- **A run without a result:** if any run is `unavailable`, the combined result is `unavailable`, with a reason such as "unavailable in 1 of 10 runs". The missing run is usually the most congested one (vehicles still queued at the end of the run), so averaging the others would make the result look better than it was. The remedy is a longer clearance.
- **A run with nothing to measure:** runs that are `not_applicable` (for example, no vehicles arrived) are left out, not counted as zero: a mean over no vehicles does not exist, and a zero would pull the mean down and widen the spread. The result is `not_applicable` only if no run has a value.
- `run_ids` lists the runs behind the value; a result without a value lists every run that was looked at.
- A movement value taken from a shared lane carries `measured_on_lane_id` (queues, section 12.3), and one taken from a shared lane group carries `measured_on_lane_group_id` (HCM values, section 9.6); both are set on the `KpiSpec` and kept only on results with a value.

Simulation-based level of service is graded from the combined delay (section 7.6). HCM results have no runs and need no combining.

## 12.2 Order: roll up per run, or combine per lane

Delay, queue duration and throughput are rolled up to approaches and the intersection within each run (section 11), and the runs are then combined.

## 12.3 Queues: lanes first

Queue length and storage ratio are combined over the runs **per lane first**; a movement, approach or intersection then takes its longest (highest) lane, with that lane's mean, standard deviation and runs. Example, East through over three runs: lane 3 has 80, 50 and 70 m (mean 66.7 m), lane 4 has 60, 90 and 60 m (mean 70 m), so East through is 70 m, measured on lane 4. Taking each run's longest lane first would give 80 m, a value no lane has. Combining per lane keeps the movement value equal to one lane result (one value in every view) and names one real lane for the "Shared lane" tag, which appears only when that lane is shared.

## 12.4 Comparing a baseline and an intervention

Simulation comparisons use the matched pairs of a `ReplicationSet` (common random numbers):

1. For each pair, **difference = intervention − baseline**. A negative change in delay or queue is an improvement.
2. **Change** = mean of the differences, with their sample standard deviation.
3. **Percentage change** = change ÷ baseline mean over the same pairs (empty when the baseline mean is 0).

Example (East delay): baseline 40, 50, 60 s; intervention 35, 44, 56 s; differences −5, −6, −4, so the change is −5 ± 1 s (−10 %). Comparing the two means instead (50 ± 10 against 45 ± 10.5) would hide the effect behind the variation between seeds, which is the same in both scenarios of a pair and cancels in the difference.

- If either run of any pair is `unavailable`, the comparison is `unavailable` ("unavailable in 1 of 10 pairs").
- Pairs in which a side is `not_applicable` are left out; `used_pairs` lists the pairs used. With no pair left, the comparison is `not_applicable`.
- For a queue, each side uses the runs of the lane its reported value comes from (section 12.3), so the change equals the difference between the two reported values.
- **Level of service** is a letter: the comparison shows both grades (e.g. D → C). For simulation results both grades are graded from the **delay comparison** of the same element and interval: the baseline grade from its baseline mean, the intervention grade from baseline mean + change. They come from the same matched pairs as the delay change, so they never contradict it. Example: baseline delays 10, 100 s and no value; intervention 20 s and two without value. Only pair 1 is matched: the delay goes 10 → 20 s and the LOS A → B. Grading the baseline from all its runs (mean 55 s, LOS D) would have shown D → B, an apparent improvement while delay got worse. HCM level-of-service comparisons keep the two HCM grades, which include the v/c override (section 3.3); HCM results have no runs, so no pair is ever left out. Each HCM result must match the comparison's scenario, KPI, method, reporting level, element, interval and unit, even when unavailable.
- **Partial sample:** when pairs were left out, the comparison's baseline values (`baseline_mean`, the baseline grade) can differ from the baseline scenario's own results, which use all its runs (in the example, 10 s and A against 55 s and D). Such comparisons carry `is_partial_sample`, shown as a tag ("Based on 1 of 3 matched runs: may differ from the scenario's own values"); `pair_count` holds the number of pairs in the set. When every pair is used, the values are identical and there is no tag.
- **HCM results** have no runs: the change is the plain difference, with no pairs and no standard deviation.

## 12.5 Input origins

`input_origins` are read from the inputs, not supplied by hand:

| Input | Origin |
| --- | --- |
| Demand | `SimulationDemand.source`: `rcrc` → observed; `synthetic`, `forecast` → modelled assumption. Demand that is **allocated** (`is_allocated`: part of a shared-lane detector count, split between movements) or **imputed** (`is_imputed`: an estimated count for a detector that did not report) also adds modelled assumption, whatever its source |
| Signal timing | `SignalProgram.source`: `observed` → observed; otherwise modelled assumption (section 9.8) |
| Lane geometry | modelled assumption (`GEOMETRY_INPUT_ORIGIN`): widths and storage lengths are SUMO defaults or modelled values |

Simulation results add *simulated*; HCM results add *modelled assumption* for the HCM default factors (`HCM_DEFAULTS_INPUT_ORIGIN`). A comparison carries the origins of both scenarios.

**Which demand records a result uses:** those of its own approach whose interval overlaps the result's interval. A lane, lane-group, movement or approach result uses its approach's records; an intersection result uses every approach's. Example: in 08:00–08:15 the East shared-lane count was split and North was measured in full, so East's results carry modelled assumption from the demand and North's do not. The approach is the unit because a split changes how traffic spreads over all the lanes of that approach. A whole-period result uses every interval it covers. An approach without demand records in an interval adds no demand origin. A demand record whose movement is unknown is rejected.

While lane geometry is a modelled assumption, every result already carries modelled assumption, so the demand markers change the label only once surveyed geometry is used.

## 12.6 Checking the runs of a comparison

Before comparing, the engine checks the `ReplicationSet` against its `SimulationRun` and `Scenario` records and stops with an error if:

- the two runs of a pair used different seeds, or two pairs used the same seed;
- a run is not `completed`, or belongs to the wrong scenario;
- the intervention scenario does not reference the baseline (`reference_scenario_id`);
- the runs differ in network version, SUMO version, step length, mapping version (`mapping_version`) or demand (`demand_sha256`);
- the two runs of a pair used different route files (`route_file_sha256`): with the same seed and demand, both scenarios of a pair plan exactly the same departures; route files differ only between pairs, which use different seeds;
- the two scenarios cover different time windows (`start_time`, `end_time`, `time_context`);
- the comparison's labels (baseline scenario, intervention scenario, replication set) differ from those of the `ReplicationSet` it is calculated from, or, for a simulation level-of-service comparison, from those of its delay comparison;

A wrong pairing would produce a convincing but false comparison.

---

# 13. Input and Measurement Contracts

What the engine expects from the components that prepare its inputs (network mapping, demand transformation, SUMO runs and output adapters). Items marked *to be built* are agreed but not yet implemented, because their inputs do not exist yet.

## 13.1 Queue length: lanes and approaches

- **Lanes and movements** report the queue of each lane over the lane's own section (its lane chain, `LaneMapping.sumo_lane_ids`): which lane is full, turn-bay and slip spillback, storage ratio.
- **Approaches and the intersection** report the **full queue over the whole upstream zone** (section 1.3): how far back the queue reaches. Beyond a lane chain several lanes merge, so a vehicle queued there belongs to the approach but to no single Jaadah lane. Example: on West the lane sections are 95 m long while the zone is 450 m; a queue reaching 250 m back is reported as 250 m on the approach.
- A lane whose queue reaches the end of its section is reported as a **minimum value** (`is_lower_bound`, with the reason "queue reaches the end of this lane's measured section (… m); the full queue is shown on the approach").
- Each lane's section, its queue and whether the queue reached the section end are measured from vehicle positions ([KPI measurements](kpi_measurements.md), section 5).
- The full-zone queue per approach and cycle is measured from vehicle positions (`ApproachCycleQueueRecord`, [KPI measurements](kpi_measurements.md), section 5.6).
- *To be built:* the `is_lower_bound` field on `KpiResult`, and the approach and intersection queue taken from the full-zone queue.

## 13.2 Uncontrolled right-turn slips

All three slips (S→E `MOV_S_E_BYPASS`, W→S `MOV_W_S_SLIP`, N→W `MOV_N_W_SLIP`) are in the KPIs, as sections 1.2 and 11.3 describe.

## 13.3 Movement attributes

- The authoritative `MovementAttributes` of the nine KPI movements are stored in `network_mappings.json`, next to the movements and lanes, and checked by the mapping validator; U-turn, tunnel and ramp movements have none.
- `MOV_S_W` is a **left** turn, signalized (protected; South's phase serves no opposing traffic). The SUMO connection's direction (`dir="s"`) is a label derived from the angle; it does not change how SUMO moves vehicles and is not changed. As a left turn, South's HCM saturation flow is about 3 % lower than as a through movement (left-turn factor 1/1.05; lane utilisation 0.971 instead of 0.952 for two lanes). The classification is to be checked against the measured saturation flow of those lanes once that calibration KPI exists.

## 13.4 Initial HCM queue

The HCM delay chain starts at the start of the warm-up with no initial queue and reports only the analysis intervals (section 10.2). The warm-up is a whole number of 15-minute intervals, and demand records cover the warm-up as well as the analysis period.

## 13.5 Equivalent inputs between compared scenarios

A comparison is valid only when baseline and intervention differ in the intervention alone. Besides the checks of section 12.6:

- the two scenarios cover the same time window (`start_time`, `end_time`, `time_context`);
- every run records the mapping version, the demand fingerprint and the route-file fingerprint it used (`SimulationRun`); mapping and demand are the same for every run of a replication set, and the route file is the same within each pair;
- baseline and intervention therefore use **one demand file, generated once and reused**: a demand file regenerated for each scenario with different demand IDs has a different fingerprint, even when the counts are identical.

These are checked by `check_replication_set` (section 12.6).

## 13.6 Vehicles, demand and signal timing

- **A vehicle's movement** is found through the SUMO demand manifest (`vehicle_id` → `demand_id`) and the demand file (`demand_id` → `SimulationDemand`), never by parsing vehicle IDs. The same lookup gives `is_allocated` and `is_imputed` for every vehicle (section 12.5).
- **Demand for capacity equals simulated demand:** each movement's demand is simulated on its main route; through counts are not split into ramp or U-turn routes, so the demand v of section 9.7 is exactly what is simulated at each stop line. For the same reason no vehicle crosses the intersection twice in the current demand.
- **Signal timing has one source:** the `SignalProgram` of a run is built from the signal program in the SUMO network file, so that SUMO and the HCM calculation use the same greens.
- **Incomplete passages are found from zone entry:** the output adapter records an `IncompletePassage` for every vehicle that entered the measurement zone during the analysis period and had not left it when the run ended (section 7.4). Selecting vehicles by their planned stop-line time is not equivalent: a vehicle can enter the zone before the end of the analysis period but be planned to reach the stop line after it.

## 13.7 Vehicles that could not enter the network on time

SUMO creates a vehicle at the network edge only when there is a safe gap; otherwise the vehicle waits outside the network (insertion delay). That waiting is not control delay (it happens before the vehicle exists in the model, outside the measurement zone) and is not added to it. A long wait means the queue reached the model edge, so the measured delay and queues of that approach are too low.

- **Rule:** when any vehicle of an approach due in an interval waited more than **10 s** to enter, or had not entered when the run ended, that approach's measured control delay, queue duration and queue length for the interval are `unavailable`, with the reason "vehicles could not enter the network on time; queue reached the model edge". Its lanes and movements follow, and the intersection through the roll-up; other approaches, throughput and HCM results are not affected.
- **Threshold:** 10 s is above SUMO's normal insertion rounding (one or two seconds when vehicles are due at the same moment) and well below the wait caused by a queue at the edge (most of a red period, 80–105 s here). It becomes a parameter in `parameters.py` and is to be reviewed after a run with realistic peak demand.
- *To be built:* the output adapter provides, per approach and interval, the longest insertion delay of the vehicles due in that interval and the number of vehicles not yet inserted when the run ended (a new output record).

## 13.8 Intervals close to capacity

Demand comes from stop-line counts, which count vehicles as they are served: in an overloaded interval fewer vehicles are counted than arrived, so the simulated delay, queues and v/c ratios are too low. When an approach's HCM volume-to-capacity ratio is **0.95 or more** in an interval, its measured delay, queues and v/c for that interval are marked as minimum values (`is_lower_bound`, reason "demand counted at the stop line may be below the real demand (v/c ≥ 0.95)"). *To be built* with the `is_lower_bound` field (section 13.1).

---

# 14. Limitations

- **Served volume:** stop-line counts are vehicles served, not vehicles arriving. In oversaturated periods the demand is underestimated, so simulated queues, delays and v/c ratios are lower than real ones (section 13.8).
- **Random arrivals:** platoons from upstream signals are not represented, consistent with arrival type 3 in the HCM delay (section 10.1). The nearest signals are 1.3–2.1 km away.
- **Driving behaviour:** SUMO passenger-car defaults, not calibrated. The comparison of measured and HCM saturation flow is the planned check.
- **Instantaneous lane changes:** no lane-change duration is set, so a vehicle never blocks two lanes while changing lanes.
- **Passenger cars only:** no heavy vehicles or buses (section 9.9).
- **Signal patterns:** one green per movement and cycle; permitted left turns, several greens per cycle and greens lasting the whole cycle have no HCM delay (sections 9.3, 9.5, 10.1). Plans with overlapping phases, where a movement stays green from one phase into the next, are rejected when the signal program is built ([KPI measurements](kpi_measurements.md), section 3.1).
- **Modelled geometry:** lane widths are SUMO's 3.2 m default and storage lengths are not yet known, so every result carries *modelled assumption* and storage ratios are `unavailable`.
- **Synthetic demand:** until RCRC data is available, demand comes from synthetic detector counts; shared-lane counts are split by an assumed method (`is_allocated`).

---

# 15. Difficulties

The decisions that were hardest to make, what made each difficult, and what was decided.

| Topic | Difficulty | Decision |
| --- | --- | --- |
| Shared left-through lanes | A shared lane's demand cannot be split between its movements by measurement, yet capacity depends on it. Equal flow ratios across lanes put too many left turners in the shared lane when they are few | HCM 7th Chapter 31 lane-choice procedure, plus a physical rule: no lane group carries more of a movement than its demand (section 9.4) |
| Residual queues between intervals | Each 15-minute interval could be treated alone (simple) or as a chain carrying leftover queues (correct when overloaded, more complex) | Full multiple-period analysis with d3 and initial-queue d1 (section 10.2) |
| HCM 6th to 7th edition | The switch after most values were chosen required re-checking every factor | All values verified against the 7th edition; North's three-lane left utilisation became 0.971, and groups with more lanes than listed take the smallest value |
| Combining queues over runs | Taking each run's longest lane gives a higher value that no lane has; averaging each lane first names one real lane | Lanes first, then the longest lane (section 12.3) |
| Baseline versus intervention | Comparing the two means hides the effect behind the variation between seeds | Paired differences over matched seeds, with LOS graded from the same pairs and a partial-sample tag (section 12.4) |
| Runs without vehicles | Counting them as zero delay seemed natural but would lower the mean and widen the spread | Left out; a mean over no vehicles does not exist (section 12.1) |
| Unsupported signal patterns | Several greens per cycle are a normal intervention design, but the HCM delay used here assumes one | Capacity kept, HCM delay and Xc `unavailable` until supported (section 9.5) |
| Queue measurement area | Lane sections are 85–395 m long (85–119 m except on East), the zones 388–500 m; a lane's queue cannot be followed beyond the point where lanes merge | Full-zone queue per approach, per-lane queues on the chains, and a minimum-value tag (section 13.1) |
| Vehicles waiting to enter | Their waiting is real but happens outside the model and is not control delay | Not added to delay; the approach is `unavailable` above a 10 s threshold (section 13.7) |

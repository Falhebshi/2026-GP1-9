# Jaadah KPI Engine

## Overview

The KPI engine calculates Jaadah's traffic performance indicators (control delay, level of service, volume-to-capacity ratio, capacity, saturation flow, queue length, queue duration, queue storage ratio and throughput) for the case-study intersection of Prince Turki Al-Awwal Road and Imam Saud Road.

It works on the canonical models described in `data_models.md`: its inputs are standardized simulation outputs and network models, and its output is a list of `KpiResult` records.

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
            └── test_rollup.py
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

Lane groups follow HCM 7th edition (Chapter 19, page 19-43): adjacent lanes serving the same movements form one group, and a shared lane is always its own group. Lane groups are derived from the `ApproachLane` records each time they are needed, rather than stored, and receive stable identifiers such as `east_L`, `east_LT` and `east_T`.

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

Queue length is measured per lane by lane-area (E2) detectors whose output period is one signal cycle, aligned with the cycle start. Each `CycleQueueRecord` therefore gives the longest queue on one lane in one cycle, in metres and in vehicles. Queue length is reported **in both units**, as two results: metres are used for the storage ratio, and vehicles are easier to read on the dashboard.

Queue length is a lane KPI. Shared lanes are reported as described in section 2.1, and an approach's queue is its longest lane (section 2.4). Queue duration is measured per vehicle and is calculated with delay (section 2.3).

## 6.2 Cycles that span an interval boundary

With a 120 s cycle, a 15-minute interval holds 7.5 cycles, so every second interval boundary falls inside a cycle. A cycle belongs to the interval that **contains its `cycle_start`**, giving 7 or 8 cycles per interval. A cycle that starts during the warm-up or clearance is not used, even if it ends inside the analysis period.

## 6.3 Queue per interval

For each lane and interval, the reported queue is the **largest cycle queue** in that interval. Metres and vehicles are each the largest value of the interval's cycles.

## 6.4 95th-percentile queue over the analysis period

For the analysis page, each lane also receives the **95th-percentile cycle queue** over all cycles of the analysis period, calculated with the **nearest-rank method**: the cycle queues are sorted and the value at rank ⌈0.95 × n⌉ is taken. For example, with 20 cycles the 19th smallest queue is reported.

The HCM 7th edition calculates its percentile back of queue analytically and does not prescribe a method for taking a percentile from measured cycles. The nearest-rank method was chosen because the result is always a queue that actually occurred, in whole vehicles, and is simple to explain and to check by hand.

## 6.5 Queue storage ratio

The queue storage ratio is a queue divided by the lane's storage length (`ApproachLane.storage_length_m`). A ratio above 1 means the queue was longer than the storage available, so it spilled back. It is reported:

- **per interval**: the interval's largest cycle queue ÷ storage length;
- **over the analysis period**: the 95th-percentile queue ÷ storage length.

When the storage length of a lane is not known, the queue length is still reported and only the storage ratio is `unavailable`, with the reason "storage length not known".

## 6.6 Missing records are not zero queues

A detector reports every cycle, including cycles with no queue, which are recorded as 0 m. A reported 0 m is a measured zero and is reported as `ok` with a value of 0. When a lane has **no** cycle record in an interval, its data is missing, and its queue is `unavailable` with the reason "no cycle records for this lane in this interval"; it is never reported as 0.

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

A lane group's effective green g is the green of the phases that serve **all** of its movements. The case-study intersection uses one phase per approach, so every movement of an approach, including both movements of a shared lane, moves in the same phase.

If the movements of a shared lane group are served in different phases, the lane group's capacity, volume-to-capacity ratio and HCM delay are `unavailable`, with the reason "shared lane whose movements are served in different phases is not supported".

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

## 10.2 Queues carried from one interval to the next

The intervals of the analysis period are calculated **in order** (a multiple-period analysis, as the HCM advises when the volume-to-capacity ratio exceeds 1.0, Chapter 19, "Interpretation of Results"). For each lane group:

1. The **first interval** starts with no initial queue (Q_b = 0). The warm-up exists so that the simulated analysis period starts in normal conditions, and the HCM's guidance for simulation analyses requires the first analysis period to be undersaturated.
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

The uncontrolled right-turn slips (section 1) are **included** in the measured delay, queue duration, throughput, queue length and storage ratio of their approach and of the intersection; these results are tagged "includes uncontrolled right turns". They are **excluded** from the HCM delay, because they have no lane group (section 8.3); the HCM delays of an approach with a slip, and of the intersection, are tagged "excludes uncontrolled right turns". A slip has no volume-to-capacity ratio or capacity.

## 11.4 Missing and not-applicable parts

- If **any** part of an approach or the intersection is `unavailable`, the combined value is `unavailable` ("a part of this element has no result"). A partial value would look complete but leave out the missing part.
- Parts that are `not_applicable` (for example a movement with no arrivals) are left out. If no part is left, the combined value is `not_applicable`.
- A lane with no cycle records, or with no known storage length, makes the queue or storage ratio of its movements, its approach and the intersection `unavailable`.
- All movements must belong to one intersection; otherwise the roll-up raises an error.
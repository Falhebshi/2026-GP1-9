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
        └── kpi_tests/
            ├── __init__.py
            └── test_parameters.py
```

Each engine file's tests are kept with the engine, in `backend/analytics/kpi/kpi_tests/`.

---

# 1. Scope of the Analysis

## 1.1 Analysis intervals

KPIs are calculated per **15-minute interval**, the HCM analysis period.

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
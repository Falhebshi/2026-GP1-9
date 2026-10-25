# KPI Measurements

The KPI engine (`kpi_engine.md`) calculates its indicators from canonical measurement records. This document defines how those records are produced from a SUMO run: where each measurement is taken, and the rules that turn SUMO's output into the records.

The engine itself does not depend on these rules; it uses the finished records.

---

# 1. Measurement Zones

Delay, queue duration and throughput are measured per vehicle while it passes through the **measurement zone** of its approach. Each zone has two parts:

- **upstream**, a fixed distance before the stop line, along the vehicle's route;
- **downstream**, a fixed distance after the **junction exit**, the end of the junction's internal lane, where the outgoing road begins.

| Approach | Upstream (before the stop line) | Downstream (after the junction exit) | Approach speed limit |
| --- | --- | --- | --- |
| East | 388 m | 155 m | 90 km/h |
| West | 450 m | 105 m | 70 km/h |
| North | 500 m | 65 m | 50 km/h |
| South | 500 m | 65 m | 50 km/h |

The upstream distances come from the Approach Study Distances Reference. The distances are stored on each approach in `network_mappings.json` (`zone_upstream_m`, `zone_downstream_m`; see [Network mapping](network_mapping.md#measurement-zones)), and the network validator checks that every movement's route starts before its zone and continues beyond it, so each zone lies entirely inside the modelled network.

A vehicle's zone is therefore the upstream part, the path through the junction, and the downstream part. The path through the junction differs by movement (about 46–70 m for the signalised movements and under 8 m for the slips), so the zone length differs by movement and is the same for every vehicle of a movement.

## 1.1 Reference points

- **Stop line:** the end of the last SUMO lane of the movement's canonical lanes (`LaneMapping.sumo_lane_ids`).
- **Junction exit:** the end of the junction's internal lane(s) on the vehicle's path, which is the start of the next route edge.

Distances are path lengths along the lanes the vehicle drives, using the lane lengths in the network file, not straight-line distances:

- **zone entry:** the point `zone_upstream_m` before the stop line; it usually falls inside a lane, several lanes back;
- **zone exit:** the point `zone_downstream_m` after the junction exit.

Example: `MOV_E_W` has 388 m before the stop line, its 63.8 m internal lane, and 155 m of outgoing road, so its zone is 606.8 m long.

The lanes of one road in this network differ in length by less than 0.5 m, so the boundaries do not depend on which lane of a road the vehicle uses.

## 1.2 Why the downstream part is measured from the junction exit

Measured from the stop line, North's 65 m would end the zone inside the junction for left turners, whose path through it is 64–70 m long. Measuring from the junction exit gives every movement its whole path through the junction plus a stretch of outgoing road, where vehicles that stopped regain their speed.

## 1.3 Why a fixed distance is enough

A vehicle starting from the stop line regains the speed limit within speed² ÷ (2 × acceleration), with SUMO's passenger-car acceleration of 2.6 m/s²:

| Approach | Speed limit | Distance to regain it from a stop | Distance available after the stop line |
| --- | --- | --- | --- |
| East | 25.0 m/s | ≈120 m | junction + 155 m |
| West | 19.4 m/s | ≈72 m | junction + 105 m |
| North, South | 13.9 m/s | ≈37 m | junction + 65 m |

The acceleration after a stop therefore lies inside the zone. A fixed zone was preferred to ending each vehicle's zone where it regains its speed, because every vehicle of a movement is then measured over the same stretch of road.

---

# 2. Control Delay and Queue Duration

Each vehicle that enters a zone produces one `VehicleDelayRecord` (data model section 4.4), or an `IncompletePassage` (section 4.5) when it has not left the zone when the run ends. Records are produced from SUMO's vehicle position output (FCD), recorded every 0.4 s.

## 2.1 Crossing times

A vehicle almost never stands exactly on the zone entry, the stop line or the zone exit at an FCD time. Each crossing time is **interpolated** between the two FCD rows on either side of the point.

Example: a vehicle 394 m before the stop line at 08:03:10.0 and 384 m before it at 08:03:10.4 crossed the 388 m zone entry 6 m into those 10 m, at 08:03:10.0 + 0.6 × 0.4 s = **08:03:10.24**.

Taking the first row past each point instead would place both the entry and the exit up to 0.4 s late, by different amounts, so the time in the zone could appear up to 0.4 s shorter than it was. A vehicle that met no delay would then show a negative time loss.

## 2.2 Free-flow travel time

The free-flow travel time is how long the vehicle itself would take through its zone with no other traffic and no signal:

free-flow time = Σ over the pieces of its path (length ÷ (the piece's speed limit × the vehicle's speed factor))

- **Each piece uses its own speed limit:** approach lanes, the junction's internal lane, and outgoing lanes, along the lanes the vehicle actually used. A turning vehicle drives the junction at the internal lane's lower speed (East's left turn: 61 km/h against the approach's 90 km/h); one speed for the whole zone would charge every turning vehicle delay it did not suffer.
- **Each vehicle uses its own desired speed:** SUMO gives every vehicle a speed factor (spread of about ±10 % around 1.0, from the vehicle type's `speedDev`), so a vehicle with factor 1.1 drives 10 % above the limit on an empty road. Measuring against the limit alone would give such a vehicle a negative time loss and a slow driver delay it did not suffer. Each vehicle's speed factor is read from SUMO's output. This matches SUMO's own definition of time loss, which allows a check against the tripinfo output.
- Lengths at the zone entry and exit count only the part of the piece inside the zone.

The departure planning of the demand writer uses the speed limit (factor 1.0) for every vehicle, because the factors are drawn by SUMO only when each vehicle is created. It aims the average vehicle at its planned time; the measurement uses each vehicle's actual factor.

## 2.3 Rounding tolerance

After interpolation, rounding can still leave a vehicle that met no delay slightly below zero. A time loss between −0.4 s (one FCD step) and 0 is recorded as 0: the free-flow time is set to the time in the zone. A time loss below −0.4 s is an error, because it can only come from a fault in the measurement.

## 2.4 Time stopped

`halted_time_s` is the time the vehicle stood still between its zone entry and exit: the FCD steps in which its speed was below 0.1 m/s, SUMO's standstill threshold.

## 2.5 Clearance

A vehicle that arrived in the analysis period but has not left its zone when the run ends has no time loss, and the engine reports its interval as `unavailable` (KPI engine section 7.4). The clearance (`SimulationConfig.clearance_duration_s`) must be long enough for the last arrivals to leave their zones.

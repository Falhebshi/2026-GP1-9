# SUMO Network Handoff

The Jaadah SUMO road network has been completed, reviewed, and verified through smoke and stress testing.

The finalized network file is:

`data/processed/road_network/jaadah_study_area.net.xml`

Backups were created at key development stages, and a final verified backup is stored at:

`data/processed/road_network/backups/jaadah_study_area_final_verified_backup.net.xml`

## Network Configuration

The network represents the selected Jaadah study area and includes:

- Corrected road and lane geometry.
- Central signalized intersection.
- Slip and bypass roads.
- Two modeled West-side U-turns.
- East-side entry and exit ramps.
- Grade-separated underground/main road.*
- Required lane-to-lane connections.
- Reviewed road speed limits.

Note: The underground road is topologically separated from surface traffic, although SUMO-GUI currently displays both on the same visual plane.

## Traffic Signal

The central intersection uses a 120-second signal cycle:

- East: 40s green
- South: 15s green
- West: 30s green
- North: 15s green
- 3s yellow after each green
- 2s all-red after each yellow

The South-to-East movement includes a pedestrian-actuated signal in the real road. Since pedestrians are outside the current simulation scope, this actuation is not included in the baseline model.

## Validation

Two temporary validation scenarios are included:

- `simulation/smoke_test.sumocfg`
- `simulation/stress_test.sumocfg`

Their route files are stored under:

`simulation/scenarios/`

The smoke test was used to verify basic network connectivity and signal operation.

The stress test was used to verify:

- Central intersection movements.
- Slip and bypass roads.
- U-turns.
- East-side ramps.
- Underground/main-road movements.
- Lane changes and merging.
- Queue formation and clearing.
- Network stability under increased traffic.

The final stress test completed successfully to 600 seconds without significant route, connectivity, teleportation, or simulation errors.

## Important

The traffic used in the smoke and stress tests is temporary validation demand only.

It is not the final synthetic baseline demand.

The next step is to create the synthetic traffic demand using the finalized network without changing the road geometry or connections unless a confirmed network issue is found.
# Documentation

How each part of Jaadah works, one document per part. To install and run the project, start with the [main README](../README.md).

## Documents

New to the project? Read [SUMO network](sumo_network.md), [Simulation integration](simulation_integration.md) and [KPI engine](kpi_engine.md) first: together they cover how a run is built and what it measures.

| Area | Document | Covers |
| --- | --- | --- |
| Traffic data | [RCRC traffic feed](rcrc_traffic_feed.md) | Loading the RCRC report and the replay clock |
| | [Traffic ingestion](traffic_ingestion.md) | Turning source observations into canonical records |
| | [Traffic demand transformation](traffic_demand_transformation.md) | From detector counts to movement demand, including shared lanes and missing counts |
| | [Network mapping](network_mapping.md) | Detectors, approaches, movements, and lanes in the network |
| | [Data models](data_models.md) | Jaadah's canonical data models |
| Simulation | [SUMO network](sumo_network.md) | The study area network and its signal plan |
| | [SUMO demand generation](sumo_demand_generation.md) | Writing SUMO route files from movement demand |
| | [Simulation integration](simulation_integration.md) | The SUMO runner and baseline runs |
| | [Calibration](calibration.md) | Calibration and validation against the RCRC counts |
| | [Live update loop](live_update_loop.md) | Simulating each new interval for Current Traffic |
| Results | [KPI measurements](kpi_measurements.md) | How measurements are taken from a SUMO run |
| | [KPI engine](kpi_engine.md) | KPI definitions, one run's KPIs, and the historical analysis |
| | [Network congestion map](network_congestion.md) | The main roads' congestion on Network Traffic Overview |
| Website | [Accounts and Login](accounts.md) | Accounts server, roles, sessions, and password rules |
| | [Night mode](night_mode.md) | The dashboard's light and night themes |
| | [3D scene guide](../simulation/scene_3d/README.md) | Building the files for the 3D intersection view |
| Earlier work | [Synthetic traffic source](synthetic_traffic_source.md) | The synthetic detector source used before the RCRC report arrived |
| | [RCRC sample analysis](rcrc_sample_analysis.md) | Analysis of the earlier RCRC sample (site 1028) |


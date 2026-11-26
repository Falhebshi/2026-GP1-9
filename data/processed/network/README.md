# Network map data: sources and licences

The files in this folder are built from open data and project assumptions for the Network Traffic Overview page (`docs/network_congestion.md`). No RCRC data is used in any of them.

| File | Built by | From | Licence |
| --- | --- | --- | --- |
| `road_segments.json` | `jaadah/network_congestion/segments.py` | OpenStreetMap | ODbL 1.0 |
| `segment_mappings.json` | `jaadah/network_congestion/segments.py` | OpenStreetMap | ODbL 1.0 |
| `segment_demand.json` | `jaadah/network_congestion/demand.py` | OpenStreetMap and WorldPop | ODbL 1.0 (WorldPop under CC BY 4.0) |
| `activity_centres.csv` | written by the team | Published size measures of Riyadh's major activity centres; each row lists its own source, date, evidence type and confidence | Our own table of facts, each credited to its source |
| `zones.json` | `jaadah/network_congestion/zones.py` | WorldPop, OpenStreetMap places, `activity_centres.csv`, published city totals (below), ITE trip rates | ODbL 1.0 (WorldPop under CC BY 4.0) |
| `od_summary.json` | `jaadah/network_congestion/trips.py` | `zones.json`, `road_segments.json` and the trip lengths in `parameters.py` | ODbL 1.0 |
| `segment_hourly_vc.json` | `jaadah/network_congestion/assignment.py --date 2026-09-16` | The trip model (files above), a Wednesday | ODbL 1.0 |
| `segment_hourly_vc_friday.json` | `jaadah/network_congestion/assignment.py --date 2026-09-18` | The trip model (files above), a Friday | ODbL 1.0 |

- `zones.json`: the trip model's zones of about 2 km, with their population and the weekday vehicle trips each attracts by purpose.
- `od_summary.json`: a summary of the trip matrices (trips, mean length and largest flows per purpose). The matrices themselves (`od_matrices.npz`, `od_sensitivity.npz`) and the hourly flows (`assigned_flows*.json`) are rebuilt from the code and not committed.
- `segment_hourly_vc*.json`: each segment's v/c for every hour of the day in the trip model. The map uses them only to rank roads; the map's overall level comes from TomTom.

Rebuild commands are in `docs/network_congestion.md`.

## OpenStreetMap

Map data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0: https://www.openstreetmap.org/copyright

These files are derived from OpenStreetMap, so they are shared under the same licence, as the ODbL requires.

## WorldPop

`segment_demand.json` and `zones.json` use the WorldPop population density for Saudi Arabia, 2020, 1 km, UN adjusted (CC BY 4.0): WorldPop and CIESIN (2018), https://doi.org/10.5258/SOTON/WP00675

## Published figures

`zones.json` scales OpenStreetMap places to these city totals (also listed in its `source` field):

- office floor area: JLL, Saudi office market, Q2 2025;
- retail area: Knight Frank, The Saudi Report 2025, quality retail GLA, end of H1 2025;
- university students: Riyadh city, 1438 AH / 2017 (Saudipedia, citing official statistics);
- hospital beds: Ministry of Health, Statistical Yearbook 2022, Riyadh region.

Trip rates are from the ITE Trip Generation Manual, 11th edition (`TRIP_RATES` in `parameters.py`). Only single figures are used, each credited; no table or text from these sources is copied.

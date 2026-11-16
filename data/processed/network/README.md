# Network map data: sources and licences

The files in this folder are built from open data for the Network Traffic Overview page.

| File | Built by | From | Licence |
| --- | --- | --- | --- |
| `road_segments.json` | `jaadah/network_congestion/segments.py` | OpenStreetMap | ODbL 1.0 |
| `segment_mappings.json` | `jaadah/network_congestion/segments.py` | OpenStreetMap | ODbL 1.0 |
| `segment_demand.json` | `jaadah/network_congestion/demand.py` | OpenStreetMap and WorldPop | ODbL 1.0 (WorldPop under CC BY 4.0) |

## OpenStreetMap

Map data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0: https://www.openstreetmap.org/copyright

These files are derived from OpenStreetMap, so they are shared under the same licence, as the ODbL requires.

## WorldPop

`segment_demand.json` also uses the WorldPop population density for Saudi Arabia, 2020, 1 km, UN adjusted (CC BY 4.0): WorldPop and CIESIN (2018), https://doi.org/10.5258/SOTON/WP00675

No RCRC data is used in these files.

# Network congestion map

Network Traffic Overview colours every main road in Riyadh every 15 minutes. Traffic is counted at one intersection only (RCRC Site 1444), so the colours are **modelled, not measured** on those roads. The page says so in its notice.

The code is in `jaadah/network_congestion/`. The method is explained in each module's docstring; this page is the overview.

## What decides the colour

Three inputs, each deciding one thing:

| Input | Decides | Where |
| --- | --- | --- |
| Trip model (open data) | Which roads are busier than others, hour by hour | `zones.py`, `trips.py`, `timing.py`, `assignment.py` → `segment_hourly_vc.json` (Sunday–Thursday), `segment_hourly_vc_friday.json` (Friday and Saturday) |
| TomTom Traffic Index | How congested the city is in each 15 minutes of a typical week | `TOMTOM_TRAVEL_TIME_10KM_S` in `parameters.py`, used in `observed.py` |
| Counts at Site 1444 | Whether today is busier or quieter than usual (Day Factor) | `observed.day_factors`, limited by `DAY_FACTOR_LIMITS` |

Each 15 minutes:

1. The city level is TomTom's 10 km drive time over the time the same drive takes on our roads at free-flow speed, times the Day Factor.
2. Each segment's v/c follows how its road ranks in the trip model at that hour, around that level (`NETWORK_SPREAD`). The level is chosen so the network as a whole matches step 1.
3. The BPR function turns v/c into speed as a share of free flow, and the HCM speed bands give the colour: above 67% green, above 40% orange, 40% or less red.

The timeline bar of each 15 minutes is the speed of the slowest 20% of the road length (`TIMELINE_SLOWEST_SHARE` in `parameters.py`).

### Trip model in short

- **Zones** (`zones.py`): squares of about 2 km with their population (WorldPop) and what they attract (OpenStreetMap places and the major centres in `activity_centres.csv`, turned into trips with ITE rates).
- **Trips** (`trips.py`): a gravity model sends trips from homes to activities for each purpose; mean trip lengths come from published values.
- **Times** (`timing.py`): when each purpose travels, by kind of day, with school terms, holidays and Riyadh Season.
- **Roads** (`assignment.py`): each hour's trips are put on the main roads in four rounds, travel times following BPR between rounds.

## Running it

From the repo root, each in its own terminal:

```bash
uvicorn traffic_source.rcrc_replay.server:app --port 8002  # RCRC replay, port 8002 (docs/rcrc_replay_source.md)
uvicorn backend.accounts.server:app --port 8003           # accounts, for logging in (docs/accounts.md)
uvicorn jaadah.network_congestion.server:app --port 8001  # network map
cd frontend && npm run dev                                # website, port 5173
```

The map server needs the RCRC replay running. On its first start it fills the last 7 days; after that it adds each completed 15 minutes. `JAADAH_NETWORK_SOURCE=synthetic` uses the older synthetic speeds instead.

The speeds are stored in `data/network_congestion/network_speeds.db` (not in git). If the server says the database was built from other inputs, delete the file and start the server again.

## Rebuilding the data

The committed files in `data/processed/network/` are enough to run the map. To rebuild them, download the OpenStreetMap and WorldPop inputs into `data/raw/network/` (see the docstrings of `segments.py` and `demand.py`), then:

```bash
python -m jaadah.network_congestion.segments
python -m jaadah.network_congestion.demand
python -m jaadah.network_congestion.zones
python -m jaadah.network_congestion.trips
python -m jaadah.network_congestion.assignment --date 2026-09-16
python -m jaadah.network_congestion.assignment --date 2026-09-18 \
    --out data/processed/network/assigned_flows_friday.json \
    --hourly-vc data/processed/network/segment_hourly_vc_friday.json
```

The assignment takes several minutes per hour. Delete `network_speeds.db` afterwards, since its speeds came from the old files. Sources and licences of each file are in `data/processed/network/README.md`.

`python -m jaadah.network_congestion.validation` checks the map's pattern against the Site 1444 counts on later weeks. It prints summary numbers only and writes nothing.

## Limits

- **Modelled, not measured.** Only Site 1444 is counted. The city level is calibrated to TomTom, so agreeing with TomTom proves nothing; the only independent check is the validation script above.
- **Two fixed days.** The road ranking comes from one Wednesday (16 Sep 2026) for Sunday–Thursday and one Friday (18 Sep 2026) for Friday and Saturday. Other days differ only through TomTom's day-of-week pattern and the Day Factor.
- **Not an equilibrium assignment.** Trips are loaded in four rounds (`ASSIGNMENT_ROUNDS`), not iterated until no driver can find a faster route.
- **The model's evening is lighter than TomTom's.** Commuting and school alone don't make the evening the busiest period; the TomTom level corrects the overall level, not each road.
- **Roads with no model data.** About 700 segments (about 5% of the road length; a few more on Fridays and Saturdays) are on roads the trip model sends no trips along. They get no speed and are drawn in grey as "No data", and they are left out of the city level and the timeline.
- **Display smoothing.** Ramps and pieces under 200 m are drawn between the speeds of the roads at their two ends (`frontend/src/services/segmentNeighbours.js`). The stored speeds and the timeline are not changed.
- **One Day Factor for the whole city,** from one intersection, limited to 0.8–1.25 so it can't turn the city green or red.

## Basemap

The basemap is OpenFreeMap: `positron` in light mode and `dark` in night mode (`NetworkMap.jsx`). When the mode changes, `setStyle` swaps the basemap and keeps our sources and layers, placed above the basemap's roads and below its names.

## Tests

```bash
pytest jaadah/network_congestion/network_congestion_tests
```

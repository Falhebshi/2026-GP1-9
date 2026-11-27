# Jaadah | جادّة

Jaadah (جادّة) is a graduation project developed by students at King Saud University. The project aims to develop a web-based traffic digital twin platform that helps traffic engineers and urban planners better understand and analyze traffic conditions in Riyadh. By combining traffic data, microscopic traffic simulation, and traffic engineering methods, Jaadah provides an interactive environment for examining congestion, identifying potential traffic problems, and evaluating possible solutions.

The system provides both a broader overview of traffic conditions across the road network and a detailed simulation of a selected intersection in Riyadh. Using SUMO (Simulation of Urban MObility), Jaadah simulates vehicle movements and evaluates traffic performance through indicators such as delay, queue length, throughput, and level of service. The project also aims to incorporate artificial intelligence for traffic forecasting and anomaly detection, alongside recommendations for potential improvements. These improvements can then be tested and compared against the original traffic conditions through simulation, helping engineers make more informed decisions before implementing changes on real roads.

The study intersection is `INT_001`, Prince Turki Al-Awwal Rd × Imam Saud Rd. Its traffic comes from the RCRC detector report for that intersection, which the RCRC traffic feed plays back as if it were live. The report is restricted, so it is kept outside this repository (see [Without the private data](#without-the-private-data)).

## Technology stack

- **Frontend:** React 19, Vite, React Router, MapLibre GL, and deck.gl; oxlint for linting.
- **Python:** FastAPI and Uvicorn, Pydantic, pandas, NumPy, SciPy, Shapely, pyproj, Matplotlib, argon2-cffi (password hashing), and pytest.
- **Simulation:** SUMO and TraCI (with sumolib).
- **Local data storage:** SQLite (accounts, RCRC traffic feed, network map speeds, synthetic source) and JSON files for the dashboard. Release 1 has no shared database.

## Repository structure

```text
frontend/       React dashboard; its data files are in frontend/public/data/
traffic_source/ Traffic sources: the RCRC traffic feed (rcrc_replay/) and the earlier synthetic source (synthetic/)
backend/        Traffic ingestion, demand transformation, KPI engine and history (analytics/), output files, and accounts
jaadah/         Shared data models, network mapping, SUMO demand generation, calibration, KPI inputs, and the network congestion map
simulation/     SUMO configurations, run scripts, the live update loop, and 3D scene-building tools
analysis/       One-off analyses: RCRC data checks, warm-up and signal plan evaluation, calibration charts
data/           Checked-in SUMO network, mappings, and other non-restricted inputs
tests/          Python tests (unit tests also sit next to their modules, in *_tests/ folders)
docs/           Technical documentation
```

The dashboard reads its files from `frontend/public/data/INT_001/`:

| Path | Contents | Committed |
| --- | --- | --- |
| `network/` | 3D scene | Yes |
| `baseline/` | Sample run | Yes |
| `signal_program.json` | Signal program shown on the Location cards | Yes |
| `live/` | Live update loop output | No (built from RCRC data) |
| `history/` | Trends page files | No (built from RCRC data) |

## Prerequisites

- Python and `pip` (used with Python 3.13, as in CI). Python dependencies are pinned in `requirements.txt`.
- Node.js 22 and npm (the frontend CI uses Node.js 22).
- SUMO with `sumo` on your `PATH` for simulation runs. The Python packages in `requirements.txt` do not install the SUMO executable.
- The private data folder (`jaadah-private-data/`, next to the repository) for anything that reads RCRC data (see [Without the private data](#without-the-private-data)).

Run the following commands from the repository root unless a step says to change directories. These examples use PowerShell on Windows.

### Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Keep this environment active for the Python commands below (activate it again in every new terminal). Check SUMO with `sumo --version`.

### Install frontend dependencies

```powershell
cd frontend
npm ci
cd ..
```

## Run the project

Each service runs in its own terminal. Each Python service answers a health check at `http://127.0.0.1:<port>/health`.

| Service | Port | Needs |
| --- | --- | --- |
| Website | 5173 | Accounts server to log in |
| Accounts server | 8003 | An administrator created once |
| RCRC traffic feed | 8002 | Private RCRC report, loaded once |
| Network map server | 8001 | RCRC traffic feed |
| Synthetic source (optional, earlier source) | 8000 | Private RCRC sample profiles |

Vite forwards `/api/auth` and `/api/admin` to port 8003 and `/api/network` to port 8001 (`frontend/vite.config.js`), so these ports must not change.

For the full demonstration, start them in this order: accounts server, RCRC traffic feed, network map server, live update loop, then the website.

### Accounts server

Every page except Login needs an account, and there is no default login. Create an administrator once (it asks for the password twice without showing it):

```powershell
python -m backend.accounts.create_admin --name "Your Name" --email you.admin@ksu.edu.sa --engineer-email you@ksu.edu.sa
```

`--engineer-email` is optional: it also creates your traffic engineer account with the same password, so you can log in either way. Accounts are stored on each laptop, so every teammate does this once on their own machine.

Then start the accounts server and keep it running while you use the website:

```powershell
python -m uvicorn backend.accounts.server:app --port 8003
```

Accounts are stored in `data/accounts/accounts.db`, which holds password hashes and is never committed. Password rules, sessions, and roles are described in [Accounts and Login](docs/accounts.md).

### Frontend

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173` and log in. Engineers land on Network Traffic Overview and administrators on the Admin Dashboard.

### RCRC traffic feed

Plays back the private RCRC report for the study intersection as a live feed ([RCRC traffic feed](docs/rcrc_replay_source.md)). Load the report once from the private folder, then start the service:

```powershell
python -m traffic_source.rcrc_replay.load ../jaadah-private-data/raw/rcrc/site_1444/<report>.csv
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
```

The report covers 13 July to 13 October 2026. The feed runs 13 weeks behind the real clock (16 November shows 17 August), keeping the real time of day and weekday, and releases one 15-minute interval every 15 minutes. So by default it has only released dates up to 13 weeks before today.

To release the whole report at once, which calibration and later baseline dates need, start it with offset 0:

```powershell
$env:JAADAH_REPLAY_OFFSET_WEEKS = "0"
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
```

The report and the replay database stay in `jaadah-private-data/`, never in the repository.

### Network map server

Colours the main roads on Network Traffic Overview every 15 minutes ([network congestion map](docs/network_congestion.md)). The colours are modelled from a trip model, the TomTom Traffic Index, and the site 1444 counts, not measured on those roads. With the RCRC traffic feed running:

```powershell
python -m uvicorn jaadah.network_congestion.server:app --port 8001
```

On its first start it fills the last 7 days, then adds each completed 15 minutes. The speeds are stored in `data/network_congestion/network_speeds.db`, which is not committed. The committed files in `data/processed/network/` are enough to run it; rebuilding them is described in the same document.

### Simulation

For a short SUMO smoke run using the included test routes (300 simulation seconds, no traffic data or KPIs):

```powershell
python simulation/scripts/run_simulation.py
```

For a baseline run of the study intersection, leave the RCRC traffic feed running and use another terminal:

```powershell
python simulation/scripts/run_baseline.py --analysis-start YYYY-MM-DDT08:00+03:00 --analysis-end YYYY-MM-DDT09:00+03:00
```

Use a date the feed has already released (see [RCRC traffic feed](#rcrc-traffic-feed)) and keep the Riyadh `+03:00` offset. If a date cannot be used, the runner stops before any work and says why. Add `--source synthetic` to use the synthetic source instead.

The run adds 15 minutes of warm-up before and clearance after the analysis period, as one continuous SUMO run (seed 42, 0.4 s step by default). It also reads the 35 days before the window to estimate missing counts, so a window in the report's first weeks has less history to draw on.

Each run writes to a new folder in `simulation/outputs/baseline_runs/`: generated demand, `raw/fcd.xml` (can be large), `raw/tripinfo.xml`, and `summary.json`. To calculate the run's KPIs and write them for the dashboard:

```powershell
python -m backend.analytics.service simulation/outputs/baseline_runs/<run-id>
```

This writes the KPI files to `frontend/public/data/INT_001/baseline/` ([KPI engine](docs/kpi_engine.md), section 16). The vehicles and signals for the 3D view are built from the same run folder with `simulation/scene_3d/build_playback.py` ([3D scene guide](simulation/scene_3d/README.md)).

`signal_program.json` is the signal plan the network runs, written from the network file. Rebuild it after any change to the signal plan (a test checks that it matches):

```powershell
python -m backend.outputs.signal_program
```

More runner options and output details are in [simulation integration](docs/simulation_integration.md).

### Live update loop

Keeps the Current Traffic page up to date: each time the source delivers a 15-minute interval, the loop simulates it, continuing from the last saved SUMO state, and publishes its KPIs and playback ([live update loop](docs/live_update_loop.md)). With the RCRC traffic feed running:

```powershell
python simulation/scripts/run_live.py
```

Add `--source synthetic` to use the synthetic source. Stop it with Ctrl+C; the next start continues the chain if it is less than two hours behind. The page reads `frontend/public/data/INT_001/live/` and shows the committed sample run, labelled as a sample, when that folder has no run. The chain's working files go to `simulation/outputs/live/`. Neither folder is committed.

### Calibration and validation

Scores the simulation against the RCRC stop-bar counts with GEH, for the test hours of a range of days ([calibration](docs/calibration.md)). Start the RCRC traffic feed with offset 0 first (see [RCRC traffic feed](#rcrc-traffic-feed)), then in another terminal:

```powershell
python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12
python analysis/calibration/calibration_charts.py
```

Results hold RCRC-derived numbers, so they are written to `jaadah-private-data/processed/calibration/`, never to the repository.

### Traffic history for the Trends page

The Trends page reads files built from whole simulated days, 00:00–24:00 each, with RCRC demand ([KPI engine](docs/kpi_engine.md), section 17). With the RCRC traffic feed running:

```powershell
python simulation/scripts/run_history.py --first-day 2026-07-14
python -m backend.analytics.trends_page
```

- 14 July is the first day whose warm-up is inside the RCRC report. Without `--last-day`, the runner goes up to the last day the feed has fully released, skipping days already stored, so an interrupted batch continues where it stopped.
- Each day takes about 40 minutes and needs about 4.3 GB of disk space while it runs. Once its measurements are stored in `data/history/` (about 4 MB a day), the raw files are deleted. A day whose missing counts cannot be estimated fails and is reported, and the batch carries on.
- `trends_page` writes the 9 page files to `frontend/public/data/INT_001/history/`. Neither folder is committed.
- The 30-day view needs at least 24 stored days; the 90-day view needs at least 72. Until then the page shows the "not enough data" reason.

To store each new day automatically, schedule `simulation/scripts/nightly_history.cmd` as a Windows task at 03:00. It starts the RCRC traffic feed if it is not answering, runs both commands, and appends its output to `data/history/nightly.log`. The setup commands, and a cron line for macOS or Linux, are in the [KPI engine](docs/kpi_engine.md), section 17.11.

### Synthetic traffic source

The earlier traffic source, used before the RCRC report for the study intersection arrived and kept for comparison. It generates synthetic detector observations from processed profiles of an RCRC sample from another intersection (site 1028), so it needs those private profiles (see [Configuration](#configuration)):

```powershell
python -m uvicorn traffic_source.synthetic.server:app
```

Observations are stored in a local SQLite database under `data/synthetic_traffic/`. A new source starts with only seven days of history.

## Without the private data

The RCRC report and everything derived from it are restricted and are not published. Without the private data folder, you can still:

- run the website with the accounts server, log in, and manage accounts;
- view Current Traffic with the committed sample run, and the sample pages (Forecast, Alerts, Recommendations). Network Traffic Overview shows the plain basemap without road congestion, and Trends shows "No traffic history has been built yet.";
- run the SUMO smoke run and rebuild the 3D scene files ([3D scene guide](simulation/scene_3d/README.md));
- run the Python tests and the frontend checks below.

The RCRC traffic feed, the network map server, baseline and live runs, calibration, the Trends history, and the synthetic source all need private data.

## Configuration

No `.env` file is needed. If SUMO is not on `PATH`, the simulation scripts accept `--sumo-bin`. If a SUMO configuration uses `${VARIABLE}` in a file path, set that variable in your shell first.

| Variable | Used by | Effect |
| --- | --- | --- |
| `JAADAH_SECURE_COOKIE` | Accounts server | `true` sends the session cookie over HTTPS only; set it when Jaadah is reached over HTTPS |
| `JAADAH_REPLAY_OFFSET_WEEKS` | RCRC traffic feed | Weeks the replay runs behind the real clock (default 13; `0` releases the whole report) |
| `JAADAH_NETWORK_SOURCE` | Network map server | `synthetic` uses the older synthetic speeds instead of the RCRC counts |
| `JAADAH_RCRC_URL` | Network map server | Address of the RCRC traffic feed (default `http://127.0.0.1:8002`) |

The private data folder sits next to the repository, with these paths used by the code:

```text
<parent-of-repository>/
  2026-GP1-9/
  jaadah-private-data/
    raw/rcrc/site_1444/<report>.csv      RCRC report for the study intersection
    raw/rcrc/site_1028/rcrc_sample.xlsx  earlier RCRC sample (another intersection)
    processed/rcrc_replay/               replay database, written by the load step
    processed/rcrc_sample/               profiles for the synthetic source
    processed/calibration/               calibration demand and results
```

The synthetic source reads fixed paths in `traffic_source/synthetic/config.py`, in the format described in [synthetic traffic source](docs/synthetic_traffic_source.md).

## Tests

From the repository root, with the Python environment active:

```powershell
python -m pytest
```

Most tests use fixtures or temporary data, so they do not need the private data. Some live SUMO checks need the SUMO executable and are skipped without it. The full suite runs several SUMO simulations and takes a while; to test one area, pass its files or folder, for example `python -m pytest backend/analytics/kpi/kpi_tests`. CI runs `pytest` on every pull request to `main`.

For frontend checks, run from `frontend/`:

```powershell
npm run lint
npm run build
```

There is no frontend unit-test script in `frontend/package.json` at present. CI builds the frontend on every push and pull request to `main`.

## Documentation

| Document | Covers |
| --- | --- |
| [Accounts and Login](docs/accounts.md) | Accounts server, roles, sessions, and password rules |
| [RCRC traffic feed](docs/rcrc_replay_source.md) | Loading the RCRC report and the replay clock |
| [RCRC sample analysis](docs/rcrc_sample_analysis.md) | Analysis of the earlier RCRC sample |
| [Synthetic traffic source](docs/synthetic_traffic_source.md) | The earlier synthetic detector source |
| [Traffic ingestion](docs/traffic_ingestion.md) | Turning source observations into canonical records |
| [Traffic demand transformation](docs/traffic_demand_transformation.md) | From detector counts to movement demand, including shared lanes and missing counts |
| [SUMO demand generation](docs/sumo_demand_generation.md) | Writing SUMO route files from movement demand |
| [SUMO network](docs/sumo_network.md) | The study area network and its signal plan |
| [Network mapping](docs/network_mapping.md) | Detectors, approaches, movements, and lanes in the network |
| [Data models](docs/data_models.md) | Jaadah's canonical data models |
| [Simulation integration](docs/simulation_integration.md) | The SUMO runner and baseline runs |
| [Calibration](docs/calibration.md) | Calibration and validation against the RCRC counts |
| [KPI measurements](docs/kpi_measurements.md) | How measurements are taken from a SUMO run |
| [KPI engine](docs/kpi_engine.md) | KPI definitions, one run's KPIs, and the historical analysis |
| [Live update loop](docs/live_update_loop.md) | Simulating each new interval for Current Traffic |
| [Network congestion map](docs/network_congestion.md) | The city road congestion on Network Traffic Overview |
| [Night mode](docs/night_mode.md) | The dashboard's light and night themes |
| [3D scene guide](simulation/scene_3d/README.md) | Building the files for the 3D intersection view |

## Team

Aliyah Alharbi, Aroub Alswayyed, Fatimah Alhebshi, and Hawra Alhammad, supervised by Prof. Maha Alyahya. Department of Information Technology, College of Computer and Information Sciences, King Saud University (see `AUTHORS`).
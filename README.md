# Jaadah | جادّة

Jaadah (جادّة) is a graduation project developed by students at King Saud University. The project aims to develop a web-based traffic digital twin platform that helps traffic engineers and urban planners better understand and analyze traffic conditions in Riyadh. By combining traffic data, microscopic traffic simulation, and traffic engineering methods, Jaadah provides an interactive environment for examining congestion, identifying potential traffic problems, and evaluating possible solutions.

The system provides both a broader overview of traffic conditions across the road network and a detailed simulation of a selected intersection in Riyadh. Using SUMO (Simulation of Urban MObility), Jaadah simulates vehicle movements and evaluates traffic performance through indicators such as delay, queue length, throughput, and level of service. The project also aims to incorporate artificial intelligence for traffic forecasting and anomaly detection, alongside recommendations for potential improvements. These improvements can then be tested and compared against the original traffic conditions through simulation, helping engineers make more informed decisions before implementing changes on real roads.

This repository has a React dashboard, a synthetic traffic source, traffic ingestion and demand code, SUMO simulation scripts, KPI calculations, and an accounts server for login. The dashboard still uses sample data on several pages. Connecting simulation results and live KPIs to the dashboard, forecasting, and intervention comparisons is planned work.

## Technology stack

- **Frontend:** React, Vite, React Router, MapLibre GL, and deck.gl.
- **Python:** FastAPI, Pydantic, pandas, NumPy, argon2-cffi (password hashing), and pytest.
- **Simulation:** SUMO and TraCI.
- **Local synthetic data storage:** SQLite.

## Repository structure

```text
frontend/       React dashboard and its local 3D scene files
traffic_source/ Synthetic detector-observation service
backend/        Traffic ingestion, demand transformation, KPI calculations, and accounts
jaadah/         Shared data models, network mapping, and SUMO demand generation
simulation/     SUMO configurations, scripts, and scene-building tools
data/           Checked-in network and other non-restricted inputs
tests/          Python tests
docs/           Technical documentation
```

The dashboard's 3D view reads `frontend/public/data/turki_imamsaud/`. Its traffic, forecast, trends, network, and alerts pages currently use sample or placeholder data. The FastAPI service serves synthetic observations; there is no dashboard KPI API yet.

## Prerequisites

- Python and `pip` (used with Python 3.13). Python dependencies are pinned in `requirements.txt`.
- Node.js 22 and npm (the frontend CI uses Node.js 22).
- SUMO with `sumo` on your `PATH` for simulation runs. The Python packages in `requirements.txt` do not install the SUMO executable.
- The private processed traffic profiles described below if you want to run the synthetic source or an end-to-end baseline. The frontend and most tests do not need them.

Run the following commands from the repository root unless a step says to change directories. These examples use PowerShell on Windows.

### Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Keep this environment active for the Python commands below. Check SUMO with `sumo --version`.

### Install frontend dependencies

```powershell
cd frontend
npm ci
cd ..
```

## Run the project

Use separate terminals for the frontend, the accounts server, and the traffic source. Run commands from the repository root unless the step says otherwise.

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

Check `http://127.0.0.1:8003/health`. Accounts are stored in `data/accounts/accounts.db`, which holds password hashes and is never committed. When Jaadah is reached over HTTPS, set `JAADAH_SECURE_COOKIE=true` before starting it, so the session cookie is only sent over HTTPS. Engineers land on Network Traffic Overview and administrators on the Admin Dashboard. Password rules, sessions, and roles are described in [Accounts and Login](docs/accounts.md).

### Frontend

```powershell
cd frontend
npm run dev
```

Open the local URL printed by Vite and log in. Logging in needs the accounts server; the traffic pages otherwise work without the Python sources, and much of their displayed traffic data is still sample data.

### Synthetic traffic source

The available Python HTTP service serves synthetic detector observations. It needs the private profiles described below. In a new terminal at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn traffic_source.synthetic.server:app
```

Check `http://127.0.0.1:8000/health`. Generated observations are stored in a local SQLite database under `data/synthetic_traffic/`.

### RCRC replay source

Plays back the private RCRC report for the study intersection as a live feed ([RCRC replay source](docs/rcrc_replay_source.md)). Load the report once from the private folder, then start the service:

```powershell
python -m traffic_source.rcrc_replay.load ../jaadah-private-data/raw/rcrc/site_1444/<report>.csv
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
```

Check `http://127.0.0.1:8002/health`. The replay uses port 8002 because the network map server uses 8001. It runs 13 weeks behind the real clock (16 November shows 17 August, 1 December shows 1 September), keeping the real time of day and weekday, and releases one 15-minute interval every 15 minutes. The report and the replay database stay in `jaadah-private-data/`, never in the repository.

### Simulation

For a short SUMO smoke run using the included test routes:

```powershell
python simulation/scripts/run_simulation.py
```

This uses `simulation/configs/tests/smoke_test.sumocfg` and runs for 300 simulation seconds. It does not fetch traffic data or calculate KPIs.

For a baseline run, leave the RCRC traffic feed running and use another terminal at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python simulation/scripts/run_baseline.py --analysis-start YYYY-MM-DDT08:00+03:00 --analysis-end YYYY-MM-DDT09:00+03:00
```

To run from the synthetic source instead, start it and add `--source synthetic`.

Replace `YYYY-MM-DD` with a date the source has released. Keep the Riyadh `+03:00` offset. The run adds 15 minutes before and after the analysis period. The RCRC report covers **13 July to 13 October 2026**; with the default 13-week replay clock, the feed has released dates up to 13 weeks before today. For a later date in the report, restart the feed with `$env:JAADAH_REPLAY_OFFSET_WEEKS = "0"`, which releases the whole report. The runner says which of these applies when a date cannot be used. A new synthetic source has only seven days of history. Each run needs a new output directory under `simulation/outputs/baseline_runs/` by default. It writes generated demand, `raw/fcd.xml`, `raw/tripinfo.xml`, and `summary.json`. FCD files can be large, and raw outputs are not automatically shown as dashboard KPIs.

### Live update loop

Keeps the Current Traffic page up to date: each time the source delivers a 15-minute interval, the loop simulates it, continuing from the last saved SUMO state, and publishes its KPIs and playback ([live update loop](docs/live_update_loop.md)). With the RCRC replay source running:

```powershell
python simulation/scripts/run_live.py --source rcrc
```

Stop it with Ctrl+C. The page reads `frontend/public/data/INT_001/live/`, and shows the committed sample run, labelled as a sample, when that folder has no run. The chain's working files go to `simulation/outputs/live/`; both folders are ignored by git.

More runner options and output details are in [simulation integration](docs/simulation_integration.md). The separate [3D scene guide](simulation/scene_3d/README.md) explains how to rebuild the frontend's scene files.

## Configuration and data limits

No `.env` file is needed for these commands. To use the website, create an administrator with `create_admin` (see [Accounts server](#accounts-server)); there is no default login. If SUMO is not on `PATH`, the simulation scripts accept `--sumo-bin`. The synthetic source uses fixed paths in `traffic_source/synthetic/config.py`. If a SUMO configuration uses `${VARIABLE}` in a file path, set that variable in your shell first.

The synthetic source expects processed RCRC-derived profiles in a sibling folder, outside this repository:

```text
<parent-of-repository>/
  2026-GP1-9/
  jaadah-private-data/
    processed/rcrc_sample/
      rcrc_profile_summary.json
      detector_volume_summary.csv
      detector_time_of_day_profile.csv
      time_of_day_profile.csv
      day_type_time_profile.csv
      temporal_autocorrelation_summary.csv
```

The RCRC sample and derived profiles are restricted and are not published. The source requires the format described in [synthetic traffic source](docs/synthetic_traffic_source.md). Without the profiles, you can still use the frontend, SUMO smoke run, and tests with artificial data.

The baseline runner currently supports baseline scenarios only. Intervention execution and real forecasting are future integration work.

## Tests

From the repository root, with the Python environment active:

```powershell
python -m pytest
```

Most tests use fixtures or temporary data, so they do not need the private profiles. Some live SUMO checks need the SUMO executable and may be skipped without it.

For frontend checks, run from `frontend/`:

```powershell
npm run lint
npm run build
```

There is no frontend unit-test script in `frontend/package.json` at present.

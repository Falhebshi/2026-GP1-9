# Jaadah | جادّة

Jaadah (جادّة) is a King Saud University graduation project. We are building a traffic digital twin for a study intersection in Riyadh so traffic engineers can examine traffic conditions and test possible changes in simulation before applying them on the road.

This repository has a React dashboard, a synthetic traffic source, traffic ingestion and demand code, SUMO simulation scripts, and KPI calculations. The dashboard still uses sample data on several pages. Connecting simulation results and live KPIs to the dashboard, forecasting, and intervention comparisons is planned work.

## Technology stack

- **Frontend:** React, Vite, React Router, MapLibre GL, and deck.gl.
- **Python:** FastAPI, Pydantic, pandas, NumPy, and pytest.
- **Simulation:** SUMO and TraCI.
- **Local synthetic data storage:** SQLite.

## Repository structure

```text
frontend/       React dashboard and its local 3D scene files
traffic_source/ Synthetic detector-observation service
backend/        Traffic ingestion, demand transformation, and KPI calculations
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

Use separate terminals for the frontend and traffic source. Run commands from the repository root unless the step says otherwise.

### Frontend

```powershell
cd frontend
npm run dev
```

Open the local URL printed by Vite. The frontend works without the Python source; much of its displayed traffic data is still sample data.

### Synthetic traffic source

The available Python HTTP service serves synthetic detector observations. It needs the private profiles described below. In a new terminal at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn traffic_source.synthetic.server:app
```

Check `http://127.0.0.1:8000/health`. Generated observations are stored in a local SQLite database under `data/synthetic_traffic/`.

### Simulation

For a short SUMO smoke run using the included test routes:

```powershell
python simulation/scripts/run_simulation.py
```

This uses `simulation/configs/tests/smoke_test.sumocfg` and runs for 300 simulation seconds. It does not fetch traffic data or calculate KPIs.

For a baseline run from the synthetic source, leave the source running and use another terminal at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python simulation/scripts/run_baseline.py --analysis-start YYYY-MM-DDT08:00+03:00 --analysis-end YYYY-MM-DDT09:00+03:00
```

Replace `YYYY-MM-DD` with a date available from the source. Keep the Riyadh `+03:00` offset. The run adds 15 minutes before and after the analysis period. Check that `/health` reports a `latest_available_timestamp` at or after the end of this full window; a new source initially has only seven days of history. Each run needs a new output directory under `simulation/outputs/baseline_runs/` by default. It writes generated demand, `raw/fcd.xml`, `raw/tripinfo.xml`, and `summary.json`. FCD files can be large, and raw outputs are not automatically shown as dashboard KPIs.

More runner options and output details are in [simulation integration](docs/simulation_integration.md). The separate [3D scene guide](simulation/scene_3d/README.md) explains how to rebuild the frontend's scene files.

## Configuration and data limits

No `.env` file or application credentials are needed for these commands. If SUMO is not on `PATH`, the simulation scripts accept `--sumo-bin`. The synthetic source uses fixed paths in `traffic_source/synthetic/config.py`. If a SUMO configuration uses `${VARIABLE}` in a file path, set that variable in your shell first.

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

The baseline runner currently supports baseline scenarios only. Intervention execution, full raw-output processing, live dashboard KPIs, and real forecasting are future integration work.

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

# Jaadah | جادّة

Jaadah is a web-based traffic digital twin for Riyadh, built as a graduation project at King Saud University. It helps traffic engineers examine congestion, spot traffic problems, and evaluate possible solutions, combining traffic data, microscopic simulation with SUMO, and traffic engineering methods.

Jaadah simulates the study intersection with SUMO, calibrated and validated against the RCRC detector counts, and reports its KPIs for every 15 minutes, such as delay, queue length, throughput, and level of service: live on Current Traffic, and over past days on Traffic Patterns & Trends. Network Traffic Overview shows the congestion of the main roads. Planned next are traffic forecasting and anomaly detection, for the Traffic Forecast and Alerts pages, and recommendations that are tested against the original conditions through simulation before any change to real roads.

The study intersection is `INT_001`, Prince Turki Al-Awwal Rd × Imam Saud Rd. Its traffic comes from the RCRC detector report for that intersection, which the RCRC traffic feed plays back as if it were live. The report is restricted and kept outside this repository.

## Technology stack

- **Frontend:** React 19, Vite, React Router, MapLibre GL, deck.gl, oxlint.
- **Python:** FastAPI, Uvicorn, Pydantic, pandas, NumPy, SciPy, Shapely, pyproj, Matplotlib, argon2-cffi, pytest.
- **Simulation:** SUMO, TraCI, sumolib.
- **Storage:** SQLite and JSON files on each laptop; Release 1 has no shared database.

## Repository structure

```text
frontend/       React dashboard; its data files are in frontend/public/data/INT_001/
traffic_source/ The RCRC traffic feed (rcrc_replay/) and the earlier synthetic source (synthetic/)
backend/        Ingestion, demand transformation, KPI engine and history, output files, accounts, the launcher
jaadah/         Data models, network mapping, SUMO demand generation, calibration, the network congestion map
simulation/     SUMO configurations, run scripts, the live update loop, 3D scene tools
analysis/       One-off analyses and the calibration charts
data/           SUMO network, mappings, and other non-restricted inputs
tests/          Python tests (unit tests also sit next to their modules, in *_tests/ folders)
docs/           Technical documentation
```

## Setup

You need Python 3.13, Node.js 22, SUMO with `sumo` on your `PATH`, and the private data folder `jaadah-private-data/` next to the repository. `pip` installs every Python package, including TraCI and sumolib, but not SUMO itself; without SUMO, the launcher skips only the live update loop, while baseline runs, calibration, and the Trends history need it.

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd frontend; npm ci; cd ..
```

Commands here use PowerShell. On macOS or Linux, activate the environment with `source .venv/bin/activate`, and set a variable on the same line as its command, as in `JAADAH_REPLAY_OFFSET_WEEKS=0 python -m …`, instead of with `$env:`.

## Run the project

With the environment active:

```powershell
python -m backend.start
```

The launcher checks the setup and lists what is missing, offers to run `npm ci` and create the administrator account, and loads the RCRC report if needed. It then starts the RCRC traffic feed, the network map server, the accounts server, the website, and the live update loop in order, and opens `http://localhost:5173`. Ctrl+C stops everything.

- Flags: `--no-live` starts everything but the live update loop, `--no-browser` doesn't open the website, and `--verbose` shows every request.
- The network map server takes about a minute to start. A new live chain, on the first start or after more than two hours stopped, takes a few minutes to warm up.
- Keep the computer awake: sleep pauses the live update loop. On Windows, set sleep to Never while plugged in; on macOS, run `caffeinate -dis python -m backend.start`.
- An RCRC traffic feed already running on port 8002, such as one the nightly history run started, is reused and left running.
- `JAADAH_REPLAY_OFFSET_WEEKS` is left out, so the launcher's feed always runs on the 13-week demonstration clock.

### One-time setup

The launcher offers both of these; to do them yourself:

```powershell
python -m backend.accounts.create_admin --name "Your Name" --email you.admin@ksu.edu.sa --engineer-email you@ksu.edu.sa
python -m traffic_source.rcrc_replay.load ../jaadah-private-data/raw/rcrc/site_1444/<report>.csv
```

Administrators only manage accounts, so the optional `--engineer-email` also creates your traffic engineer account, with the same password, for the traffic pages. Accounts are stored per laptop in `data/accounts/accounts.db`.

### RCRC traffic feed

The report covers 13 July to 13 October 2026. The feed replays it 13 weeks behind the real clock, so 16 November shows 17 August, releasing one 15-minute interval every 15 minutes, so it has only released dates up to 13 weeks ago. Calibration and later baseline dates need the whole report: start the feed yourself with offset 0.

```powershell
$env:JAADAH_REPLAY_OFFSET_WEEKS = "0"
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
```

### Run the services one by one

To run or debug one service, start it in its own terminal. Each Python service answers `http://127.0.0.1:<port>/health`.

| Service | Port | Command |
| --- | --- | --- |
| Accounts server | 8003 | `python -m uvicorn backend.accounts.server:app --port 8003` |
| RCRC traffic feed | 8002 | `python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002` |
| Network map server | 8001 | `python -m uvicorn jaadah.network_congestion.server:app --port 8001` |
| Live update loop | none | `python simulation/scripts/run_live.py` |
| Website | 5173 | `cd frontend; npm run dev` |
| Synthetic source, earlier and optional | 8000 | `python -m uvicorn traffic_source.synthetic.server:app` |

Start them in this order. The ports must not change: Vite forwards `/api/auth` and `/api/admin` to 8003 and `/api/network` to 8001. Engineers land on Network Traffic Overview, administrators on the Admin Dashboard. The live update loop and the baseline runner take `--source synthetic` for the synthetic source.

## Simulation runs

A 300-second SUMO smoke run with test routes, without traffic data or KPIs:

```powershell
python simulation/scripts/run_simulation.py
```

A baseline run of the study intersection, with the RCRC traffic feed running, for a date it has released, keeping the `+03:00` offset, then its KPIs for the dashboard:

```powershell
python simulation/scripts/run_baseline.py --analysis-start YYYY-MM-DDT08:00+03:00 --analysis-end YYYY-MM-DDT09:00+03:00
python -m backend.analytics.service simulation/outputs/baseline_runs/<run-id>
```

Every run uses one fixed 225-second signal plan, all day, derived from the site 1444 counts with Webster's method. The real controller is actuated, so the plan is a modeled assumption, explained in [SUMO network](docs/sumo_network.md). After changing the plan, rebuild `signal_program.json` with `python -m backend.outputs.signal_program`.

### Calibration and validation

With the RCRC traffic feed on offset 0, these reproduce the official runs with 4 seeds. The charts read the two labels, so keep them:

```powershell
python simulation/scripts/run_calibration.py --days 2026-08-30..2026-09-12 --seeds 42 43 44 45 --label calibration_final
python simulation/scripts/run_calibration.py --days 2026-09-27..2026-10-03 --seeds 42 43 44 45 --label validation_final
python analysis/calibration/calibration_charts.py
```

Results stay in `jaadah-private-data/processed/calibration/`.

### Traffic history for the Trends page

With the RCRC traffic feed running:

```powershell
python simulation/scripts/run_history.py --first-day 2026-07-14
python -m backend.analytics.trends_page
```

Each day takes about 40 minutes and 4.3 GB of disk while it runs; days already stored are skipped. To add each new day automatically, schedule `simulation/scripts/nightly_history.cmd` at 03:00; section 17.11 of the [KPI engine](docs/kpi_engine.md) has the steps, also for macOS. Don't stop the launcher during the nightly run if the launcher started the feed: the run may be using it.

## Without the private data

You can run the accounts server and the website, log in and manage accounts, see Current Traffic with the committed sample run, run the SUMO smoke run, and run the tests. Network Traffic Overview then shows no road congestion, and Traffic Patterns & Trends shows no history. Everything else reads RCRC data. Traffic Forecast and Alerts are planned for Release 2.

## Configuration

No `.env` file is needed.

| Variable | Used by | Effect |
| --- | --- | --- |
| `JAADAH_SECURE_COOKIE` | Accounts server | `true` sends the session cookie over HTTPS only |
| `JAADAH_REPLAY_OFFSET_WEEKS` | RCRC traffic feed | Weeks behind the real clock, 13 by default; `0` releases the whole report |
| `JAADAH_NETWORK_SOURCE` | Network map server | `synthetic` uses the older synthetic speeds |
| `JAADAH_RCRC_URL` | Network map server | Feed address, `http://127.0.0.1:8002` by default |

The private data folder:

```text
jaadah-private-data/
  raw/rcrc/site_1444/<report>.csv      RCRC report for the study intersection
  raw/rcrc/site_1028/rcrc_sample.xlsx  earlier RCRC sample (another intersection)
  processed/                           replay database, synthetic profiles, calibration results
```

## Tests

```powershell
python -m pytest
```

The full suite runs several SUMO simulations and takes a while; to test one area, pass its folder, as in `python -m pytest backend/analytics/kpi/kpi_tests`. Tests that need SUMO are skipped without it. For the frontend, run `npm run lint` and `npm run build` in `frontend/`. CI runs the Python tests and the frontend build on every pull request to `main`.

## Documentation

How each part works is documented in [`docs/`](docs/).

## Team

Aliyah Alharbi, Aroub Alswayyed, Fatimah Alhebshi, and Hawra Alhammad, supervised by Prof. Maha Alyahya. Department of Information Technology, College of Computer and Information Sciences, King Saud University. The full list is in `AUTHORS`.

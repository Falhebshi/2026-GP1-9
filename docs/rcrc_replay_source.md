# RCRC Replay Source

## Overview

Jaadah is a digital twin: traffic data arrives continuously, and each new interval is simulated as it comes in. RCRC provides its detector data as report files, not as a live feed. The **RCRC replay source** turns a report back into a feed: it releases the report's 15-minute intervals one at a time as its clock advances, and serves them over HTTP the way a live RCRC service would.

It is a separate service outside the Jaadah application, like the [synthetic traffic source](synthetic_traffic_source.md). Jaadah **pulls** from it through `RcrcReplayClient` and never reads the report file itself (see [Traffic ingestion](traffic_ingestion.md#rcrc-source)). A live RCRC feed would replace only this service.

The implementation is in:

```text
traffic_source/
└── rcrc_replay/
    ├── config.py     paths and replay clock settings
    ├── report.py     reading an RCRC report file
    ├── storage.py    SQLite storage: report rows and replay clock
    ├── clock.py      which intervals have been released
    ├── server.py     FastAPI service
    └── load.py       command to load a report
```

---

## Private Data

The RCRC report and the replay database hold restricted RCRC data and are never stored in the repository. They live in the private data folder next to it, as for the RCRC sample:

```text
<parent-of-repository>/
  2026-GP1-9/
  jaadah-private-data/
    raw/rcrc/site_1444/
      <report>.csv
    processed/rcrc_replay/
      rcrc_replay.db           created by the load command
```

Tests use artificial reports only.

---

## Running It

Load the report once, then start the service:

```bash
python -m traffic_source.rcrc_replay.load ../jaadah-private-data/raw/rcrc/site_1444/<report>.csv
uvicorn traffic_source.rcrc_replay.server:app --port 8002
```

The load command prints the report period and, for each detector, how many intervals are missing and the longest gap. Loading the same file again changes nothing. Loading a different report replaces the stored one.

A baseline simulation can then pull from it:

```bash
python simulation/scripts/run_baseline.py --source rcrc \
  --analysis-start 2026-08-10T08:00+03:00 --analysis-end 2026-08-10T09:00+03:00
```

---

## The Replay Clock

The replay runs a whole number of weeks behind the real clock. `ReplayConfig.offset_weeks` (`config.py`, default **13**) sets how many:

```text
data time shown as "now" = real time - offset_weeks
```

rounded down to a 15-minute boundary for the latest released interval. Everything before it is history; later intervals are released as real time passes, one every 15 minutes.

Because the offset is whole weeks, the **time of day and the weekday always match the real clock**: a Tuesday-morning demonstration shows Tuesday-morning traffic. With 13 weeks:

| Real time | Data shown as "now" | History available |
|---|---|---|
| Mon 16 Nov 2026 | Mon 17 Aug 2026 | 13 July – 17 August (5 weeks) |
| Tue 1 Dec 2026 | Tue 1 Sep 2026 | 13 July – 1 September (7 weeks) |
| Tue 12 Jan 2027 | Tue 13 Oct 2026 | the whole report; the data ends here |

After the end of the data the clock stays there: the provider has nothing newer. To show a later or earlier point in the data, change `offset_weeks`.

The server reads the offset from the environment variable `JAADAH_REPLAY_OFFSET_WEEKS` when it is set (a whole number of weeks, 0 or more), otherwise it uses 13. Calibration compares runs with days in September and October, which the demonstration clock has not released yet, so it starts the server with `0`, which releases the whole report (see [`calibration.md`](calibration.md)):

```powershell
$env:JAADAH_REPLAY_OFFSET_WEEKS = "0"
python -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
Remove-Item Env:JAADAH_REPLAY_OFFSET_WEEKS   # back to the 13-week demonstration clock
```

**The dates in the data are never changed.** The replay only decides how much of the report has been delivered. The clock depends on nothing but the real time, so stopping or restarting the service never shifts it.

---

## API

### `GET /health`

```json
{
  "status": "ok",
  "source": "rcrc",
  "site_id": "1444",
  "latest_available_timestamp": "2026-08-27T08:15:00+03:00",
  "replay_time": "2026-08-27T08:21:40+03:00",
  "data_end": "2026-10-13T00:00:00+03:00"
}
```

`latest_available_timestamp` is the end of the latest interval released, and `replay_time` the data time shown as "now". An interval ending by then without rows is **missing**, not still to come; this is what lets Jaadah fill the newest interval during an outage. `status` is `no_report` and the timestamp `null` when no report is loaded.

### `GET /detectors`

The distinct `Detector ID : Description` values of the report.

### `GET /observations?start=...&end=...`

The released rows whose time stamp (an interval end) is after `start` and at or before `end`. Both must include a timezone and be on a 15-minute boundary. Rows not yet released are not returned, and `latest_available_timestamp` says how far the feed has reached.

Rows are served **exactly as RCRC wrote them**, as text (the values below are invented):

```json
{
  "source": "rcrc",
  "site_id": "1444",
  "interval_minutes": 15,
  "start": "2026-08-27T08:00:00+03:00",
  "end": "2026-08-27T08:15:00+03:00",
  "latest_available_timestamp": "2026-08-27T08:15:00+03:00",
  "observations": [
    {
      "Detector ID : Description": "144409: P2-NB-L1-L-STB-RP2",
      "Time Stamp": "Aug 27, 2026 08:15:00",
      "Volume (Vehicles)": "36",
      "Occupancy (Seconds)": "22",
      "Occupancy (Percent)": "2"
    }
  ]
}
```

Interpreting the values (types, timezone, interval) is Jaadah's job, in its RCRC adapter, so that sources adapt to Jaadah and not the other way round.

---

## Reading the Report

`read_rcrc_report()` refuses a file that is not a readable 15-minute RCRC report: no title, no site ID in the title, another aggregation interval, an unexpected column header, or a row with more values than the header. Repeated column header rows (one before each detector block) and blank rows are skipped.

Rows are otherwise kept as written, including values Jaadah will later reject, because a live provider would send them too. The service only reads each row's time stamp, to know when to release it. A row whose time stamp cannot be read is reported by the load command and never served.

---

## Storage

`RcrcReplayStorage` is the only code that touches the database. It holds the report rows, a record of the loaded report (site, title, SHA-256 fingerprint, data period) and the replay clock. Moving the source to another database, such as PostgreSQL, changes this class only.

---

## Testing

```bash
python -m pytest -v tests/test_rcrc_replay_source.py tests/test_rcrc_ingestion.py tests/test_baseline_run_rcrc.py
```

The tests cover reading reports and refusing malformed ones, the clock (whole intervals, keeping the time of day and weekday, stopping at the end of the data, unaffected by restarts), the API (released rows only, rows as written, bad requests, no report), the load command, ingestion through the real service, and the baseline runner with an RCRC source up to the point where SUMO starts.

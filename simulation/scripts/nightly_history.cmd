@echo off
rem Nightly trends history (docs/kpi_engine.md, section 17.11).
rem Stores the day that has just finished, then rebuilds the Trends page
rem files. Run by a Windows scheduled task at 03:00. Output is added to
rem data\history\nightly.log.

cd /d "%~dp0..\.."
set LOG=data\history\nightly.log
set PY=.venv\Scripts\python.exe
if not exist data\history mkdir data\history
echo ===== %date% %time% >> %LOG%

rem Start the RCRC replay source if it is not answering (after a restart).
rem The wait uses ping: timeout fails in a scheduled task.
%PY% -c "import httpx2; httpx2.get('http://127.0.0.1:8002/health', timeout=5).raise_for_status()" >NUL 2>&1
if errorlevel 1 (
    echo Starting the RCRC replay source >> %LOG%
    start "Jaadah RCRC replay" /min %PY% -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
    ping -n 21 127.0.0.1 >NUL
)

rem 13 July is the first day of the RCRC report; stored days are skipped,
rem so only the new day, and any earlier day that failed, are run.
rem -u writes each line to the log at once.
%PY% -u simulation\scripts\run_history.py --first-day 2026-07-13 >> %LOG% 2>&1

rem Rebuilt even when a day failed, so the days that were stored still appear
%PY% -u -m backend.analytics.trends_page >> %LOG% 2>&1
echo ===== finished %date% %time% >> %LOG%

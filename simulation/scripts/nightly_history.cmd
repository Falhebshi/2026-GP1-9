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

rem The RCRC replay source must answer with status ok (a server without a
rem report answers no_report). If it does not, start it and check again
rem every 5 s for up to 60 s. The waits use ping: timeout fails in a
rem scheduled task.
set HEALTH=%PY% -c "import httpx2, sys; sys.exit(httpx2.get('http://127.0.0.1:8002/health', timeout=5).json().get('status') != 'ok')"
%HEALTH% >NUL 2>&1
if not errorlevel 1 goto source_ok
echo Starting the RCRC replay source >> %LOG%
start "Jaadah RCRC replay" /min %PY% -m uvicorn traffic_source.rcrc_replay.server:app --port 8002
set /a TRIES=0
:wait_for_source
ping -n 6 127.0.0.1 >NUL
%HEALTH% >NUL 2>&1
if not errorlevel 1 goto source_ok
set /a TRIES+=1
if %TRIES% lss 12 goto wait_for_source
echo The RCRC replay source did not answer with status ok within 60 s; no day can be stored tonight >> %LOG%
:source_ok

rem 14 July is the first day whose warm-up (from 23:45 the day before) is
rem in the RCRC report. Stored days are skipped, so only the new day, and
rem any earlier day that failed, are run. -u writes each line at once.
%PY% -u simulation\scripts\run_history.py --first-day 2026-07-14 >> %LOG% 2>&1

rem Rebuilt even when a day failed, so the days that were stored still appear
%PY% -u -m backend.analytics.trends_page >> %LOG% 2>&1
echo ===== finished %date% %time% >> %LOG%

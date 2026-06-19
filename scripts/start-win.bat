@echo off
REM Hand Of Midas — Windows VPS Start Script
REM Starts Gold backend, Oil backend, and Frontend

echo ============================================
echo   HAND OF MIDAS - Starting All Services
echo ============================================
echo.

cd /d C:\hand-of-midas

REM Force UTF-8 for Python stdout/stderr so print() with arrows (→), em-dashes (—),
REM and emoji don't crash on Windows' default cp1252 charmap codec.
REM This avoids the June 10 09:44 IST 'charmap codec can't encode character' bug
REM in Gold Micro position_monitor without churning 70+ source lines.
REM PYTHONUTF8 enables UTF-8 mode (Python 3.7+); PYTHONIOENCODING is the belt-and-suspenders.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Kill any existing processes on our ports
REM Macro ports 5053+5054 retired 2026-06-19 — kill loop kept so legacy
REM processes get cleaned if they were started manually.
REM General service on 5050 hosts cross-cutting routes (auth + aggregate debug).
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5050" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5053" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5054" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5055" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5056" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

REM Rotate prior logs (restart-based; preserves week-long history across restarts).
REM Date format normalization: %date% on Windows can be "Fri 06/12/2026" or "12-06-2026" depending on locale.
REM Use PowerShell to get a deterministic timestamp.
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "TS=%%i"
echo [LOG ROTATE] timestamp=%TS%
REM Rotate legacy Macro logs too (in case they exist from prior runs).
if exist logs\general.log ren logs\general.log general.%TS%.log
if exist logs\gold.log ren logs\gold.log gold.%TS%.log
if exist logs\oil.log ren logs\oil.log oil.%TS%.log
if exist logs\micro.log ren logs\micro.log micro.%TS%.log
if exist logs\oil-micro.log ren logs\oil-micro.log oil-micro.%TS%.log
if exist logs\frontend.log ren logs\frontend.log frontend.%TS%.log

REM Default observability log level (DEBUG = max verbosity for week-long observability run).
REM Override at any time by setting HOM_LOG_LEVEL=INFO|WARN|ERROR before running this script.
if not defined HOM_LOG_LEVEL set HOM_LOG_LEVEL=DEBUG
echo [LOG LEVEL] HOM_LOG_LEVEL=%HOM_LOG_LEVEL%

REM ============================================================================
REM Macros (Gold + Oil) RETIRED 2026-06-19 — see DECISION_2026-06-19_DROP_MACROS.md.
REM Live signal scanning was env-gated off in commit e38b288, then services
REM removed from startup entirely (this commit) to silence position-monitor
REM noise + free RAM. To temporarily re-enable for diagnostic only:
REM   1. Uncomment the two REM-prefixed lines below.
REM   2. Set GOLD_MACRO_SCAN_ENABLED=true and/or OIL_MACRO_SCAN_ENABLED=true
REM      BEFORE running this script (env vars captured at config import time).
REM   3. Re-run start-win.bat. Verify via /api/gold/journal that scanning fired.
REM   4. Disable via env unset + re-comment when done.
REM ============================================================================
REM echo [1/3] Starting Gold Macro Backend (port 5053)...
REM start /B cmd /c "cd /d C:\hand-of-midas && python -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 > logs\gold.log 2>&1"
REM echo       OK
REM echo [2/3] Starting Oil Macro Backend (port 5054)...
REM start /B cmd /c "cd /d C:\hand-of-midas\backend-oil && python -m uvicorn main:app --host 0.0.0.0 --port 5054 > ..\logs\oil.log 2>&1"
REM echo       OK

echo [1/4] Starting General Backend (port 5050) — auth + aggregate debug...
start /B cmd /c "cd /d C:\hand-of-midas\backend-general && python -m uvicorn main:app --host 0.0.0.0 --port 5050 > ..\logs\general.log 2>&1"
echo       OK

echo [2/4] Starting Gold Micro Backend (port 5055)...
start /B cmd /c "cd /d C:\hand-of-midas\backend-micro && python -m uvicorn main:app --host 0.0.0.0 --port 5055 > ..\logs\micro.log 2>&1"
echo       OK

echo [3/4] Starting Oil Micro Backend (port 5056)...
start /B cmd /c "cd /d C:\hand-of-midas\backend-oil-micro && python -m uvicorn main:app --host 0.0.0.0 --port 5056 > ..\logs\oil-micro.log 2>&1"
echo       OK

echo [4/4] Starting Frontend (port 3001)...
start /B cmd /c "cd /d C:\hand-of-midas\frontend && npx next start -p 3001 > ..\logs\frontend.log 2>&1"
echo       OK

echo.
echo ============================================
echo   ALL SYSTEMS ONLINE
echo ============================================
echo.
echo   General:    http://localhost:5050   (auth + /api/debug/* + /api/health)
echo   Gold Micro: http://localhost:5055
echo   Oil Micro:  http://localhost:5056
echo   Frontend:   http://localhost:3001
echo   (Macros retired 2026-06-19 — see start-win.bat header)
echo.
echo   Logs: logs\general.log, logs\micro.log, logs\oil-micro.log, logs\frontend.log
echo.
echo   Tailing all logs (Ctrl+C to stop)...
echo ============================================
echo.

powershell -Command "Get-Content logs\general.log, logs\micro.log, logs\oil-micro.log -Wait -Tail 5"

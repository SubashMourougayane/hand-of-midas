@echo off
REM Hand Of Midas — Windows VPS Start Script
REM Starts Gold backend, Oil backend, and Frontend

echo ============================================
echo   HAND OF MIDAS - Starting All Services
echo ============================================
echo.

cd /d C:\hand-of-midas

REM Kill any existing processes on our ports
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5053" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5054" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5055" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [1/4] Starting Gold Macro Backend (port 5053)...
start /B cmd /c "cd /d C:\hand-of-midas && python -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 > logs\gold.log 2>&1"
echo       OK

echo [2/4] Starting Oil Backend (port 5054)...
start /B cmd /c "cd /d C:\hand-of-midas\backend-oil && python -m uvicorn main:app --host 0.0.0.0 --port 5054 > ..\logs\oil.log 2>&1"
echo       OK

echo [3/4] Starting Gold Micro Backend (port 5055)...
start /B cmd /c "cd /d C:\hand-of-midas\backend-micro && python -m uvicorn main:app --host 0.0.0.0 --port 5055 > ..\logs\micro.log 2>&1"
echo       OK

echo [4/4] Starting Frontend (port 3001)...
start /B cmd /c "cd /d C:\hand-of-midas\frontend && npx next start -p 3001 > ..\logs\frontend.log 2>&1"
echo       OK

echo.
echo ============================================
echo   ALL SYSTEMS ONLINE
echo ============================================
echo.
echo   Gold Macro: http://localhost:5053
echo   Oil:        http://localhost:5054
echo   Gold Micro: http://localhost:5055
echo   Frontend:   http://localhost:3001
echo.
echo   Logs: logs\gold.log, logs\oil.log, logs\micro.log, logs\frontend.log
echo.
echo   Tailing all logs (Ctrl+C to stop)...
echo ============================================
echo.

powershell -Command "Get-Content logs\gold.log, logs\oil.log, logs\micro.log -Wait -Tail 5"

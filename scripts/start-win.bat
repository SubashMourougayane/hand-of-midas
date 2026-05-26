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
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [1/3] Starting Gold Backend (port 5053)...
start /B cmd /c "cd /d C:\hand-of-midas && python -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 > logs\gold.log 2>&1"
echo       OK

echo [2/3] Starting Oil Backend (port 5054)...
start /B cmd /c "cd /d C:\hand-of-midas\backend-oil && python -m uvicorn main:app --host 0.0.0.0 --port 5054 > ..\logs\oil.log 2>&1"
echo       OK

echo [3/3] Starting Frontend (port 3001)...
start /B cmd /c "cd /d C:\hand-of-midas\frontend && npx next start -p 3001 > ..\logs\frontend.log 2>&1"
echo       OK

echo.
echo ============================================
echo   ALL SYSTEMS ONLINE
echo ============================================
echo.
echo   Gold:     http://localhost:5053
echo   Oil:      http://localhost:5054
echo   Frontend: http://localhost:3001
echo.
echo   Logs: logs\gold.log, logs\oil.log, logs\frontend.log
echo.
echo   Press any key to stop all services...
pause >nul

REM Stop all
taskkill /F /IM "python.exe" >nul 2>&1
taskkill /F /IM "node.exe" >nul 2>&1
echo Services stopped.

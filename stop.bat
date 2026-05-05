@echo off
setlocal

cd /d "%~dp0"

call :stop_port 8000 "TripSage Backend"
if errorlevel 1 goto :error
call :stop_port 5173 "TripSage Frontend"
if errorlevel 1 goto :error

echo TripSage Agent stopped.
endlocal
exit /b 0

:error
echo Stop failed. Check the messages above.
endlocal
exit /b 1

:stop_port
set "TARGET_PORT=%~1"
set "TARGET_NAME=%~2"
set /a STOP_ATTEMPT=0

:stop_port_loop
set "TARGET_PID="

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$conn = Get-NetTCPConnection -State Listen -LocalPort %TARGET_PORT% -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { $conn.OwningProcess }"`) do (
  set "TARGET_PID=%%P"
)

if not defined TARGET_PID (
  echo %TARGET_NAME% is not running on port %TARGET_PORT%.
  exit /b 0
)

echo Stopping %TARGET_NAME% on port %TARGET_PORT% ^(PID %TARGET_PID%^)
taskkill /PID %TARGET_PID% /T /F >nul 2>&1
if errorlevel 1 (
  echo Failed to stop %TARGET_NAME% ^(PID %TARGET_PID%^).
  exit /b 1
)

set /a STOP_ATTEMPT+=1
timeout /t 1 >nul

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$conn = Get-NetTCPConnection -State Listen -LocalPort %TARGET_PORT% -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { $conn.OwningProcess }"`) do (
  set "TARGET_PID=%%P"
)

if not defined TARGET_PID (
  echo %TARGET_NAME% stopped.
  exit /b 0
)

if %STOP_ATTEMPT% GEQ 5 (
  echo %TARGET_NAME% is still listening on port %TARGET_PORT%.
  exit /b 1
)

goto :stop_port_loop

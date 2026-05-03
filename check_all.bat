@echo off
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [FAIL] backend virtualenv was not found.
  echo Run start.bat first.
  endlocal
  exit /b 1
)

echo Running TripSage delivery checks...
call backend\.venv\Scripts\python.exe -m app.scripts.check_delivery
set RESULT=%ERRORLEVEL%

if not "%RESULT%"=="0" (
  echo Delivery checks failed.
  endlocal
  exit /b %RESULT%
)

echo Delivery checks passed.
endlocal
exit /b 0

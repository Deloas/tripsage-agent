@echo off
setlocal EnableExtensions

rem TripSage Agent one-click startup script.
rem Keep this file ASCII-only because Windows cmd can misread UTF-8 comments or JSON-like text.

cd /d "%~dp0"
set "ROOT_DIR=%cd%"

if not exist "backend\.env" (
  if exist "backend\.env.example" (
    copy /Y "backend\.env.example" "backend\.env" >nul
    echo Created backend\.env. Fill DeepSeek and Amap API keys when needed.
  ) else (
    echo Missing backend\.env.example.
    goto :error
  )
)

if not exist "frontend\.env" (
  if exist "frontend\.env.example" (
    copy /Y "frontend\.env.example" "frontend\.env" >nul
    echo Created frontend\.env.
  ) else (
    echo Missing frontend\.env.example.
    goto :error
  )
)

if not exist "mcp_servers.json" (
  if exist "mcp_servers.example.json" (
    copy /Y "mcp_servers.example.json" "mcp_servers.json" >nul
    echo Created mcp_servers.json. Fill 12306 MCP settings when needed.
  ) else (
    echo Missing mcp_servers.example.json.
    goto :error
  )
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv "backend\.venv"
  if errorlevel 1 goto :error
)

echo Installing backend dependencies...
call "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
call "backend\.venv\Scripts\pip.exe" install -e "backend"
if errorlevel 1 goto :error

echo Initializing database and built-in guide data...
pushd "backend"
call ".venv\Scripts\python.exe" -m app.scripts.init_db
if errorlevel 1 goto :error_popd
call ".venv\Scripts\python.exe" -m app.scripts.seed_guides
if errorlevel 1 goto :error_popd
popd

echo Installing frontend dependencies...
pushd "frontend"
if not exist "node_modules" (
  call npm install
  if errorlevel 1 goto :error_popd
)
popd

call :is_port_listening 8000
if errorlevel 1 (
  echo Starting backend at http://127.0.0.1:8000
  start "TripSage Backend" cmd /k "cd /d ""%ROOT_DIR%\backend"" && "".venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
) else (
  echo Backend already running at http://127.0.0.1:8000
)

call :is_port_listening 5173
if errorlevel 1 (
  echo Starting frontend at http://127.0.0.1:5173
  start "TripSage Frontend" cmd /k "cd /d ""%ROOT_DIR%\frontend"" && npm run dev"
) else (
  echo Frontend already running at http://127.0.0.1:5173
)

timeout /t 3 >nul
start "" "http://127.0.0.1:5173"

echo TripSage Agent started.
endlocal
exit /b 0

:is_port_listening
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -State Listen -LocalPort %1 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:error_popd
popd

:error
echo Startup failed. Check the error above.
endlocal
exit /b 1

@echo off
setlocal

REM TripSage Agent 一键启动脚本。
REM 负责准备依赖、初始化数据，并启动后端与前端。

cd /d "%~dp0"

if not exist "backend\.env" (
  copy "backend\.env.example" "backend\.env" >nul
  echo Created backend\.env. Fill LLM, AMAP and MCP settings when needed.
)

if not exist "frontend\.env" (
  copy "frontend\.env.example" "frontend\.env" >nul
  echo Created frontend\.env.
)

if not exist "mcp_servers.json" (
  copy "mcp_servers.example.json" "mcp_servers.json" >nul
  echo Created mcp_servers.json. Fill ModelScope 12306 MCP settings when needed.
)

if not exist "backend\.venv" (
  echo Creating backend virtual environment...
  python -m venv backend\.venv
  if errorlevel 1 goto :error
)

echo Installing backend dependencies...
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
call backend\.venv\Scripts\pip.exe install -e backend
if errorlevel 1 goto :error

echo Initializing database and built-in guide data...
pushd backend
call .venv\Scripts\python.exe -m app.scripts.init_db
if errorlevel 1 goto :error_popd
call .venv\Scripts\python.exe -m app.scripts.seed_guides
if errorlevel 1 goto :error_popd
popd

echo Installing frontend dependencies...
pushd frontend
if not exist "node_modules" (
  call npm install
  if errorlevel 1 goto :error_popd
)
popd

echo Starting backend at http://127.0.0.1:8000
start "TripSage Backend" cmd /k "cd /d %cd%\backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo Starting frontend at http://127.0.0.1:5173
start "TripSage Frontend" cmd /k "cd /d %cd%\frontend && npm run dev"

timeout /t 3 >nul
start http://127.0.0.1:5173

echo TripSage Agent started.
endlocal
exit /b 0

:error_popd
popd

:error
echo Startup failed. Check the error above.
endlocal
exit /b 1

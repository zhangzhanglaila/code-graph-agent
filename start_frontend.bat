@echo off
echo Starting Why-Code-Agent Frontend...
echo.
echo [1/2] Starting FastAPI backend on port 8000...
start "API Server" cmd /c "cd /d %~dp0 && python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] Starting Vue dev server on port 5173...
cd /d %~dp0\frontend
call npm install
call npm run dev

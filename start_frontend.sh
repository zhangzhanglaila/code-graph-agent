#!/bin/bash
echo "Starting Why-Code-Agent Frontend..."
echo ""
echo "[1/2] Starting FastAPI backend on port 8000..."
cd "$(dirname "$0")"
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

echo "[2/2] Starting Vue dev server on port 5173..."
cd frontend
npm install
npm run dev

kill $API_PID

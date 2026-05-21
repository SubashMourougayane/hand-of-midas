#!/bin/bash
# GoldDigger — Start backend + frontend
cd "$(dirname "$0")"

echo "Starting GoldDigger..."
echo "  Backend: http://localhost:5053"
echo "  Frontend: http://localhost:3001"
echo ""

# Start backend
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 --reload &
BACKEND_PID=$!

# Start frontend
cd frontend && npm run dev -- -p 3001 &
FRONTEND_PID=$!

cd ..

echo "PIDs: backend=$BACKEND_PID, frontend=$FRONTEND_PID"
echo "Press Ctrl+C to stop both"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait

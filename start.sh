#!/bin/bash
# GoldDigger + OilMiner — Start all services
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Starting GoldDigger + OilMiner..."
echo "  Gold Backend: http://localhost:5053"
echo "  Oil Backend:  http://localhost:5054"
echo "  Frontend:     http://localhost:3001"
echo ""

# Start Gold backend
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 --timeout-keep-alive 300 &
GOLD_PID=$!

# Start Oil backend
cd "$DIR/backend-oil"
python3 -m uvicorn main:app --host 0.0.0.0 --port 5054 --timeout-keep-alive 300 &
OIL_PID=$!
cd "$DIR"

# Wait for backends to load data
echo "  Waiting for data to load..."
sleep 10

# Start frontend
cd "$DIR/frontend"
npm run dev -- -p 3001 &
FRONTEND_PID=$!
cd "$DIR"

echo "PIDs: gold=$GOLD_PID, oil=$OIL_PID, frontend=$FRONTEND_PID"
echo "Press Ctrl+C to stop all"

trap "kill $GOLD_PID $OIL_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait

#!/usr/bin/env bash
set -e

echo "🔥 [Agni All-In-One] Booting integrated stack..."

export PYTHONPATH="/app/apps/api-gateway:/app/apps/agent-daemon:/app/packages/shared-protocol:${PYTHONPATH:-}"

# 1. Start background Redis server
echo "📦 Starting Redis Server (Port 6379)..."
redis-server --daemonize yes --loglevel warning

# Wait for redis ping
until redis-cli ping > /dev/null 2>&1; do
  echo "Waiting for Redis to become ready..."
  sleep 1
done
echo "✅ Redis is online."

# 2. Run Database Seeding
echo "🌱 Running Database Seeding (seed.py)..."
python seed.py || echo "Seeding completed or already initialized."

# 3. Start Agni API Gateway in background
echo "🚀 Starting Agni API Gateway on port 8000..."
uvicorn api_gateway.main:app --host 0.0.0.0 --port 8000 --app-dir apps/api-gateway &
API_PID=$!

# 4. Start Agni Agent Daemon in background
echo "🤖 Starting Agni Agent Daemon on port 9000..."
python apps/agent-daemon/agent_daemon/main.py &
DAEMON_PID=$!

# 5. Start Agni Web Dashboard
echo "💻 Starting Agni Web Dashboard on port 3000..."
cd /app/apps/web-dashboard
node_modules/.bin/next start -p 3000 &
WEB_PID=$!

echo "✨ All services running! Dashboard: http://localhost:3000 | API: http://localhost:8000"

# Trap exit signals to gracefully terminate
trap "kill -TERM $API_PID $DAEMON_PID $WEB_PID" SIGINT SIGTERM
wait -n

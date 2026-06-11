#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

PORT="${PORT:-53000}"
API_PORT="${API_PORT:-58000}"

# Free the port if something else is listening
PID=$(lsof -ti:"$PORT" 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Port $PORT in use by PID $PID — killing."
  kill -9 $PID 2>/dev/null || true
fi

cd "$FRONTEND_DIR"

# Activate the bundled pnpm via corepack (Node 20+ ships corepack).
corepack enable >/dev/null 2>&1 || true

if [ ! -d node_modules ]; then
  echo "Installing frontend dependencies..."
  pnpm install
fi

export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$API_PORT}"

echo "Starting Next.js dev server on port $PORT (proxying API to $NEXT_PUBLIC_API_URL)..."
exec pnpm run dev --port "$PORT"

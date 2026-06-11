#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

PORT="${PORT:-58000}"

# Free the port if something else is listening
PID=$(lsof -ti:"$PORT" 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Port $PORT in use by PID $PID — killing."
  kill -9 $PID 2>/dev/null || true
fi

cd "$BACKEND_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating Python venv at $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

if [ ! -f "$VENV_DIR/.deps-installed" ] || [ "$BACKEND_DIR/requirements.txt" -nt "$VENV_DIR/.deps-installed" ]; then
  echo "Installing backend dependencies..."
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  touch "$VENV_DIR/.deps-installed"
fi

# Load root .env if it exists so CB / OpenAI / Capella creds propagate
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

echo "Starting FastAPI dev server on port $PORT..."
exec uvicorn main:app --reload --port "$PORT"

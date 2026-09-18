#!/usr/bin/env bash
# Start the JARVIS bridge and the HUD together (Linux / macOS / WSL).
#
#   ./scripts/dev.sh            # bridge on 8770, HUD on 5173
#   ./scripts/dev.sh --no-hud   # API only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${JARVIS_PY:-python3}"
if [ -d .venv ]; then
  PY="$ROOT/.venv/bin/python"
fi

BRIDGE_HOST="${JARVIS_HOST:-127.0.0.1}"
BRIDGE_PORT="${JARVIS_PORT:-8770}"
HUD_PORT="${PORT:-5173}"

cleanup() {
  [ -n "${BRIDGE_PID:-}" ] && kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "▶ bridge  http://${BRIDGE_HOST}:${BRIDGE_PORT}"
"$PY" -m jarvis serve --host "$BRIDGE_HOST" --port "$BRIDGE_PORT" &
BRIDGE_PID=$!

if [ "${1:-}" = "--no-hud" ]; then
  wait "$BRIDGE_PID"
  exit 0
fi

if [ ! -d hud/node_modules ]; then
  echo "▶ installing HUD dependencies"
  (cd hud && npm install)
fi

echo "▶ hud     http://127.0.0.1:${HUD_PORT}"
(cd hud && JARVIS_BRIDGE="http://127.0.0.1:${BRIDGE_PORT}" npm run dev -- --host 127.0.0.1 --port "$HUD_PORT")

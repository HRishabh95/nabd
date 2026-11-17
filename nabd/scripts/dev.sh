#!/usr/bin/env bash
# Start the API (127.0.0.1:8000) and the web app (localhost:5173) together; Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
# On exit (Ctrl+C, an error or a closed terminal) stop everything this script started: its whole process group.
trap 'trap - EXIT INT TERM; kill 0 2>/dev/null; wait' EXIT INT TERM
(cd backend && exec uv run nabd serve --port 8000) &
until curl -sf -m 2 http://127.0.0.1:8000/api/system/health >/dev/null; do sleep 1; done
echo "API ready on http://127.0.0.1:8000 · the web app address follows (normally http://localhost:5173)"
cd frontend && npm run dev -- --port 5173

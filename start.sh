#!/bin/bash
# FinSight AI - Railway Startup Script
# Handles dynamic PORT environment variable from Railway and logs shutdown signals

set -euo pipefail

log() {
  # shellcheck disable=SC2039
  printf "[start.sh] %s\n" "$1"
}

# Capture termination signals so we can see why the process is exiting on Railway
on_term() {
  log "Received shutdown signal (SIGTERM) from platform – exiting uvicorn"
}
trap on_term TERM

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}
log "Starting uvicorn on port ${PORT}"

# Start uvicorn with the correct port
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

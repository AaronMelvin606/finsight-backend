#!/bin/bash
# FinSight AI - Railway Startup Script
# Handles dynamic PORT environment variable from Railway and logs shutdown signals

set -euo pipefail

log() {
  printf "[start.sh] %s\n" "$1"
}

PORT=${PORT:-8080}
UVICORN_ARGS=(
  --host 0.0.0.0
  --port "$PORT"
  --proxy-headers
  --forwarded-allow-ips "*"
  --timeout-keep-alive 75
)

start_uvicorn() {
  log "Starting uvicorn on port ${PORT} with proxy headers enabled"
  uvicorn app.main:app "${UVICORN_ARGS[@]}" &
  UVICORN_PID=$!
  log "uvicorn started with PID ${UVICORN_PID}"
}

shutdown() {
  log "Received shutdown signal from platform – forwarding to uvicorn"
  if kill -0 "${UVICORN_PID:-0}" 2>/dev/null; then
    kill -TERM "$UVICORN_PID"
    wait "$UVICORN_PID" || true
  fi
  exit 0
}

trap shutdown TERM INT

start_uvicorn
wait "$UVICORN_PID"
EXIT_CODE=$?
log "uvicorn exited with status ${EXIT_CODE}"
exit "$EXIT_CODE"

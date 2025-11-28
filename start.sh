#!/bin/bash
# FinSight AI - Railway Startup Script
# Handles dynamic PORT environment variable from Railway

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

# Start uvicorn with the correct port
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

#!/bin/bash
# FinSight AI - Railway Startup Script
# Handles dynamic PORT environment variable from Railway

echo "=========================================="
echo "FinSight AI Backend - Startup Script"
echo "=========================================="

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}
echo "Using PORT: $PORT"

# Check environment variables
echo "Checking environment configuration..."
if [ -z "$DATABASE_URL" ]; then
    echo "WARNING: DATABASE_URL not set!"
else
    echo "DATABASE_URL: configured ✓"
fi

if [ -z "$SECRET_KEY" ]; then
    echo "WARNING: SECRET_KEY not set!"
else
    echo "SECRET_KEY: configured ✓"
fi

echo "=========================================="
echo "Starting Uvicorn server on 0.0.0.0:$PORT"
echo "=========================================="

# Start uvicorn with the correct port
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --log-level info

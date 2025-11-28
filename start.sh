#!/bin/bash
# FinSight AI - Railway Startup Script
# Handles dynamic PORT environment variable from Railway

set -e  # Exit on error

echo "=========================================="
echo "FinSight AI Backend Starting..."
echo "=========================================="
echo "Environment: ${ENVIRONMENT:-production}"
echo "PORT: ${PORT:-8000}"
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo "=========================================="

# Get PORT from environment variable, default to 8000 if not set
PORT=${PORT:-8000}

echo "Starting Uvicorn on port $PORT..."
echo "Use exec to replace shell with uvicorn process..."

# Start uvicorn with the correct port
# Using exec ensures uvicorn becomes PID 1 and receives signals properly
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --log-level info

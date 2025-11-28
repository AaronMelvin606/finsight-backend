# Railway Container Issue - Need Help Diagnosing

## Problem Summary
A FastAPI backend deployed on Railway starts successfully, passes the health check, and then shuts down cleanly about four seconds later. Once the container stops, the service URL becomes unreachable even though Uvicorn initially reports that it is running.

## Tech Stack
- FastAPI + Uvicorn
- Neon PostgreSQL
- Railway + Docker

## Current Behavior (Logs)
```
Starting Container
✓ Database engine created successfully
✓ Settings loaded successfully
✓ Database tables created successfully
✓ Application startup complete
INFO: Uvicorn running on http://0.0.0.0:8080
INFO: 100.64.0.2:37361 - "GET /health HTTP/1.1" 200 OK
Stopping Container ← PROBLEM: Container stops here!
INFO: Shutting down
INFO: Application shutdown complete
```

## Key Configuration
### `railway.toml`
```toml
[build]

[deploy]
startCommand = "./start.sh"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

### `start.sh`
```bash
#!/bin/bash
PORT=${PORT:-8000}
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

## What Works
- ✅ Container starts
- ✅ Database connects (Neon PostgreSQL)
- ✅ Tables created
- ✅ Health check passes (200 OK)
- ✅ Uvicorn reports it is running

## What Fails
- ❌ Container stops ~4 seconds after the health check
- ❌ No error messages — shutdown is clean
- ❌ Service URL becomes unreachable after the stop

## Troubleshooting Attempts So Far
- Added explicit `startCommand` to `railway.toml`
- Added `restartPolicyType = "ON_FAILURE"`
- Simplified the health check (removed DB queries)
- Added timeouts to DB operations
- Verified `PORT` environment variable handling

## Questions for Further Diagnosis
1. Why is Railway stopping the container after a successful health check?
2. Is there a `railway.toml` configuration issue?
3. Could Railway be treating this as a one-time job instead of a web service?
4. Are there Railway-specific requirements missing from the setup?
5. Is there an issue with how Uvicorn is being started?

## Need
Root cause analysis and specific Railway configuration changes that will keep the container running persistently.

---

**Usage**: Copy this prompt into ChatGPT (or another helper) to debug the Railway container shutdown. The prompt captures the observed behavior, configuration, and questions to investigate.

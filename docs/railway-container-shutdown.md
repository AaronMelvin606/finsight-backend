# Railway container shutdown diagnosis

Recent deployments show the service starting normally, passing the `/health` probe, and then receiving a shutdown signal a few seconds later. The Uvicorn shutdown logs indicate the platform is sending `SIGTERM` (exit code 0) rather than the process crashing.

## What we changed
- Added signal trapping in `start.sh` so logs clearly record when the platform sends `SIGTERM`. This will confirm whether Railway is terminating the container after the health check even though the app is still healthy.
- The startup script now logs the port the app binds to, making it easier to confirm the service is listening on the `$PORT` Railway injects.

## Next steps to verify on Railway
1. Redeploy and check build logs for the new `[start.sh] Starting uvicorn on port <PORT>` line to verify the runtime port matches Railway's expectation.
2. When the container stops, look for a `[start.sh] Received shutdown signal (SIGTERM) from platform` line to confirm the orchestrator is ending the process. If that appears, the root cause is platform-driven termination rather than an application crash.
3. If a SIGTERM is logged immediately after the health check, open a Railway support ticket with the timestamp and container ID; provide the log snippet to show the platform is stopping the service despite a healthy probe.
4. If no SIGTERM line appears, the app itself is exiting; in that case gather the surrounding Uvicorn logs for further investigation.

These steps should pinpoint whether the shutdown is caused by Railway orchestration or by the application process exiting on its own.

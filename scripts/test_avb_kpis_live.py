#!/usr/bin/env python3
"""
Test GET /api/v1/reports/avb-kpis against the live FinSight backend.
Uses FINSIGHT_EMAIL and FINSIGHT_PASSWORD to get a JWT, then calls avb-kpis
and prints the full JSON response for verification.

  export FINSIGHT_EMAIL=your@email.com
  export FINSIGHT_PASSWORD=yourpassword
  python3 scripts/test_avb_kpis_live.py

Optional query params (pass as env or leave default):
  FINSIGHT_PERIOD_START=2025-04-01
  FINSIGHT_PERIOD_END=2026-03-15
"""
import os
import sys
import json

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

BASE_URL = os.environ.get("FINSIGHT_BASE_URL", "https://finsight-backend-520129376224.us-central1.run.app")
EMAIL = os.environ.get("FINSIGHT_EMAIL")
PASSWORD = os.environ.get("FINSIGHT_PASSWORD")
PERIOD_START = os.environ.get("FINSIGHT_PERIOD_START")
PERIOD_END = os.environ.get("FINSIGHT_PERIOD_END")


def main():
    if not EMAIL or not PASSWORD:
        print("Set FINSIGHT_EMAIL and FINSIGHT_PASSWORD environment variables.")
        sys.exit(1)

    # 1) Get token
    login_url = f"{BASE_URL}/api/v1/auth/login/json"
    r = requests.post(login_url, json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    token = data.get("access_token")
    if not token:
        print("Login response missing access_token:", data)
        sys.exit(1)
    print("Got access token.")

    # 2) GET avb-kpis
    url = f"{BASE_URL}/api/v1/reports/avb-kpis"
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if PERIOD_START:
        params["period_start"] = PERIOD_START
    if PERIOD_END:
        params["period_end"] = PERIOD_END

    r2 = requests.get(url, headers=headers, params=params or None, timeout=30)
    print(f"avb-kpis response: {r2.status_code}")
    if r2.status_code != 200:
        print(r2.text)
        sys.exit(1)

    body = r2.json()
    print(json.dumps(body, indent=2))
    print("Done.")


if __name__ == "__main__":
    main()

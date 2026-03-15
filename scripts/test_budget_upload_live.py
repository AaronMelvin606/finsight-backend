#!/usr/bin/env python3
"""
Test POST /api/v1/reports/budget/upload against the live FinSight backend.
Uses FINSIGHT_EMAIL and FINSIGHT_PASSWORD env vars to get a JWT, then uploads
test_budget_upload.csv. Run from repo root after deploy.

  export FINSIGHT_EMAIL=your@email.com
  export FINSIGHT_PASSWORD=yourpassword
  python scripts/test_budget_upload_live.py
"""
import os
import sys

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

BASE_URL = os.environ.get("FINSIGHT_BASE_URL", "https://finsight-backend-520129376224.us-central1.run.app")
EMAIL = os.environ.get("FINSIGHT_EMAIL")
PASSWORD = os.environ.get("FINSIGHT_PASSWORD")
CSV_PATH = os.environ.get("FINSIGHT_BUDGET_CSV", "test_budget_upload.csv")


def main():
    if not EMAIL or not PASSWORD:
        print("Set FINSIGHT_EMAIL and FINSIGHT_PASSWORD environment variables.")
        sys.exit(1)
    if not os.path.isfile(CSV_PATH):
        print(f"CSV not found: {CSV_PATH}")
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

    # 2) Upload CSV
    upload_url = f"{BASE_URL}/api/v1/reports/budget/upload"
    with open(CSV_PATH, "rb") as f:
        files = {"file": (os.path.basename(CSV_PATH), f, "text/csv")}
        headers = {"Authorization": f"Bearer {token}"}
        r2 = requests.post(upload_url, files=files, headers=headers, params={}, timeout=60)
    print(f"Upload response: {r2.status_code}")
    print(r2.text)
    if r2.status_code != 200:
        sys.exit(1)
    print("Done.")

    # 3) Optional: call avb-kpis and print response for verification
    if os.environ.get("FINSIGHT_TEST_AVB_AFTER_UPLOAD"):
        print("\n--- GET /reports/avb-kpis ---")
        kpis_url = f"{BASE_URL}/api/v1/reports/avb-kpis"
        r3 = requests.get(kpis_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        print(f"avb-kpis: {r3.status_code}")
        if r3.status_code == 200:
            import json
            print(json.dumps(r3.json(), indent=2))
        else:
            print(r3.text)


if __name__ == "__main__":
    main()

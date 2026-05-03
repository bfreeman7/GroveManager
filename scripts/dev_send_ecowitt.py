#!/usr/bin/env python3
"""
Send synthetic Ecowitt form-encoded payload(s) to an OrchardMonitor endpoint.

Usage:
  python scripts/dev_send_ecowitt.py http://localhost:8080/ecowitt [--count 1]
"""

import argparse
from datetime import datetime, timezone

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Ecowitt ingest URL, e.g. http://localhost:8080/ecowitt")
    p.add_argument("--count", type=int, default=1)
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    base_payload = {
        "dateutc": now.strftime("%Y-%m-%d %H:%M:%S"),
        "soilmoisture1": "41",
        "tempf": "70.1",
        "humidity": "52",
        "stationtype": "GW1100A",  # ignored by server filter
    }

    for i in range(args.count):
        payload = dict(base_payload)
        payload["soilmoisture1"] = str(41 + i)
        r = requests.post(args.url, data=payload, timeout=10)
        r.raise_for_status()
        print(f"sent {i+1}/{args.count}: status={r.status_code}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


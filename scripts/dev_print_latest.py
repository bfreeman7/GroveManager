#!/usr/bin/env python3
"""
Print a quick local status view from the daily parquet store.

Usage:
  DATA_STORAGE_PATH=.local-data python scripts/dev_print_latest.py
"""

import os
from datetime import datetime, timezone

import pandas as pd


def main() -> int:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.getenv("DATA_STORAGE_PATH", os.path.join(project_root, "data"))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parquet_path = os.path.join(data_path, "measurements", f"{date_str}.parquet")

    if not os.path.exists(parquet_path):
        print(f"No parquet found for today at {parquet_path}")
        return 1

    df = pd.read_parquet(parquet_path).sort_values("timestamp").reset_index(drop=True)
    last = df.tail(1).iloc[0].to_dict()

    ts = last.get("timestamp")
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    print(f"parquet: {parquet_path}")
    print(f"rows: {len(df)}")
    print(f"last_timestamp: {ts}")

    # Print a few high-signal keys if present
    keys = [k for k in ["soilmoisture1", "tempf", "humidity"] if k in last]
    if keys:
        print("latest:")
        for k in keys:
            print(f"  {k}: {last.get(k)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


#!/usr/bin/env python3
"""
Validate and display moisture data from OrchardMonitor parquet files.
Usage: python scripts/check_moisture.py [data_path] [date]
  data_path: defaults to ../data or DATA_STORAGE_PATH env
  date: YYYY-MM-DD, defaults to today
"""

import os
import sys
from datetime import datetime, timezone

# Allow running from project root or scripts/
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))

def main():
    data_path = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATA_STORAGE_PATH", os.path.join(project_root, "data"))
    date_str = sys.argv[2] if len(sys.argv) > 2 else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    measurements_dir = os.path.join(data_path, "measurements")
    parquet_path = os.path.join(measurements_dir, f"{date_str}.parquet")

    if not os.path.exists(parquet_path):
        print(f"File not found: {parquet_path}")
        sys.exit(1)

    import pandas as pd

    df = pd.read_parquet(parquet_path)
    moisture_cols = [c for c in df.columns if "soilmoisture" in c.lower()]
    if not moisture_cols:
        print(f"No moisture columns in {parquet_path}")
        print(f"Available columns: {list(df.columns)}")
        sys.exit(1)

    print(f"File: {parquet_path}")
    print(f"Rows: {len(df)}")
    print()

    for col in sorted(moisture_cols):
        vals = df[col].dropna()
        if len(vals) == 0:
            print(f"  {col}: (no data)")
        else:
            latest = vals.iloc[-1]
            mn, mx = vals.min(), vals.max()
            print(f"  {col}: latest={latest:.0f}%  min={mn:.0f}%  max={mx:.0f}%  (n={len(vals)})")

    print()
    print("Last 3 readings:")
    cols = ["timestamp"] + sorted(moisture_cols)
    cols = [c for c in cols if c in df.columns]
    print(df[cols].tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

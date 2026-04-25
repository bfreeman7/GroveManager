#!/usr/bin/env python3
"""
Export all OrchardMonitor parquet files to a single CSV.
Usage: python scripts/export_to_csv.py [data_path] [output_path]
  data_path: defaults to ../data or DATA_STORAGE_PATH env
  output_path: defaults to data/measurements/all_measurements.csv
"""

import glob
import os
import sys

import pandas as pd

# Allow running from project root or scripts/
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    data_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.getenv("DATA_STORAGE_PATH", os.path.join(project_root, "data"))
    )
    output_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else os.path.join(data_path, "measurements", "all_measurements.csv")
    )

    measurements_dir = os.path.join(data_path, "measurements")
    pattern = os.path.join(measurements_dir, "*.parquet")
    parquet_files = sorted(glob.glob(pattern))

    if not parquet_files:
        print(f"No parquet files found in {measurements_dir}")
        sys.exit(1)

    dfs = []
    for path in parquet_files:
        df = pd.read_parquet(path)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True, join="outer")
    combined = combined.sort_values("timestamp").reset_index(drop=True)

    combined.to_csv(output_path, index=False)
    print(f"Exported {len(parquet_files)} parquet files ({len(combined)} rows) to {output_path}")


if __name__ == "__main__":
    main()

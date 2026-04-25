"""
Simple daily parquet storage for measurements.

One file per day: data/measurements/YYYY-MM-DD.parquet
Appends new rows to the existing file for that day.
"""

import os
import pandas as pd
import pyarrow.parquet as pq
from datetime import datetime, timezone
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MeasurementStore:
    """Appends measurements to daily parquet files."""

    def __init__(self, base_path: str = "data"):
        self.measurements_path = os.path.join(base_path, "measurements")
        os.makedirs(self.measurements_path, exist_ok=True)

    def _get_daily_path(self, timestamp: datetime) -> str:
        """Path for the day's parquet file: measurements/YYYY-MM-DD.parquet"""
        date_str = timestamp.strftime("%Y-%m-%d")
        return os.path.join(self.measurements_path, f"{date_str}.parquet")

    def store_reading(self, data: Dict, timestamp: Optional[datetime] = None):
        """
        Append a single reading to the day's parquet file.

        Args:
            data: Dictionary of sensor readings (e.g. from Ecowitt)
            timestamp: Timestamp for the reading (defaults to UTC now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        file_path = self._get_daily_path(timestamp)

        # Build record with timestamp first
        record = {"timestamp": timestamp}
        for key, value in data.items():
            if value is None or value == "":
                record[key] = None
            else:
                try:
                    record[key] = float(value)
                except (ValueError, TypeError):
                    record[key] = str(value)

        new_df = pd.DataFrame([record])

        if os.path.exists(file_path):
            existing_df = pd.read_parquet(file_path)
            all_columns = set(existing_df.columns) | set(new_df.columns)
            for col in all_columns:
                if col not in existing_df.columns:
                    existing_df[col] = pd.NA
                if col not in new_df.columns:
                    new_df[col] = pd.NA
            ordered = ["timestamp"] + sorted(c for c in all_columns if c != "timestamp")
            combined = pd.concat(
                [existing_df[ordered], new_df[ordered]], ignore_index=True, sort=False
            )
        else:
            ordered = ["timestamp"] + sorted(c for c in new_df.columns if c != "timestamp")
            combined = new_df[ordered]

        combined.to_parquet(file_path, compression="snappy", index=False)
        logger.debug(f"Stored reading to {file_path}")

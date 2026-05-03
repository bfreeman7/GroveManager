"""
Simple daily parquet storage for measurements.

One file per day: data/measurements/YYYY-MM-DD.parquet
Appends new rows to the existing file for that day.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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

        # Avoid pandas' read_parquet/to_parquet here; on long-running processes (Pi) we saw
        # file descriptor pressure leading to Errno 24. Use pyarrow directly with no mmap.
        new_tbl = pa.Table.from_pandas(new_df, preserve_index=False)

        if os.path.exists(file_path):
            existing_tbl = pq.read_table(file_path, memory_map=False)
            unified_schema = pa.unify_schemas([existing_tbl.schema, new_tbl.schema])

            def _align(tbl: pa.Table, schema: pa.Schema) -> pa.Table:
                cols = []
                n = tbl.num_rows
                for field in schema:
                    if field.name in tbl.schema.names:
                        arr = tbl[field.name]
                        if not arr.type.equals(field.type):
                            arr = arr.cast(field.type, safe=False)
                        cols.append(arr)
                    else:
                        cols.append(pa.nulls(n, type=field.type))
                return pa.table(cols, schema=schema)

            existing_tbl = _align(existing_tbl, unified_schema)
            new_tbl = _align(new_tbl, unified_schema)
            combined_tbl = pa.concat_tables([existing_tbl, new_tbl])
        else:
            combined_tbl = new_tbl

        pq.write_table(combined_tbl, file_path, compression="snappy")
        logger.debug(f"Stored reading to {file_path}")


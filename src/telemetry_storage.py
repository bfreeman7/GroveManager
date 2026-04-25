"""
Telemetry storage module for saving Ecowitt sensor data to Parquet files.

Stores data in hourly chunks with dynamic schema handling to accommodate
changing sensor configurations.
"""

import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set
import logging

from catalog import Catalog

logger = logging.getLogger(__name__)


class TelemetryStorage:
    """Manages storage of telemetry data in hourly Parquet files."""
    
    def __init__(self, base_path: str = "data", catalog: Optional[Catalog] = None):
        """
        Initialize telemetry storage.
        
        Args:
            base_path: Base directory for data storage
            catalog: Catalog instance (creates new one if not provided)
        """
        self.base_path = base_path
        self.raw_path = os.path.join(base_path, "raw")
        self.catalog = catalog or Catalog(os.path.join(base_path, "catalog.db"))
        
        # Ensure directories exist
        os.makedirs(self.raw_path, exist_ok=True)
    
    def get_current_hour_file_path(self, timestamp: datetime) -> str:
        """
        Get the file path for the current hour.
        
        Args:
            timestamp: Timestamp to determine the hour
            
        Returns:
            Full path to the parquet file for this hour
        """
        # Format: data/raw/YYYY/MM/DD/raw_YYYYMMDD_HH.parquet
        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%m")
        day = timestamp.strftime("%d")
        hour = timestamp.strftime("%H")
        
        date_dir = os.path.join(self.raw_path, year, month, day)
        os.makedirs(date_dir, exist_ok=True)
        
        filename = f"raw_{timestamp.strftime('%Y%m%d')}_{hour}.parquet"
        return os.path.join(date_dir, filename)
    
    def _ensure_schema_compatibility(self, file_path: str, new_columns: Set[str]) -> Optional[pa.Schema]:
        """
        Ensure schema compatibility when appending new data.
        
        If file exists, reads existing schema and merges with new columns.
        If file doesn't exist, creates a new schema.
        
        Args:
            file_path: Path to the parquet file
            new_columns: Set of column names in the new data
            
        Returns:
            PyArrow schema to use, or None if file doesn't exist
        """
        if not os.path.exists(file_path):
            return None
        
        try:
            # Read existing file to get schema
            existing_table = pq.read_table(file_path)
            existing_schema = existing_table.schema
            existing_columns = set(existing_schema.names)
            
            # Check if we need to add new columns
            missing_columns = new_columns - existing_columns
            
            if not missing_columns:
                # No new columns, use existing schema
                return existing_schema
            
            # Need to add new columns - create updated schema
            # For new columns, we'll use float64 (most numeric sensors) or string
            # We'll default to float64 and let pandas handle type inference
            new_fields = list(existing_schema)
            
            for col in missing_columns:
                # Default to float64 for numeric data, can be adjusted later
                new_fields.append(pa.field(col, pa.float64(), nullable=True))
            
            return pa.schema(new_fields)
        
        except Exception as e:
            logger.warning(f"Error reading existing schema from {file_path}: {e}")
            return None
    
    def _read_existing_data(self, file_path: str) -> Optional[pd.DataFrame]:
        """
        Read existing data from a parquet file.
        
        Args:
            file_path: Path to the parquet file
            
        Returns:
            DataFrame with existing data, or None if file doesn't exist
        """
        if not os.path.exists(file_path):
            return None
        
        try:
            return pd.read_parquet(file_path)
        except Exception as e:
            logger.warning(f"Error reading existing data from {file_path}: {e}")
            return None
    
    def store_reading(self, data: Dict, timestamp: Optional[datetime] = None):
        """
        Store a single sensor reading to the appropriate hourly file.
        
        Args:
            data: Dictionary of sensor readings (from Ecowitt)
            timestamp: Timestamp for the reading (defaults to UTC now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        # Ensure timestamp is timezone-aware (UTC)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        
        # Get file path for this hour
        file_path = self.get_current_hour_file_path(timestamp)
        
        # Prepare data for DataFrame
        # Add timestamp as first column
        record = {"timestamp": timestamp}
        
        # Convert all values to appropriate types
        # Ecowitt sends everything as strings, so we need to convert
        for key, value in data.items():
            if value is None or value == "":
                record[key] = None
            else:
                # Try to convert to float, fall back to string
                try:
                    # Try float first (most sensors are numeric)
                    record[key] = float(value)
                except (ValueError, TypeError):
                    # Keep as string if conversion fails
                    record[key] = str(value)
        
        # Create DataFrame from single record
        new_df = pd.DataFrame([record])
        
        # Get existing data if file exists
        existing_df = self._read_existing_data(file_path)
        
        if existing_df is not None:
            # Append to existing data
            # Ensure all columns are present in both DataFrames
            all_columns = set(existing_df.columns) | set(new_df.columns)
            
            # Add missing columns with NaN
            for col in all_columns:
                if col not in existing_df.columns:
                    existing_df[col] = pd.NA
                if col not in new_df.columns:
                    new_df[col] = pd.NA
            
            # Reorder columns consistently (timestamp first, then alphabetical)
            ordered_cols = ["timestamp"] + sorted([c for c in all_columns if c != "timestamp"])
            existing_df = existing_df[ordered_cols]
            new_df = new_df[ordered_cols]
            
            # Concatenate with sort=False to avoid FutureWarning
            combined_df = pd.concat([existing_df, new_df], ignore_index=True, sort=False)
        else:
            # New file - order columns (timestamp first, then alphabetical)
            ordered_cols = ["timestamp"] + sorted([c for c in new_df.columns if c != "timestamp"])
            combined_df = new_df[ordered_cols]
        
        # Write to parquet
        try:
            # Use PyArrow for better schema control
            table = pa.Table.from_pandas(combined_df)
            pq.write_table(table, file_path, compression='snappy')
            
            # Update catalog
            sensor_names = set(data.keys())
            self.catalog.record_file(file_path, sensor_names, "raw", timestamp)
            
            logger.debug(f"Stored reading to {file_path}")
        
        except Exception as e:
            logger.error(f"Error storing reading to {file_path}: {e}")
            raise
    
    def get_file_path(self, year: int, month: int, day: int, hour: int) -> str:
        """
        Get file path for a specific hour.
        
        Args:
            year: Year
            month: Month (1-12)
            day: Day (1-31)
            hour: Hour (0-23)
            
        Returns:
            Full path to the parquet file
        """
        timestamp = datetime(year, month, day, hour, tzinfo=timezone.utc)
        return self.get_current_hour_file_path(timestamp)
    
    def read_hour(self, year: int, month: int, day: int, hour: int) -> Optional[pd.DataFrame]:
        """
        Read data for a specific hour.
        
        Args:
            year: Year
            month: Month (1-12)
            day: Day (1-31)
            hour: Hour (0-23)
            
        Returns:
            DataFrame with the hour's data, or None if file doesn't exist
        """
        file_path = self.get_file_path(year, month, day, hour)
        return self._read_existing_data(file_path)

"""
Summarization module for aggregating hourly telemetry data.

Processes raw hourly Parquet files and creates summarized versions with
statistics (mean, min, max, count) per sensor.
"""

import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import logging

from catalog import Catalog
from telemetry_storage import TelemetryStorage

logger = logging.getLogger(__name__)


class Summarizer:
    """Handles summarization of hourly telemetry data."""
    
    def __init__(self, base_path: str = "data", 
                 storage: Optional[TelemetryStorage] = None,
                 catalog: Optional[Catalog] = None):
        """
        Initialize summarizer.
        
        Args:
            base_path: Base directory for data storage
            storage: TelemetryStorage instance (creates new one if not provided)
            catalog: Catalog instance (creates new one if not provided)
        """
        self.base_path = base_path
        self.summarized_path = os.path.join(base_path, "summarized")
        self.storage = storage or TelemetryStorage(base_path)
        self.catalog = catalog or self.storage.catalog
        
        # Ensure directories exist
        os.makedirs(self.summarized_path, exist_ok=True)
    
    def _get_summary_file_path(self, timestamp: datetime) -> str:
        """
        Get the file path for a summarized hour.
        
        Args:
            timestamp: Timestamp for the hour
            
        Returns:
            Full path to the summarized parquet file
        """
        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%m")
        day = timestamp.strftime("%d")
        hour = timestamp.strftime("%H")
        
        date_dir = os.path.join(self.summarized_path, year, month, day)
        os.makedirs(date_dir, exist_ok=True)
        
        filename = f"summary_{timestamp.strftime('%Y%m%d')}_{hour}.parquet"
        return os.path.join(date_dir, filename)
    
    def _calculate_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate statistics for each sensor column.
        
        Args:
            df: DataFrame with sensor data (must have 'timestamp' column)
            
        Returns:
            DataFrame with one row containing statistics for each sensor
        """
        if df.empty:
            return pd.DataFrame()
        
        # Exclude timestamp from statistics
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        if 'timestamp' in numeric_cols:
            numeric_cols.remove('timestamp')
        
        # If no numeric columns, return empty DataFrame
        if not numeric_cols:
            return pd.DataFrame()
        
        # Calculate statistics for each numeric column
        stats_dict = {}
        
        for col in numeric_cols:
            col_data = df[col].dropna()
            
            if len(col_data) == 0:
                # All NaN values
                stats_dict[f"{col}_mean"] = None
                stats_dict[f"{col}_min"] = None
                stats_dict[f"{col}_max"] = None
                stats_dict[f"{col}_count"] = 0
            else:
                stats_dict[f"{col}_mean"] = col_data.mean()
                stats_dict[f"{col}_min"] = col_data.min()
                stats_dict[f"{col}_max"] = col_data.max()
                stats_dict[f"{col}_count"] = len(col_data)
        
        # Add hour timestamp (start of the hour)
        if not df.empty and 'timestamp' in df.columns:
            hour_start = df['timestamp'].min().replace(minute=0, second=0, microsecond=0)
            stats_dict['hour_start'] = hour_start
        
        # Create DataFrame from statistics
        stats_df = pd.DataFrame([stats_dict])
        
        return stats_df
    
    def summarize_hour(self, year: int, month: int, day: int, hour: int) -> Optional[str]:
        """
        Summarize data for a specific hour.
        
        Args:
            year: Year
            month: Month (1-12)
            day: Day (1-31)
            hour: Hour (0-23)
            
        Returns:
            Path to the created summary file, or None if no data to summarize
        """
        # Read raw data for this hour
        raw_df = self.storage.read_hour(year, month, day, hour)
        
        if raw_df is None or raw_df.empty:
            logger.debug(f"No data to summarize for {year}-{month:02d}-{day:02d} {hour:02d}:00")
            return None
        
        # Calculate statistics
        summary_df = self._calculate_stats(raw_df)
        
        if summary_df.empty:
            logger.debug(f"No numeric data to summarize for {year}-{month:02d}-{day:02d} {hour:02d}:00")
            return None
        
        # Get output path
        timestamp = datetime(year, month, day, hour, tzinfo=timezone.utc)
        summary_path = self._get_summary_file_path(timestamp)
        
        # Write summary to parquet
        try:
            table = pa.Table.from_pandas(summary_df)
            pq.write_table(table, summary_path, compression='snappy')
            
            # Extract sensor names from summary columns (remove _mean, _min, _max, _count suffixes)
            sensor_names = set()
            for col in summary_df.columns:
                if col.endswith('_mean') or col.endswith('_min') or col.endswith('_max') or col.endswith('_count'):
                    sensor_name = col.rsplit('_', 1)[0]  # Remove suffix
                    sensor_names.add(sensor_name)
            
            # Update catalog
            self.catalog.record_file(summary_path, sensor_names, "summarized", timestamp)
            
            logger.info(f"Created summary for {year}-{month:02d}-{day:02d} {hour:02d}:00 at {summary_path}")
            return summary_path
        
        except Exception as e:
            logger.error(f"Error creating summary for {year}-{month:02d}-{day:02d} {hour:02d}:00: {e}")
            raise
    
    def process_pending_hours(self, lookback_hours: int = 24) -> List[str]:
        """
        Find and process any unprocessed hours.
        
        Checks for raw files that don't have corresponding summary files
        and processes them.
        
        Args:
            lookback_hours: How many hours back to check (default: 24)
            
        Returns:
            List of paths to created summary files
        """
        created_summaries = []
        now = datetime.now(timezone.utc)
        
        # Check each hour in the lookback period
        for hours_ago in range(lookback_hours, 0, -1):  # Start from oldest
            check_time = now - timedelta(hours=hours_ago)
            year = check_time.year
            month = check_time.month
            day = check_time.day
            hour = check_time.hour
            
            # Check if summary already exists
            summary_path = self._get_summary_file_path(check_time)
            if os.path.exists(summary_path):
                continue
            
            # Check if raw file exists
            raw_path = self.storage.get_file_path(year, month, day, hour)
            if not os.path.exists(raw_path):
                continue
            
            # Process this hour
            try:
                result = self.summarize_hour(year, month, day, hour)
                if result:
                    created_summaries.append(result)
            except Exception as e:
                logger.error(f"Error processing hour {year}-{month:02d}-{day:02d} {hour:02d}:00: {e}")
        
        return created_summaries
    
    def summarize_recent_hour(self) -> Optional[str]:
        """
        Summarize the previous hour (most recent completed hour).
        
        Returns:
            Path to the created summary file, or None if no data
        """
        # Get previous hour (current hour might still be receiving data)
        now = datetime.now(timezone.utc)
        previous_hour = now - timedelta(hours=1)
        
        return self.summarize_hour(
            previous_hour.year,
            previous_hour.month,
            previous_hour.day,
            previous_hour.hour
        )

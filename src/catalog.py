"""
Catalog system for tracking telemetry files and sensors.

Maintains a SQLite database that tracks:
- File metadata (path, timestamp, type, sensor count)
- Sensor registry (name, first_seen, last_seen, data_type)
- File-sensor mappings
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set


class Catalog:
    """Manages the SQLite catalog for telemetry files and sensors."""
    
    def __init__(self, db_path: str = "data/catalog.db"):
        """
        Initialize the catalog.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self.initialize()
    
    def _ensure_db_directory(self):
        """Ensure the directory for the database exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    def _get_connection(self, timeout: float = 5.0) -> sqlite3.Connection:
        """
        Get a database connection.
        
        Args:
            timeout: Timeout in seconds for database operations
        """
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def initialize(self):
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Files table: tracks parquet files
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_type TEXT NOT NULL,  -- 'raw' or 'summarized'
                timestamp TEXT NOT NULL,  -- ISO format datetime
                sensor_count INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Sensors table: tracks individual sensors
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                data_type TEXT,  -- 'numeric', 'string', etc.
                first_seen TEXT NOT NULL,  -- ISO format datetime
                last_seen TEXT NOT NULL,   -- ISO format datetime
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # File-sensor mapping table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                sensor_id INTEGER NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (sensor_id) REFERENCES sensors(id) ON DELETE CASCADE,
                UNIQUE(file_id, sensor_id)
            )
        """)
        
        # Create indexes for better query performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_timestamp ON files(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_sensors_file ON file_sensors(file_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_sensors_sensor ON file_sensors(sensor_id)")
        
        conn.commit()
        conn.close()
    
    def record_file(self, file_path: str, sensors: Set[str], file_type: str, timestamp: Optional[datetime] = None):
        """
        Record a file and its sensors in the catalog.
        
        Args:
            file_path: Path to the parquet file
            sensors: Set of sensor names in the file
            file_type: 'raw' or 'summarized'
            timestamp: Timestamp for the file (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        timestamp_str = timestamp.isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Insert or update file record
            cursor.execute("""
                INSERT INTO files (file_path, file_type, timestamp, sensor_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    sensor_count = excluded.sensor_count,
                    timestamp = excluded.timestamp
            """, (file_path, file_type, timestamp_str, len(sensors)))
            
            file_id = cursor.lastrowid
            if file_id == 0:
                # File already exists, get its ID
                cursor.execute("SELECT id FROM files WHERE file_path = ?", (file_path,))
                row = cursor.fetchone()
                file_id = row['id']
            
            # Update sensor registry inline (to avoid opening a new connection)
            for sensor_name in sensors:
                # Check if sensor exists
                cursor.execute("SELECT id, first_seen FROM sensors WHERE name = ?", (sensor_name,))
                row = cursor.fetchone()
                
                if row:
                    # Update last_seen
                    cursor.execute("""
                        UPDATE sensors SET last_seen = ? WHERE name = ?
                    """, (timestamp_str, sensor_name))
                else:
                    # Insert new sensor
                    cursor.execute("""
                        INSERT INTO sensors (name, first_seen, last_seen)
                        VALUES (?, ?, ?)
                    """, (sensor_name, timestamp_str, timestamp_str))
            
            # Get sensor IDs (after updating registry)
            sensor_ids = []
            for sensor_name in sensors:
                cursor.execute("SELECT id FROM sensors WHERE name = ?", (sensor_name,))
                row = cursor.fetchone()
                if row:
                    sensor_ids.append(row['id'])
            
            # Clear existing file-sensor mappings
            cursor.execute("DELETE FROM file_sensors WHERE file_id = ?", (file_id,))
            
            # Insert new file-sensor mappings
            for sensor_id in sensor_ids:
                cursor.execute("""
                    INSERT OR IGNORE INTO file_sensors (file_id, sensor_id)
                    VALUES (?, ?)
                """, (file_id, sensor_id))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def update_sensor_registry(self, sensors: Set[str], timestamp: Optional[datetime] = None):
        """
        Update the sensor registry with new sensors or update last_seen.
        
        Args:
            sensors: Set of sensor names
            timestamp: Timestamp when sensors were seen (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        timestamp_str = timestamp.isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for sensor_name in sensors:
                # Check if sensor exists
                cursor.execute("SELECT id, first_seen FROM sensors WHERE name = ?", (sensor_name,))
                row = cursor.fetchone()
                
                if row:
                    # Update last_seen
                    cursor.execute("""
                        UPDATE sensors SET last_seen = ? WHERE name = ?
                    """, (timestamp_str, sensor_name))
                else:
                    # Insert new sensor
                    cursor.execute("""
                        INSERT INTO sensors (name, first_seen, last_seen)
                        VALUES (?, ?, ?)
                    """, (sensor_name, timestamp_str, timestamp_str))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def get_sensors_in_file(self, file_path: str) -> List[str]:
        """
        Get list of sensor names in a specific file.
        
        Args:
            file_path: Path to the parquet file
            
        Returns:
            List of sensor names
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT s.name
            FROM sensors s
            JOIN file_sensors fs ON s.id = fs.sensor_id
            JOIN files f ON fs.file_id = f.id
            WHERE f.file_path = ?
            ORDER BY s.name
        """, (file_path,))
        
        sensors = [row['name'] for row in cursor.fetchall()]
        conn.close()
        return sensors
    
    def get_files_with_sensor(self, sensor_name: str, file_type: Optional[str] = None) -> List[str]:
        """
        Find all files containing a specific sensor.
        
        Args:
            sensor_name: Name of the sensor
            file_type: Optional filter by 'raw' or 'summarized'
            
        Returns:
            List of file paths
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if file_type:
            cursor.execute("""
                SELECT f.file_path
                FROM files f
                JOIN file_sensors fs ON f.id = fs.file_id
                JOIN sensors s ON fs.sensor_id = s.id
                WHERE s.name = ? AND f.file_type = ?
                ORDER BY f.timestamp
            """, (sensor_name, file_type))
        else:
            cursor.execute("""
                SELECT f.file_path
                FROM files f
                JOIN file_sensors fs ON f.id = fs.file_id
                JOIN sensors s ON fs.sensor_id = s.id
                WHERE s.name = ?
                ORDER BY f.timestamp
            """, (sensor_name,))
        
        files = [row['file_path'] for row in cursor.fetchall()]
        conn.close()
        return files
    
    def get_all_sensors(self) -> List[Dict]:
        """
        Get all registered sensors with their metadata.
        
        Returns:
            List of dictionaries with sensor information
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT name, data_type, first_seen, last_seen
            FROM sensors
            ORDER BY name
        """)
        
        sensors = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return sensors
    
    def get_files_in_range(self, start_time: datetime, end_time: datetime, 
                           file_type: Optional[str] = None) -> List[str]:
        """
        Get all files within a time range.
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            file_type: Optional filter by 'raw' or 'summarized'
            
        Returns:
            List of file paths
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        start_str = start_time.isoformat()
        end_str = end_time.isoformat()
        
        if file_type:
            cursor.execute("""
                SELECT file_path
                FROM files
                WHERE timestamp >= ? AND timestamp <= ? AND file_type = ?
                ORDER BY timestamp
            """, (start_str, end_str, file_type))
        else:
            cursor.execute("""
                SELECT file_path
                FROM files
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            """, (start_str, end_str))
        
        files = [row['file_path'] for row in cursor.fetchall()]
        conn.close()
        return files
    
    def file_exists(self, file_path: str) -> bool:
        """
        Check if a file is recorded in the catalog.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if file exists in catalog
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM files WHERE file_path = ?", (file_path,))
        count = cursor.fetchone()['count']
        conn.close()
        
        return count > 0

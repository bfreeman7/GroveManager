from flask import Flask, request
import logging
from datetime import datetime, timezone
from typing import Optional
import os
import sys

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telemetry_storage import TelemetryStorage
from summarizer import Summarizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize storage components
# Use environment variable for data path if set, otherwise default to ./data
DATA_PATH = os.getenv('DATA_STORAGE_PATH', 'data')
storage = TelemetryStorage(base_path=DATA_PATH)
summarizer = Summarizer(base_path=DATA_PATH, storage=storage)

# Keys to ignore when storing telemetry data
# These are typically device metadata, security keys, or internal diagnostics
IGNORED_KEYS = {
    'PASSKEY',           # Security key - should not be stored
    'runtime',            # Device runtime counter - not sensor data
    'heap',              # Device memory info - not sensor data
    'freq',              # Radio frequency - device config, not sensor data
    'model',             # Device model - static metadata
    'stationtype',       # Device type - static metadata
    'interval',           # Update interval - configuration, not sensor data
}

def filter_telemetry_data(data: dict) -> dict:
    """
    Filter out unwanted keys from Ecowitt payload.
    
    Args:
        data: Raw Ecowitt data dictionary
        
    Returns:
        Filtered dictionary with only telemetry data
    """
    return {k: v for k, v in data.items() if k not in IGNORED_KEYS}

def parse_ecowitt_timestamp(dateutc_str: str) -> Optional[datetime]:
    """
    Parse Ecowitt's dateutc timestamp string.
    
    Args:
        dateutc_str: Timestamp string from Ecowitt (format: "YYYY-MM-DD HH:MM:SS")
        
    Returns:
        datetime object in UTC, or None if parsing fails
    """
    if not dateutc_str:
        return None
    
    try:
        # Ecowitt sends: "2026-01-20 04:22:16"
        dt = datetime.strptime(dateutc_str, "%Y-%m-%d %H:%M:%S")
        # Assume UTC (Ecowitt sends UTC time)
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse dateutc '{dateutc_str}': {e}")
        return None

@app.route('/ecowitt', methods=['POST'])
def ecowitt_listener():
    """
    Receive telemetry data from Ecowitt gateway and store it.
    
    Ecowitt sends data as form-encoded data. We extract it, filter out unwanted
    keys, use the dateutc timestamp if available, and store it in the 
    appropriate hourly Parquet file.
    """
    try:
        # Ecowitt sends data as form-encoded data
        raw_data = request.form.to_dict()
        
        # Filter out unwanted keys (security, device metadata, etc.)
        filtered_data = filter_telemetry_data(raw_data)
        
        # Use Ecowitt's timestamp if available, otherwise use current time
        timestamp = None
        if 'dateutc' in raw_data:
            timestamp = parse_ecowitt_timestamp(raw_data['dateutc'])
        
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        # Store the reading (only filtered telemetry data)
        storage.store_reading(filtered_data, timestamp)
        
        # Log key sensor values for monitoring
        sensor_count = len(filtered_data)
        if 'soilmoisture1' in filtered_data:
            logger.info(f"Received reading: soilmoisture1={filtered_data.get('soilmoisture1')}% ({sensor_count} sensors)")
        else:
            logger.debug(f"Received reading with {sensor_count} sensors")
        
        return "OK", 200
    
    except Exception as e:
        logger.error(f"Error processing Ecowitt data: {e}", exc_info=True)
        # Still return OK to Ecowitt to avoid retries
        return "OK", 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}, 200

if __name__ == '__main__':
    # Listen on all interfaces so the Gateway can find it
    logger.info("Starting Ecowitt server on 0.0.0.0:8080...")
    logger.info(f"Data storage path: {DATA_PATH}")
    app.run(host='0.0.0.0', port=8080)
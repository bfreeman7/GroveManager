"""
OrchardMonitor server: measurements, Open Sprinkler schedule logging, schedule updates.
"""

import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
from flask import Flask, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from measurement_store import MeasurementStore
from schedule_logger import ScheduleLogger, log_schedule_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Config
DATA_PATH = os.getenv("DATA_STORAGE_PATH", "data")
OPENSPRINKLER_URL = os.getenv("OPENSPRINKLER_URL", "")
OPENSPRINKLER_PASSWORD = os.getenv("OPENSPRINKLER_PASSWORD", "")

# Storage
measurements = MeasurementStore(base_path=DATA_PATH)
schedule_logger: Optional[ScheduleLogger] = None
if OPENSPRINKLER_URL and OPENSPRINKLER_PASSWORD:
    schedule_logger = ScheduleLogger(
        base_url=OPENSPRINKLER_URL,
        password=OPENSPRINKLER_PASSWORD,
        base_path=DATA_PATH,
    )
else:
    logger.warning("OPENSPRINKLER_URL/PASSWORD not set - schedule logging disabled")

IGNORED_KEYS = {
    "PASSKEY",
    "runtime",
    "heap",
    "freq",
    "model",
    "stationtype",
    "interval",
}


def filter_telemetry_data(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in IGNORED_KEYS}


def parse_ecowitt_timestamp(dateutc_str: str) -> Optional[datetime]:
    if not dateutc_str:
        return None
    try:
        dt = datetime.strptime(dateutc_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


@app.route("/ecowitt", methods=["POST"])
def ecowitt_listener():
    """Receive Ecowitt telemetry and append to daily parquet."""
    try:
        raw_data = request.form.to_dict()
        filtered = filter_telemetry_data(raw_data)

        timestamp = None
        if "dateutc" in raw_data:
            timestamp = parse_ecowitt_timestamp(raw_data["dateutc"])
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        measurements.store_reading(filtered, timestamp)

        if "soilmoisture1" in filtered:
            logger.info(
                f"Received: soilmoisture1={filtered.get('soilmoisture1')}% ({len(filtered)} sensors)"
            )

        return "OK", 200
    except Exception as e:
        logger.error(f"Error processing Ecowitt: {e}", exc_info=True)
        return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return {"status": "healthy"}, 200


def _opensprinkler_update(params: dict) -> dict:
    """
    Send update to Open Sprinkler.
    Uses /cp (change program). Params vary by firmware - pass pid, dur, etc. as needed.
    """
    pw = hashlib.md5(OPENSPRINKLER_PASSWORD.encode()).hexdigest()
    all_params = {"pw": pw, **params}
    # /cp = change program - common for schedule updates
    url = f"{OPENSPRINKLER_URL.rstrip('/')}/cp"
    r = requests.get(url, params=all_params, timeout=10)
    r.raise_for_status()
    return r.json()


@app.route("/schedule/update", methods=["POST"])
def schedule_update():
    """
    Update Open Sprinkler schedule. Body: JSON with API params (e.g. pid, ...).
    Logs to schedule_updates.jsonl and triggers immediate schedule log.
    """
    if not schedule_logger:
        return {"error": "Open Sprinkler not configured"}, 503

    try:
        body = request.get_json() or {}
        # Forward params to Open Sprinkler /cp
        resp = _opensprinkler_update(body)

        log_schedule_update(DATA_PATH, request_data=body, response_data=resp)
        schedule_logger.log_schedule()

        return {"result": resp.get("result", 1), "response": resp}, 200
    except Exception as e:
        logger.error(f"Schedule update failed: {e}", exc_info=True)
        log_schedule_update(
            DATA_PATH,
            request_data=request.get_json() or {},
            response_data={"error": str(e)},
        )
        return {"error": str(e)}, 500


def main():
    logger.info("Starting OrchardMonitor on 0.0.0.0:8080")
    logger.info(f"Data path: {DATA_PATH}")

    if schedule_logger:
        schedule_logger.start_background()

    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()

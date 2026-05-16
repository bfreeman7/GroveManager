"""
Open Sprinkler schedule logger.

Fetches schedule from Open Sprinkler /jp endpoint and appends to schedule_log.jsonl.
Can be run on a 12-hour timer or triggered immediately (e.g. after a schedule update).
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from libs.opensprinkler_client import resolve_opensprinkler_pw_hash

logger = logging.getLogger(__name__)


class ScheduleLogger:
    """Fetches Open Sprinkler schedule and logs to JSONL file."""

    def __init__(
        self,
        base_url: str,
        password: str = "",
        password_md5: str = "",
        base_path: str = "data",
        log_file: str = "schedule_log.jsonl",
    ):
        """
        Args:
            base_url: Open Sprinkler base URL (e.g. http://192.168.1.x:8080)
            password: Plain-text password (MD5 hashed for API), or use password_md5
            password_md5: Pre-computed MD5 hex (OPENSPRINKLER_PW_MD5)
            base_path: Data directory
            log_file: Filename for schedule log (inside base_path)
        """
        self.base_url = base_url.rstrip("/")
        self._pw_hash = resolve_opensprinkler_pw_hash(password=password, password_md5=password_md5)
        self.log_path = os.path.join(base_path, log_file)
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        self._stop = threading.Event()

    def _fetch_schedule(self) -> Optional[dict]:
        """GET schedule from Open Sprinkler /jp endpoint."""
        url = f"{self.base_url}/jp"
        params = {"pw": self._pw_hash}
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Failed to fetch Open Sprinkler schedule: {e}")
            return None

    def log_schedule(self) -> bool:
        """
        Fetch current schedule and append one line to schedule_log.jsonl.

        Returns True if successful.
        """
        schedule = self._fetch_schedule()
        if schedule is None:
            return False

        line = json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(), "schedule": schedule}
        )
        with open(self.log_path, "a") as f:
            f.write(line + "\n")
        logger.info(f"Logged schedule to {self.log_path}")
        return True

    def run_every_12h(self):
        """Background loop: log schedule immediately, then every 12 hours until stopped."""
        try:
            self.log_schedule()
        except Exception:
            logger.error("Schedule logger initial log_schedule failed", exc_info=True)
        while not self._stop.wait(12 * 60 * 60):  # 12 hours
            try:
                self.log_schedule()
            except Exception:
                logger.error("Schedule logger periodic log_schedule failed", exc_info=True)

    def start_background(self):
        """Start the 12-hour polling loop in a daemon thread."""
        t = threading.Thread(target=self.run_every_12h, daemon=True)
        t.start()
        logger.info("Schedule logger background task started (every 12h)")


def log_schedule_update(
    base_path: str,
    request_data: dict,
    response_data: dict,
    updates_file: str = "schedule_updates.jsonl",
):
    """Append a schedule update event to schedule_updates.jsonl."""
    path = os.path.join(base_path, updates_file)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request": request_data,
            "response": response_data,
        }
    )
    with open(path, "a") as f:
        f.write(line + "\n")
    logger.info(f"Logged schedule update to {path}")

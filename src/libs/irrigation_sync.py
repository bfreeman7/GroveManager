from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from libs.edge_db import EdgeDB
from libs.opensprinkler_client import OpenSprinklerClient, summarize_json_all, summarize_run_log

logger = logging.getLogger(__name__)


def station_channel(station_id: int) -> str:
    return f"irrigation_state.station{station_id + 1:02d}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _epoch_to_dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


class IrrigationSyncer:
    """Poll OpenSprinkler and enqueue irrigation_state.stationNN on every snapshot."""

    def __init__(self, *, client: OpenSprinklerClient, db: EdgeDB):
        self.client = client
        self.db = db
        self._logging_warned = False
        self.history_lookback_minutes = _env_int("IRRIGATION_HISTORY_LOOKBACK_MINUTES", 5)
        self.history_startup_lookback_hours = _env_int("IRRIGATION_HISTORY_STARTUP_LOOKBACK_HOURS", 24)

    def sync_snapshot(self) -> int:
        raw = self.client.get_json_all()
        summary = summarize_json_all(raw)
        stations = summary.get("stations") or []
        poll_now = _utc_now()

        points: List[Tuple[datetime, str, bool]] = []
        on_count = 0
        for st in stations:
            sid = int(st["id"])
            on = bool(st["on"])
            if on:
                on_count += 1
            points.append((poll_now, station_channel(sid), on))
            self.db.upsert_irrigation_station_state(sid, on, updated_at=poll_now)

        if points:
            self.db.insert_irrigation_points(
                points=points,
                payload={"kind": "snapshot", "count": len(points), "on": on_count},
            )
            logger.info(
                "Irrigation snapshot sync queued %d point(s) (%d on)",
                len(points),
                on_count,
            )
        return len(points)

    def sync_history(self, *, lookback_minutes: Optional[int] = None) -> int:
        lookback_minutes = (
            self.history_lookback_minutes if lookback_minutes is None else max(1, lookback_minutes)
        )
        raw = self.client.get_json_all()
        summary = summarize_json_all(raw)
        controller = summary.get("controller") or {}
        logging_enabled = controller.get("logging_enabled")
        if logging_enabled is False and not self._logging_warned:
            logger.warning(
                "OpenSprinkler run logging is disabled (options.lg=0); "
                "history backfill will produce no runs until enabled"
            )
            self._logging_warned = True

        station_names = [s["name"] for s in summary.get("stations") or []]
        program_names = [p["name"] for p in summary.get("programs") or []]
        records = self.client.get_run_log(hist=1)
        runs = summarize_run_log(records, station_names, program_names)

        cutoff = _utc_now() - timedelta(minutes=lookback_minutes)
        cutoff_epoch = int(cutoff.timestamp())

        points: List[Tuple[datetime, str, bool]] = []
        synced = 0
        for row in runs:
            if row.get("kind") != "run":
                continue
            end_epoch = int(row["end_epoch"])
            if end_epoch < cutoff_epoch:
                continue
            sid = int(row["station_id"])
            if self.db.is_run_synced(sid, end_epoch):
                continue

            duration = int(row["duration_seconds"])
            start_epoch = end_epoch - duration
            channel = station_channel(sid)
            points.append((_epoch_to_dt(start_epoch), channel, True))
            points.append((_epoch_to_dt(end_epoch), channel, False))
            self.db.mark_run_synced(sid, end_epoch)
            synced += 1

        if points:
            self.db.insert_irrigation_points(
                points=points,
                payload={"kind": "history", "runs": synced, "points": len(points)},
            )
            logger.info("Irrigation history sync queued %d point(s) from %d run(s)", len(points), synced)
        elif lookback_minutes > self.history_lookback_minutes:
            logger.info(
                "Irrigation startup history sync: no new runs in last %d hour(s)",
                lookback_minutes // 60,
            )
        return len(points)


class IrrigationSyncLoop:
    def __init__(
        self,
        *,
        syncer: IrrigationSyncer,
        snapshot_interval_seconds: int = 15,
        history_interval_seconds: int = 300,
    ):
        self.syncer = syncer
        self.snapshot_interval_seconds = max(1, snapshot_interval_seconds)
        self.history_interval_seconds = history_interval_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def sync_once(self) -> None:
        with self._lock:
            try:
                self.syncer.sync_snapshot()
            except requests.RequestException as e:
                logger.error("Irrigation snapshot sync failed: %s", e, exc_info=True)
            except Exception:
                logger.error("Irrigation snapshot sync failed", exc_info=True)

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        logger.info(
            "Irrigation sync background task started (snapshot=%ds, history=%ds)",
            self.snapshot_interval_seconds,
            self.history_interval_seconds,
        )

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            self.sync_once()
        except Exception:
            logger.error("Irrigation sync initial tick failed", exc_info=True)

        with self._lock:
            try:
                startup_minutes = self.syncer.history_startup_lookback_hours * 60
                self.syncer.sync_history(lookback_minutes=startup_minutes)
            except requests.RequestException as e:
                logger.error("Irrigation startup history sync failed: %s", e, exc_info=True)
            except Exception:
                logger.error("Irrigation startup history sync failed", exc_info=True)

        last_history = time.monotonic()
        while not self._stop.wait(self.snapshot_interval_seconds):
            try:
                self.sync_once()
            except Exception:
                logger.error("Irrigation snapshot sync tick failed", exc_info=True)

            if self.history_interval_seconds <= 0:
                continue

            now = time.monotonic()
            if now - last_history < self.history_interval_seconds:
                continue

            last_history = now
            with self._lock:
                try:
                    self.syncer.sync_history()
                except requests.RequestException as e:
                    logger.error("Irrigation history sync failed: %s", e, exc_info=True)
                except Exception:
                    logger.error("Irrigation history sync failed", exc_info=True)


def make_irrigation_sync_loop(
    *,
    client: OpenSprinklerClient,
    db: EdgeDB,
) -> Optional[IrrigationSyncLoop]:
    if not _env_bool("IRRIGATION_SYNC_ENABLED", True):
        return None

    syncer = IrrigationSyncer(client=client, db=db)
    snapshot_interval = _env_int("IRRIGATION_SYNC_INTERVAL_SECONDS", 15)
    history_interval = _env_int("IRRIGATION_HISTORY_SYNC_INTERVAL_SECONDS", 300)
    return IrrigationSyncLoop(
        syncer=syncer,
        snapshot_interval_seconds=snapshot_interval,
        history_interval_seconds=history_interval,
    )

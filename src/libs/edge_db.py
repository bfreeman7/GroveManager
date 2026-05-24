from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class PendingMeasurement:
    id: int
    ts: str
    channel: str
    value: float
    raw_event_id: int


class EdgeDB:
    """
    SQLite-backed index/queue for store-and-forward.

    Bulk retention remains in Parquet; SQLite tracks:
    - raw ingest events (payload, timestamps)
    - normalized measurements (channel/value rows) + forwarding state
    - system events (important transitions)
    """

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _conn(self):
        # check_same_thread=False to allow background worker + Flask threads.
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  received_at TEXT NOT NULL,
                  source TEXT NOT NULL,
                  payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  raw_event_id INTEGER NOT NULL,
                  ts TEXT NOT NULL,
                  channel TEXT NOT NULL,
                  value REAL NOT NULL,
                  forwarded_at TEXT,
                  forward_error TEXT,
                  FOREIGN KEY(raw_event_id) REFERENCES raw_events(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_measurements_pending ON measurements(forwarded_at) WHERE forwarded_at IS NULL"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements(ts)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts TEXT NOT NULL,
                  level TEXT NOT NULL,
                  component TEXT NOT NULL,
                  message TEXT NOT NULL,
                  details_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS irrigation_station_state (
                  station_id INTEGER PRIMARY KEY,
                  is_on INTEGER NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS irrigation_run_synced (
                  station_id INTEGER NOT NULL,
                  end_epoch INTEGER NOT NULL,
                  PRIMARY KEY (station_id, end_epoch)
                )
                """
            )
            conn.commit()

    def add_system_event(
        self,
        *,
        level: str,
        component: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ) -> None:
        ts = ts or _utc_now()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO system_events (ts, level, component, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_iso(ts), level, component, message, json.dumps(details) if details else None),
            )
            conn.commit()

    def insert_raw_event(self, *, source: str, payload: Dict[str, Any], received_at: datetime) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO raw_events (received_at, source, payload_json)
                VALUES (?, ?, ?)
                """,
                (_iso(received_at), source, json.dumps(payload)),
            )
            conn.commit()
            return int(cur.lastrowid)

    def insert_measurements(
        self,
        *,
        raw_event_id: int,
        ts: datetime,
        channel_values: Iterable[Tuple[str, float]],
    ) -> int:
        rows = [(raw_event_id, _iso(ts), ch, float(val)) for ch, val in channel_values]
        if not rows:
            return 0
        with self._lock, self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO measurements (raw_event_id, ts, channel, value)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            return len(rows)

    def get_pending_measurements(self, *, limit: int = 500) -> List[PendingMeasurement]:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                SELECT id, ts, channel, value, raw_event_id
                FROM measurements
                WHERE forwarded_at IS NULL
                ORDER BY ts ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                PendingMeasurement(
                    id=int(r[0]),
                    ts=str(r[1]),
                    channel=str(r[2]),
                    value=float(r[3]),
                    raw_event_id=int(r[4]),
                )
                for r in cur.fetchall()
            ]

    def mark_forwarded(self, ids: Iterable[int], *, forwarded_at: Optional[datetime] = None) -> None:
        ids = list(ids)
        if not ids:
            return
        forwarded_at = forwarded_at or _utc_now()
        with self._lock, self._conn() as conn:
            conn.executemany(
                """
                UPDATE measurements
                SET forwarded_at = ?, forward_error = NULL
                WHERE id = ?
                """,
                [(_iso(forwarded_at), i) for i in ids],
            )
            conn.commit()

    def mark_forward_error(self, ids: Iterable[int], error: str) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._lock, self._conn() as conn:
            conn.executemany(
                """
                UPDATE measurements
                SET forward_error = ?
                WHERE id = ?
                """,
                [(error, i) for i in ids],
            )
            conn.commit()

    def counts(self) -> Dict[str, int]:
        with self._lock, self._conn() as conn:
            pending = conn.execute("SELECT COUNT(*) FROM measurements WHERE forwarded_at IS NULL").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
            return {"pending_forward": int(pending), "total_measurements": int(total)}

    def recent_system_events(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """
                SELECT ts, level, component, message, details_json
                FROM system_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            out: List[Dict[str, Any]] = []
            for ts, level, component, message, details_json in cur.fetchall():
                out.append(
                    {
                        "ts": ts,
                        "level": level,
                        "component": component,
                        "message": message,
                        "details": json.loads(details_json) if details_json else None,
                    }
                )
            return out

    def get_irrigation_station_states(self) -> Dict[int, bool]:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT station_id, is_on FROM irrigation_station_state")
            return {int(row[0]): bool(row[1]) for row in cur.fetchall()}

    def upsert_irrigation_station_state(
        self,
        station_id: int,
        on: bool,
        *,
        updated_at: Optional[datetime] = None,
    ) -> None:
        updated_at = updated_at or _utc_now()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO irrigation_station_state (station_id, is_on, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                  is_on = excluded.is_on,
                  updated_at = excluded.updated_at
                """,
                (int(station_id), 1 if on else 0, _iso(updated_at)),
            )
            conn.commit()

    def is_run_synced(self, station_id: int, end_epoch: int) -> bool:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM irrigation_run_synced
                WHERE station_id = ? AND end_epoch = ?
                """,
                (int(station_id), int(end_epoch)),
            ).fetchone()
            return row is not None

    def mark_run_synced(self, station_id: int, end_epoch: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO irrigation_run_synced (station_id, end_epoch)
                VALUES (?, ?)
                """,
                (int(station_id), int(end_epoch)),
            )
            conn.commit()

    def insert_irrigation_points(
        self,
        *,
        points: Iterable[Tuple[datetime, str, bool]],
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        point_list = list(points)
        if not point_list:
            return 0

        received_at = _utc_now()
        raw_event_id = self.insert_raw_event(
            source="irrigation_sync",
            payload=payload or {"points": len(point_list)},
            received_at=received_at,
        )

        by_ts: Dict[str, List[Tuple[str, float]]] = {}
        for ts, channel, value in point_list:
            by_ts.setdefault(_iso(ts), []).append((channel, 1.0 if value else 0.0))

        count = 0
        for ts_iso, channel_values in by_ts.items():
            ts_dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
            count += self.insert_measurements(
                raw_event_id=raw_event_id,
                ts=ts_dt,
                channel_values=channel_values,
            )
        return count


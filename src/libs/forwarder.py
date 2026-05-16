from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

import logging

from libs.edge_db import EdgeDB, PendingMeasurement

logger = logging.getLogger(__name__)

# Reuse one event loop per OS thread. `asyncio.run()` creates a fresh loop (and selector
# socketpair) on every call; combined with gRPC cleanup timing this can exhaust the
# process FD budget on long-running edge hosts with small `LimitNOFILE`.
_asyncio_loops = threading.local()


def _run_coroutine_sync(coro):
    loop = getattr(_asyncio_loops, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _asyncio_loops.loop = loop
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_sift_grpc_url(url: str) -> str:
    """
    Sift's Python client is picky about URL shape. Users often paste:
    - grpc-api.siftstack.com:443
    - https://grpc-api.siftstack.com
    """
    u = (url or "").strip()
    if not u:
        return u

    # Sift's Python gRPC clients expect a "base uri" without scheme and typically without port.
    if "://" in u:
        parsed = urlparse(u)
        host = parsed.hostname or ""
        if not host:
            return u
        port = parsed.port
        if port and port != 443:
            return f"{host}:{port}"
        return host

    if u.endswith(":443"):
        return u[: -len(":443")]

    return u


def _coalesce_points_by_timestamp(points: List[Dict]) -> List[Dict[str, Any]]:
    """
    Merge per-channel rows that share a timestamp into one ingest payload per ts.

    Ecowitt readings produce ~14 sqlite rows per event; coalescing cuts gRPC calls
    by that factor during catch-up.
    """
    by_ts: Dict[str, Dict[str, float]] = {}
    for p in points:
        ts = str(p["ts"])
        ch = str(p["channel"])
        by_ts.setdefault(ts, {})[ch] = float(p["value"])
    return [{"ts": ts, "values": vals} for ts, vals in sorted(by_ts.items())]


def _split_points_by_day(points: List[Dict]) -> Dict[str, List[Dict]]:
    by_day: Dict[str, List[Dict]] = {}
    for p in points:
        day = str(p["ts"])[:10]
        by_day.setdefault(day, []).append(p)
    return by_day


def _parse_point_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return max(1, int(raw))


def forward_batch_size_for_pending(pending: int) -> int:
    """Larger sqlite pull + one gRPC stream when the queue is deep."""
    normal = _env_int("FORWARD_BATCH_SIZE", 500)
    catchup = _env_int("FORWARD_CATCHUP_BATCH_SIZE", 10000)
    threshold = _env_int("FORWARD_CATCHUP_THRESHOLD", 2000)
    if pending >= threshold:
        return catchup
    return normal


def _normalize_sift_py_grpc_uri(url: str) -> str:
    """
    Normalize user-provided gRPC URI for the legacy `sift_py` transport (grpcio).
    """
    u = (url or "").strip()
    if not u:
        return u

    if "://" in u:
        parsed = urlparse(u)
        host = parsed.hostname or ""
        if not host:
            return u
        port = parsed.port or 443
        return f"{host}:{port}"

    if ":" not in u:
        return f"{u}:443"

    return u


@dataclass(frozen=True)
class ForwardResult:
    attempted: int
    forwarded: int
    error: Optional[str] = None


class MeasurementForwarder:
    def send(self, *, asset: str, day: str, points: List[Dict]) -> None:
        raise NotImplementedError()


class FakeSiftForwarder(MeasurementForwarder):
    """
    Offline/local validation forwarder.
    Writes line-delimited JSON payloads so you can inspect exactly what would be sent.
    """

    def __init__(self, out_path: str):
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        self.out_path = out_path
        self._lock = threading.Lock()

    def send(self, *, asset: str, day: str, points: List[Dict]) -> None:
        rec = {"ts": _iso(_utc_now()), "asset": asset, "day": day, "points": points}
        line = json.dumps(rec)
        with self._lock, open(self.out_path, "a") as f:
            f.write(line + "\n")


class SiftSDKForwarder(MeasurementForwarder):
    """
    Real Sift (Sift Stack) Python SDK integration via `sift-stack-py`.
    """

    def __init__(self):
        self.api_key = os.getenv("SIFT_API_KEY")
        raw_grpc = os.getenv("SIFT_GRPC_URL") or os.getenv("SIFT_GRPC_URI") or os.getenv("SIFT_GRPC")
        self.grpc_url = (raw_grpc or "").strip()
        self.rest_url = os.getenv("SIFT_REST_URL") or os.getenv("SIFT_REST_URI") or os.getenv("SIFT_REST")
        self.base_client_key = os.getenv("SIFT_INGESTION_CLIENT_KEY", "orchard-edge-v1")
        self.flow_name = os.getenv("SIFT_FLOW_NAME", "orchard")
        self.prefer_client = os.getenv("SIFT_SDK_PREFER", "client").strip().lower()  # client|py
        self.debug = os.getenv("SIFT_DEBUG", "0").strip() in ("1", "true", "yes", "on")
        self.debug_sample_n = int(os.getenv("SIFT_DEBUG_SAMPLE_N", "3"))

        if not self.api_key or not self.grpc_url:
            raise RuntimeError(
                "Missing Sift config. Set SIFT_API_KEY and SIFT_GRPC_URL (or use SIFT_MODE=fake)."
            )

        self._sift_client = None
        self._sift_client_lock = threading.Lock()
        # After sift_client TLS/connect failures on this host, stick to sift_py for the process.
        self._use_sift_py_only = self.prefer_client == "py"

    def _sift_client_grpc_url(self) -> str:
        grpc_u = self.grpc_url
        if "://" not in grpc_u:
            grpc_u = f"https://{grpc_u}"
        return grpc_u

    def _get_sift_client(self):
        """
        Reuse one SiftClient for the process lifetime.

        Each SiftClient() constructs a GrpcClient with its own background thread and
        asyncio loop; creating one per forward tick leaks threads until the process exits.
        """
        if self._sift_client is not None:
            return self._sift_client
        with self._sift_client_lock:
            if self._sift_client is not None:
                return self._sift_client
            from sift_client import SiftClient  # type: ignore

            if not self.rest_url:
                raise RuntimeError("Missing SIFT_REST_URL required by sift_client.")
            self._sift_client = SiftClient(
                api_key=self.api_key,
                grpc_url=self._sift_client_grpc_url(),
                rest_url=self.rest_url,
            )
            return self._sift_client

    def send(self, *, asset: str, day: str, points: List[Dict]) -> None:
        if self.debug:
            logger.setLevel(logging.DEBUG)

        if not points:
            return

        for day_part, day_points in _split_points_by_day(points).items():
            self._send_day(asset=asset, day=day_part, points=day_points)

    def _send_day(self, *, asset: str, day: str, points: List[Dict]) -> None:
        channels: Set[str] = set()
        for p in points:
            ch = p.get("channel")
            if ch:
                channels.add(str(ch))

        if not channels:
            return

        coalesced = _coalesce_points_by_timestamp(points)
        client_key = f"{self.base_client_key}.ch{len(channels)}"
        run_name = f"{asset}.{day}"

        def _send_via_sift_client() -> None:
            from sift_client.sift_types.channel import ChannelDataType  # type: ignore
            from sift_client.sift_types.ingestion import (  # type: ignore
                ChannelConfig,
                FlowConfig,
                IngestionConfigCreate,
            )

            grpc_u = self._sift_client_grpc_url()
            client = self._get_sift_client()

            if self.debug:
                safe_key = (self.api_key[:6] + "…" + self.api_key[-4:]) if self.api_key else "(missing)"
                logger.debug(
                    "sift_client send start asset=%s flow=%s run=%s client_key=%s points=%d unique_channels=%d grpc_url=%s rest_url=%s api_key=%s",
                    asset,
                    self.flow_name,
                    run_name,
                    client_key,
                    len(points),
                    len(channels),
                    grpc_u,
                    self.rest_url,
                    safe_key,
                )

            flow_cfg = FlowConfig(
                name=self.flow_name,
                channels=[
                    ChannelConfig(name=ch, data_type=ChannelDataType.DOUBLE, unit=None)
                    for ch in sorted(channels)
                ],
            )
            ingestion_cfg = IngestionConfigCreate(asset_name=asset, client_key=client_key, flows=[flow_cfg])

            async def _send_all():
                ing = await client.async_.ingestion.create_ingestion_config_streaming_client(
                    ingestion_cfg,
                    run=run_name,
                )
                async with ing:
                    for row in coalesced:
                        ts = _parse_point_timestamp(row["ts"])
                        await ing.send(flow_cfg.as_flow(timestamp=ts, values=row["values"]))
                    await ing.finish()

            _run_coroutine_sync(_send_all())

        def _send_via_sift_py() -> None:
            from sift_py.grpc.transport import SiftChannelConfig, use_sift_channel  # type: ignore
            from sift_py.ingestion.channel import ChannelConfig, ChannelDataType  # type: ignore
            from sift_py.ingestion.config.telemetry import FlowConfig, TelemetryConfig  # type: ignore
            from sift_py.ingestion.service import IngestionService  # type: ignore
            from google.protobuf.empty_pb2 import Empty  # type: ignore
            from sift.ingest.v1.ingest_pb2 import IngestWithConfigDataChannelValue  # type: ignore

            grpc_uri = _normalize_sift_py_grpc_uri(self.grpc_url)
            ordered_channels = sorted(channels)
            channel_idx = {ch: i for i, ch in enumerate(ordered_channels)}

            telemetry_config = TelemetryConfig(
                asset_name=asset,
                ingestion_client_key=client_key,
                flows=[
                    FlowConfig(
                        name=self.flow_name,
                        channels=[
                            ChannelConfig(name=ch, data_type=ChannelDataType.DOUBLE) for ch in ordered_channels
                        ],
                    )
                ],
            )

            sift_channel_config = SiftChannelConfig(uri=grpc_uri, apikey=self.api_key)
            with use_sift_channel(sift_channel_config) as channel:
                ingestion_service = IngestionService(channel, telemetry_config)
                ingestion_service.attach_run(channel, run_name)
                for row in coalesced:
                    ts = _parse_point_timestamp(row["ts"])
                    values = [IngestWithConfigDataChannelValue(empty=Empty()) for _ in ordered_channels]
                    for ch, val in row["values"].items():
                        idx = channel_idx.get(ch)
                        if idx is not None:
                            values[idx] = IngestWithConfigDataChannelValue(double=val)
                    ingestion_service.ingest_flows(
                        {
                            "flow_name": self.flow_name,
                            "timestamp": ts,
                            "channel_values": values,
                        }
                    )

        if self._use_sift_py_only:
            _send_via_sift_py()
            return

        try:
            _send_via_sift_client()
        except Exception as e:
            msg = str(e)
            if "BadSignature" in msg or "InvalidUri" in msg:
                self._use_sift_py_only = True
                logger.warning(
                    "sift_client transport failed (%s). Using sift_py for this process. "
                    "Set SIFT_SDK_PREFER=client|py to override.",
                    msg,
                )
                if self.debug:
                    logger.debug("sift_client exception details", exc_info=True)
                _send_via_sift_py()
                return
            raise


class ForwardWorker:
    def __init__(
        self,
        *,
        db: EdgeDB,
        forwarder: MeasurementForwarder,
        asset: str,
        batch_size: Optional[int] = None,
    ):
        self.db = db
        self.forwarder = forwarder
        self.asset = asset
        self.batch_size = batch_size or _env_int("FORWARD_BATCH_SIZE", 500)

    def _resolve_batch_size(self, override: Optional[int] = None) -> int:
        if override is not None:
            return max(1, override)
        try:
            pending = self.db.counts()["pending_forward"]
        except Exception:
            pending = 0
        return forward_batch_size_for_pending(pending)

    def run_once(self, *, batch_size: Optional[int] = None) -> ForwardResult:
        limit = self._resolve_batch_size(batch_size)
        try:
            pending = self.db.get_pending_measurements(limit=limit)
        except Exception as e:
            logger.error("get_pending_measurements failed: %s", e, exc_info=True)
            return ForwardResult(attempted=0, forwarded=0, error=str(e))

        if not pending:
            return ForwardResult(attempted=0, forwarded=0)

        points = [self._to_point(m) for m in pending]
        ids = [m.id for m in pending]
        days = sorted({m.ts[:10] for m in pending})
        coalesced_n = len(_coalesce_points_by_timestamp(points))

        try:
            self.forwarder.send(asset=self.asset, day=days[0], points=points)
        except Exception as e:
            err = str(e)
            try:
                self.db.mark_forward_error(ids, err)
                self.db.add_system_event(
                    level="error",
                    component="forwarder",
                    message="forward_failed",
                    details={"count": len(ids), "error": err},
                )
            except Exception as inner:
                logger.error(
                    "forward_failed and could not persist error to sqlite: %s (original: %s)",
                    inner,
                    err,
                    exc_info=True,
                )
            return ForwardResult(attempted=len(ids), forwarded=0, error=err)

        try:
            self.db.mark_forwarded(ids, forwarded_at=_utc_now())
            self.db.add_system_event(
                level="info",
                component="forwarder",
                message="forwarded_batch",
                details={
                    "count": len(ids),
                    "days": days,
                    "ingest_timestamps": coalesced_n,
                    "batch_limit": limit,
                },
            )
            logger.info(
                "Forwarded %d measurements (%d timestamps, days=%s) via one gRPC stream",
                len(ids),
                coalesced_n,
                ",".join(days),
            )
        except Exception as e:
            err = f"post_send_sqlite_failed:{e}"
            logger.critical(
                "Sift send succeeded but sqlite mark_forwarded failed; rows stay pending and "
                "may duplicate on retry: %s",
                e,
                exc_info=True,
            )
            try:
                self.db.add_system_event(
                    level="error",
                    component="forwarder",
                    message="mark_forwarded_failed_after_send",
                    details={"count": len(ids), "days": days, "error": str(e)},
                )
            except Exception:
                pass
            return ForwardResult(attempted=len(ids), forwarded=len(ids), error=err)
        return ForwardResult(attempted=len(ids), forwarded=len(ids))

    def run_catchup(
        self,
        *,
        max_batches: Optional[int] = None,
        max_seconds: Optional[float] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Drain pending rows using large batches and one gRPC stream per batch.

        Intended for manual/operator use; the background loop enters the same mode
        automatically when the queue exceeds FORWARD_CATCHUP_THRESHOLD.
        """
        max_batches = max_batches if max_batches is not None else _env_int("FORWARD_CATCHUP_MAX_BATCHES", 0)
        max_seconds = (
            float(max_seconds)
            if max_seconds is not None
            else float(_env_int("FORWARD_CATCHUP_MAX_SECONDS", 0))
        )
        deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
        batches = 0
        forwarded = 0
        last_error: Optional[str] = None

        while max_batches == 0 or batches < max_batches:
            if deadline is not None and time.monotonic() >= deadline:
                break
            res = self.run_once(batch_size=batch_size or _env_int("FORWARD_CATCHUP_BATCH_SIZE", 10000))
            if res.attempted == 0:
                break
            batches += 1
            forwarded += res.forwarded
            if res.error:
                last_error = res.error
                break

        try:
            pending_remaining = self.db.counts()["pending_forward"]
        except Exception:
            pending_remaining = -1

        return {
            "batches": batches,
            "forwarded": forwarded,
            "pending_remaining": pending_remaining,
            "error": last_error,
        }

    def _to_point(self, m: PendingMeasurement) -> Dict:
        return {"ts": m.ts, "channel": m.channel, "value": m.value}


class BackgroundForwardLoop:
    def __init__(
        self,
        *,
        worker: ForwardWorker,
        db: EdgeDB,
        interval_seconds: int = 30,
    ):
        self.worker = worker
        self.db = db
        self.interval_seconds = interval_seconds
        self.catchup_interval_seconds = _env_int("FORWARD_CATCHUP_INTERVAL_SECONDS", 0)
        self.catchup_threshold = _env_int("FORWARD_CATCHUP_THRESHOLD", 2000)
        self._stop = threading.Event()
        self._in_catchup = False

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _pending_count(self) -> int:
        try:
            return self.db.counts()["pending_forward"]
        except Exception:
            return 0

    def _sleep_seconds(self) -> int:
        if self._pending_count() >= self.catchup_threshold:
            return self.catchup_interval_seconds
        return self.interval_seconds

    def _run(self) -> None:
        while not self._stop.wait(self._sleep_seconds()):
            try:
                pending_before = self._pending_count()
                in_catchup = pending_before >= self.catchup_threshold
                if in_catchup and not self._in_catchup:
                    logger.info(
                        "Forward catch-up mode: pending=%d (batch up to %d, interval %ds)",
                        pending_before,
                        forward_batch_size_for_pending(pending_before),
                        self.catchup_interval_seconds,
                    )
                self._in_catchup = in_catchup
                self.worker.run_once()
            except Exception:
                logger.error("BackgroundForwardLoop tick failed", exc_info=True)


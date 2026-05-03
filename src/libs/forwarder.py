from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set
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

    def send(self, *, asset: str, day: str, points: List[Dict]) -> None:
        if self.debug:
            logger.setLevel(logging.DEBUG)

        channels: Set[str] = set()
        for p in points:
            ch = p.get("channel")
            if ch:
                channels.add(str(ch))

        if not channels:
            return

        client_key = f"{self.base_client_key}.ch{len(channels)}"
        run_name = f"{asset}.{day}"

        def _send_via_sift_client() -> None:
            from sift_client import SiftClient  # type: ignore
            from sift_client.sift_types.channel import ChannelDataType  # type: ignore
            from sift_client.sift_types.ingestion import (  # type: ignore
                ChannelConfig,
                FlowConfig,
                IngestionConfigCreate,
            )

            grpc_u = self.grpc_url
            if "://" not in grpc_u:
                grpc_u = f"https://{grpc_u}"

            if not self.rest_url:
                raise RuntimeError("Missing SIFT_REST_URL required by sift_client.")

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
            client = SiftClient(api_key=self.api_key, grpc_url=grpc_u, rest_url=self.rest_url)

            async def _send_all():
                ing = await client.async_.ingestion.create_ingestion_config_streaming_client(
                    ingestion_cfg,
                    run=run_name,
                )
                async with ing:
                    for p in points:
                        ts = datetime.fromisoformat(p["ts"].replace("Z", "+00:00"))
                        await ing.send(flow_cfg.as_flow(timestamp=ts, values={p["channel"]: float(p["value"])}))
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
                for p in points:
                    ts = datetime.fromisoformat(p["ts"].replace("Z", "+00:00"))
                    values = [IngestWithConfigDataChannelValue(empty=Empty()) for _ in ordered_channels]
                    idx = channel_idx.get(str(p["channel"]))
                    if idx is not None:
                        values[idx] = IngestWithConfigDataChannelValue(double=float(p["value"]))
                    ingestion_service.ingest_flows(
                        {
                            "flow_name": self.flow_name,
                            "timestamp": ts,
                            "channel_values": values,
                        }
                    )

        if self.prefer_client == "py":
            _send_via_sift_py()
            return

        try:
            _send_via_sift_client()
        except Exception as e:
            msg = str(e)
            if "BadSignature" in msg or "InvalidUri" in msg:
                logger.warning(
                    "sift_client transport failed (%s). Falling back to deprecated sift_py transport. "
                    "To force one or the other set SIFT_SDK_PREFER=client|py.",
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
        batch_size: int = 500,
    ):
        self.db = db
        self.forwarder = forwarder
        self.asset = asset
        self.batch_size = batch_size

    def run_once(self) -> ForwardResult:
        try:
            pending = self.db.get_pending_measurements(limit=self.batch_size)
        except Exception as e:
            logger.error("get_pending_measurements failed: %s", e, exc_info=True)
            return ForwardResult(attempted=0, forwarded=0, error=str(e))

        if not pending:
            return ForwardResult(attempted=0, forwarded=0)

        points = [self._to_point(m) for m in pending]
        day = pending[0].ts[:10]
        ids = [m.id for m in pending]

        try:
            self.forwarder.send(asset=self.asset, day=day, points=points)
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
                details={"count": len(ids), "day": day},
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
                    details={"count": len(ids), "day": day, "error": str(e)},
                )
            except Exception:
                pass
            return ForwardResult(attempted=len(ids), forwarded=len(ids), error=err)
        return ForwardResult(attempted=len(ids), forwarded=len(ids))

    def _to_point(self, m: PendingMeasurement) -> Dict:
        return {"ts": m.ts, "channel": m.channel, "value": m.value}


class BackgroundForwardLoop:
    def __init__(self, *, worker: ForwardWorker, interval_seconds: int = 30):
        self.worker = worker
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.worker.run_once()
            except Exception:
                logger.error("BackgroundForwardLoop tick failed", exc_info=True)


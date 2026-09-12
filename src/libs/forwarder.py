from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    by_ts: Dict[str, Dict[str, Any]] = {}
    for p in points:
        ts = str(p["ts"])
        ch = str(p["channel"])
        raw = float(p["value"])
        val: Any = bool(raw) if is_bool_channel(ch) else raw
        by_ts.setdefault(ts, {})[ch] = val
    return [{"ts": ts, "values": vals} for ts, vals in sorted(by_ts.items())]


def is_bool_channel(channel: str) -> bool:
    """Irrigation on/off channels are forwarded to Sift as BOOL."""
    return channel.startswith("irrigation_state.") or channel.startswith("irrigation.")


def flow_name_from_channels(channels: Iterable[str], *, recovery: int = 0) -> str:
    """
    Stable Sift flow name for a channel set (sorted SHA-256, 16 hex chars).

    Irrigation and ecowitt each get one flow per distinct channel set; if channels
    are added or removed, the hash changes and Sift registers a new flow.

    When `recovery > 0`, salt is mixed into the hash so a fresh flow can be used if
    Sift already has a partial/broken registration for the base name (flows cannot
    be deleted in Sift).
    """
    ordered = ",".join(sorted({str(c) for c in channels if c}))
    if not ordered:
        raise ValueError("flow_name_from_channels requires at least one channel")
    if recovery > 0:
        ordered = f"{ordered},__recover:{recovery}"
    return hashlib.sha256(ordered.encode()).hexdigest()[:16]


def _group_points_by_flow(points: List[Dict]) -> Dict[str, List[Dict]]:
    """One hashed flow per channel family (irrigation BOOLs, ecowitt doubles)."""
    irrigation_points: List[Dict] = []
    ecowitt_points: List[Dict] = []
    irrigation_channels: Set[str] = set()
    ecowitt_channels: Set[str] = set()

    for p in points:
        ch = str(p.get("channel", ""))
        if is_bool_channel(ch):
            irrigation_channels.add(ch)
            irrigation_points.append(p)
        else:
            ecowitt_channels.add(ch)
            ecowitt_points.append(p)

    by_flow: Dict[str, List[Dict]] = {}
    if irrigation_points:
        by_flow[flow_name_from_channels(irrigation_channels)] = irrigation_points
    if ecowitt_points:
        by_flow[flow_name_from_channels(ecowitt_channels)] = ecowitt_points
    return by_flow


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _summarize_forward_error(err: str, *, max_len: int = 180) -> str:
    """Collapse noisy gRPC UNAVAILABLE blobs into a short, stable key."""
    text = " ".join((err or "").split())
    lower = text.lower()
    if lower.startswith("connectivity_offline"):
        return text if len(text) <= max_len else text[: max_len - 3] + "..."
    if "dns" in lower or "hostname lookup" in lower or "address lookup failed" in lower:
        return "dns_resolve_failed:grpc-api.siftstack.com"
    if "failed to connect to all addresses" in lower:
        return "connect_failed:sift_grpc"
    if "ping timeout" in lower:
        return "ping_timeout:sift_grpc"
    if "recvmsg:connection timed out" in lower:
        return "recv_timeout:sift_grpc"
    if "unavailable" in lower:
        return "unavailable:sift_grpc"
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _sift_grpc_hostname() -> str:
    raw = (
        os.getenv("SIFT_GRPC_URL")
        or os.getenv("SIFT_GRPC_URI")
        or os.getenv("SIFT_GRPC")
        or "grpc-api.siftstack.com"
    ).strip()
    if "://" in raw:
        host = urlparse(raw).hostname or ""
        return host or "grpc-api.siftstack.com"
    # host or host:port
    return raw.split(":")[0] or "grpc-api.siftstack.com"


def probe_sift_connectivity(*, timeout_seconds: Optional[float] = None) -> bool:
    """
    Cheap reachability check: DNS resolve of the Sift gRPC host.

    Used to detect internet/DNS restoration without hanging on a full gRPC attempt.
    """
    if timeout_seconds is None:
        timeout_seconds = _env_float("FORWARD_CONNECTIVITY_PROBE_TIMEOUT_SECONDS", 3.0)
    host = _sift_grpc_hostname()
    if not host:
        return False

    def _resolve() -> None:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_resolve)
            fut.result(timeout=max(0.5, float(timeout_seconds)))
        return True
    except Exception:
        return False


def is_connectivity_error(summary: str) -> bool:
    s = (summary or "").lower()
    return (
        s.startswith("connectivity_offline")
        or "dns_resolve_failed" in s
        or "connect_failed" in s
        or "recv_timeout" in s
        or "ping_timeout" in s
    )


class ForwardSyncHealth:
    """
    In-process forwarder health for /health, logging, backoff, and self-restart.

    Persist nothing here — sqlite system_events remain the durable trail, but we
    rate-limit how often identical failures are written.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_attempt_at: Optional[datetime] = None
        self.last_success_at: Optional[datetime] = None
        self.last_error_at: Optional[datetime] = None
        self.first_failure_at: Optional[datetime] = None
        self.last_error_summary: Optional[str] = None
        self.consecutive_failures: int = 0
        self.total_failures: int = 0
        self.total_successes: int = 0
        self._last_event_error_key: Optional[str] = None
        self._last_event_at: Optional[datetime] = None
        self._last_row_error_key: Optional[str] = None
        self.restart_requested: bool = False
        self.connectivity_ok: Optional[bool] = None

    def note_connectivity(self, online: bool) -> Optional[str]:
        """
        Update connectivity flag. Returns 'restored' | 'lost' | None when unchanged/first sighting.
        """
        with self._lock:
            prev = self.connectivity_ok
            self.connectivity_ok = online
        if prev is False and online:
            return "restored"
        if prev is True and not online:
            return "lost"
        return None

    def note_connectivity_restored(self) -> None:
        """Soft-reset backoff after the network comes back so we retry immediately."""
        with self._lock:
            self.consecutive_failures = 0
            self.first_failure_at = None
            self.restart_requested = False
            # Force a fresh system_event if the next send still fails.
            self._last_event_error_key = None
            self._last_row_error_key = None
        logger.info("Connectivity restored — reset forward backoff for immediate retry")

    def record_success(self, *, forwarded: int) -> None:
        now = _utc_now()
        with self._lock:
            self.last_attempt_at = now
            self.last_success_at = now
            self.consecutive_failures = 0
            self.first_failure_at = None
            self.total_successes += 1
            self.last_error_summary = None
            self._last_event_error_key = None
            self._last_row_error_key = None
            self.restart_requested = False
        if forwarded:
            logger.debug("Forward success recorded (forwarded=%d)", forwarded)

    def record_failure(self, error: str) -> Dict[str, Any]:
        """
        Update failure counters.

        Returns flags for the worker:
        - should_log_event: write a system_events row (rate-limited)
        - should_mark_rows: update measurements.forward_error (rate-limited)
        - summary: short error key
        """
        now = _utc_now()
        summary = _summarize_forward_error(error)
        event_interval = _env_float("FORWARD_ERROR_LOG_INTERVAL_SECONDS", 300.0)
        with self._lock:
            self.last_attempt_at = now
            self.last_error_at = now
            self.last_error_summary = summary
            if self.consecutive_failures == 0:
                self.first_failure_at = now
            self.consecutive_failures += 1
            self.total_failures += 1
            failures = self.consecutive_failures

            should_log_event = (
                summary != self._last_event_error_key
                or self._last_event_at is None
                or (now - self._last_event_at).total_seconds() >= event_interval
            )
            if should_log_event:
                self._last_event_error_key = summary
                self._last_event_at = now

            should_mark_rows = summary != self._last_row_error_key
            if should_mark_rows:
                self._last_row_error_key = summary

        if should_log_event:
            logger.error(
                "Forward failed (%dx): %s",
                failures,
                summary,
            )
            if "dns_resolve" in summary:
                logger.error(
                    "Sift DNS failing — Pi resolv.conf may be Tailscale MagicDNS-only; "
                    "see runbooks (DNS resilience). consecutive_failures=%d",
                    failures,
                )
        else:
            logger.warning(
                "Forward still failing (%dx): %s",
                failures,
                summary,
            )

        return {
            "summary": summary,
            "should_log_event": should_log_event,
            "should_mark_rows": should_mark_rows,
            "consecutive_failures": failures,
        }

    def snapshot(self, *, pending_forward: int = 0) -> Dict[str, Any]:
        stale_after = _env_float("FORWARD_STALE_SECONDS", 1800.0)
        restart_after = _env_float("FORWARD_RESTART_AFTER_SECONDS", 3600.0)
        with self._lock:
            last_success = self.last_success_at
            last_attempt = self.last_attempt_at
            last_error_at = self.last_error_at
            last_error = self.last_error_summary
            consecutive = self.consecutive_failures
            total_fail = self.total_failures
            total_ok = self.total_successes
            first_failure = self.first_failure_at
            connectivity_ok = self.connectivity_ok

        success_age: Optional[float] = None
        if last_success is not None:
            success_age = max(0.0, (_utc_now() - last_success).total_seconds())

        streak: Optional[float] = None
        if consecutive > 0 and first_failure is not None:
            streak = max(0.0, (_utc_now() - first_failure).total_seconds())

        degraded = False
        reason: Optional[str] = None
        if pending_forward > 0 and consecutive > 0:
            success_stale = (
                last_success is not None
                and success_age is not None
                and success_age >= stale_after
            )
            streak_stale = streak is not None and streak >= stale_after
            if success_stale or streak_stale:
                degraded = True
                if connectivity_ok is False:
                    reason = "connectivity_offline"
                else:
                    reason = "forward_stale" if last_success is not None else "forward_failing"

        return {
            "ok": not degraded,
            "degraded": degraded,
            "reason": reason,
            "pending_forward": pending_forward,
            "connectivity_ok": connectivity_ok,
            "last_attempt_at": _iso(last_attempt) if last_attempt else None,
            "last_success_at": _iso(last_success) if last_success else None,
            "last_error_at": _iso(last_error_at) if last_error_at else None,
            "last_error": last_error,
            "consecutive_failures": consecutive,
            "failure_streak_seconds": int(streak) if streak is not None else None,
            "total_failures": total_fail,
            "total_successes": total_ok,
            "success_age_seconds": int(success_age) if success_age is not None else None,
            "stale_after_seconds": int(stale_after),
            "restart_after_seconds": int(restart_after),
        }

    def failure_streak_seconds(self) -> Optional[float]:
        with self._lock:
            if self.consecutive_failures <= 0 or self.first_failure_at is None:
                return None
            return max(0.0, (_utc_now() - self.first_failure_at).total_seconds())

    def should_restart(self, *, pending_forward: int, connectivity_ok: bool = True) -> bool:
        """
        Exit the process so systemd Restart=always can clear stuck gRPC/DNS client state.

        Does not restart while the network probe says we are offline — that cannot help
        until internet/DNS returns.
        """
        if not _env_bool("FORWARD_WATCHDOG_ENABLED", True):
            return False
        if not connectivity_ok:
            return False
        if pending_forward <= 0:
            return False
        # Prefer restart when online but still failing (stuck client), not during outages.
        with self._lock:
            err = self.last_error_summary or ""
        if is_connectivity_error(err) and self.connectivity_ok is False:
            return False
        restart_after = _env_float("FORWARD_RESTART_AFTER_SECONDS", 3600.0)
        streak = self.failure_streak_seconds()
        if streak is None or streak < restart_after:
            return False
        with self._lock:
            if self.restart_requested:
                return False
            self.restart_requested = True
            return True

    def backoff_seconds(self, base_interval: int) -> int:
        """Exponential backoff while failing; capped. Success path uses base_interval."""
        max_backoff = int(_env_float("FORWARD_BACKOFF_MAX_SECONDS", 300.0))
        with self._lock:
            failures = self.consecutive_failures
        if failures <= 0:
            return base_interval
        # 30, 60, 120, 240, ... up to max
        delay = min(max_backoff, int(base_interval * (2 ** min(failures - 1, 6))))
        return max(base_interval, delay)


def _sift_ingest_log_enabled() -> bool:
    """Verbose Sift registration + ingest tracing (SIFT_INGEST_LOG, else SIFT_DEBUG)."""
    raw = os.getenv("SIFT_INGEST_LOG", "").strip()
    if raw:
        return _env_bool("SIFT_INGEST_LOG", False)
    return _env_bool("SIFT_DEBUG", False)


def _sift_ingest_log_sample_n() -> int:
    raw = os.getenv("SIFT_INGEST_LOG_SAMPLE_N", "").strip()
    if raw:
        return max(1, int(raw))
    raw = os.getenv("SIFT_DEBUG_SAMPLE_N", "").strip()
    if raw:
        return max(1, int(raw))
    return 5


def _log_sift_ingest(msg: str, *args, **kwargs) -> None:
    if _sift_ingest_log_enabled():
        logger.info(msg, *args, **kwargs)


def _channel_data_type_label(channel: str) -> str:
    return "BOOL" if is_bool_channel(channel) else "DOUBLE"


def _format_scalar_value(val: Any) -> str:
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, float):
        return f"{val:g}"
    return str(val)


def _summarize_coalesced_values(ordered_names: List[str], row_values: Dict[str, Any]) -> str:
    parts: List[str] = []
    for idx, name in enumerate(ordered_names):
        if name in row_values:
            parts.append(f"[{idx}] {name}={_format_scalar_value(row_values[name])}")
        else:
            parts.append(f"[{idx}] {name}=<empty>")
    return "; ".join(parts)


def _summarize_protobuf_channel_value(pb: Any) -> str:
    if hasattr(pb, "HasField"):
        if pb.HasField("bool"):
            return f"bool={str(pb.bool).lower()}"
        if pb.HasField("double"):
            return f"double={pb.double:g}"
        if pb.HasField("empty"):
            return "<empty>"
    which = pb.WhichOneof("channel_value") if hasattr(pb, "WhichOneof") else None
    if which == "bool":
        return f"bool={str(pb.bool).lower()}"
    if which == "double":
        return f"double={pb.double:g}"
    if which in (None, "empty"):
        return "<empty>"
    return which or "<?>"

def _summarize_protobuf_channel_values(ordered_names: List[str], values: List[Any]) -> str:
    parts: List[str] = []
    for idx, name in enumerate(ordered_names):
        if idx >= len(values):
            parts.append(f"[{idx}] {name}=<missing>")
            continue
        parts.append(f"[{idx}] {name}={_summarize_protobuf_channel_value(values[idx])}")
    return "; ".join(parts)


def _flow_channels_in_order(
    transport_channel,
    ingestion_config_id: str,
    flow_name: str,
) -> List[str]:
    from sift_py.ingestion._internal.ingestion_config import get_ingestion_config_flows  # type: ignore

    ordered: List[str] = []
    for flow in get_ingestion_config_flows(transport_channel, ingestion_config_id):
        if flow.name != flow_name:
            continue
        for ch in flow.channels:
            ordered.append(str(ch.name))
    return ordered


def _log_ingestion_config_flow_snapshot(
    transport_channel,
    ingestion_config_id: str,
    *,
    client_key: str,
    asset: str,
) -> None:
    if not _sift_ingest_log_enabled():
        return
    from sift_py.ingestion._internal.ingestion_config import get_ingestion_config_flows  # type: ignore

    flows = get_ingestion_config_flows(transport_channel, ingestion_config_id)
    _log_sift_ingest(
        "Sift ListIngestionConfigFlows ingestion_config_id=%s client_key=%s asset=%s flow_count=%d",
        ingestion_config_id,
        client_key,
        asset,
        len(flows),
    )
    for flow in sorted(flows, key=lambda f: f.name):
        channel_desc = ", ".join(
            f"{ch.name}({_channel_data_type_label(str(ch.name))})" for ch in flow.channels
        )
        _log_sift_ingest("  flow %s: %s", flow.name, channel_desc or "(no channels)")


def _sift_py_channel_value(channel: str, val: Any):
    from google.protobuf.empty_pb2 import Empty  # type: ignore
    from sift.ingest.v1.ingest_pb2 import IngestWithConfigDataChannelValue  # type: ignore

    if is_bool_channel(channel):
        return IngestWithConfigDataChannelValue(bool=bool(val))
    return IngestWithConfigDataChannelValue(double=float(val))


def _registered_flow_channels(
    transport_channel,
    ingestion_config_id: str,
    flow_name: str,
) -> Set[str]:
    from sift_py.ingestion._internal.ingestion_config import get_ingestion_config_flows  # type: ignore

    registered: Set[str] = set()
    registered_order: List[str] = []
    for flow in get_ingestion_config_flows(transport_channel, ingestion_config_id):
        if flow.name != flow_name:
            continue
        for ch in flow.channels:
            name = str(ch.name)
            registered.add(name)
            registered_order.append(name)
    if _sift_ingest_log_enabled():
        _log_sift_ingest(
            "Sift ListIngestionConfigFlows lookup flow=%s ingestion_config_id=%s registered_count=%d order=[%s]",
            flow_name,
            ingestion_config_id,
            len(registered_order),
            ", ".join(registered_order) or "(none)",
        )
    return registered


def _resolve_sift_flow_name(
    transport_channel,
    ingestion_config_id: str,
    channels: List[str],
    *,
    max_recovery: int = 20,
) -> str:
    """
    Pick a flow name whose Sift registration matches the full channel set.

    If the base hash flow exists with only a subset of channels (common after a
    failed smoke test), bump recovery salt until an unused or complete flow is found.
    """
    required = sorted({str(c) for c in channels if c})
    if not required:
        raise ValueError("_resolve_sift_flow_name requires at least one channel")

    _log_sift_ingest(
        "Sift resolve flow name required_channels=[%s] ingestion_config_id=%s",
        ", ".join(required),
        ingestion_config_id,
    )

    for recovery in range(max_recovery):
        name = flow_name_from_channels(required, recovery=recovery)
        registered = _registered_flow_channels(transport_channel, ingestion_config_id, name)
        if not registered or registered == set(required):
            _log_sift_ingest(
                "Sift resolve flow name -> %s (recovery=%d, registered=%d)",
                name,
                recovery,
                len(registered),
            )
            if recovery > 0:
                logger.warning(
                    "Using Sift flow %s (recovery=%d) for channels: %s",
                    name,
                    recovery,
                    ", ".join(required),
                )
            return name
        logger.warning(
            "Sift flow %s partially registered (%s); trying recovery %d",
            name,
            ", ".join(sorted(registered)),
            recovery + 1,
        )

    raise RuntimeError(
        f"Could not resolve a Sift flow for channels {required} after {max_recovery} attempts"
    )


def _ensure_sift_py_flow_channels(
    transport_channel,
    ingestion_config_id: str,
    flow_name: str,
    channels: List[str],
) -> None:
    """
    Ensure a Sift flow exists with exactly the requested channels.

    Sift rejects ingests when the payload channel count differs from the flow
  registration (e.g. a partial flow left over from an earlier smoke test).
    """
    import grpc
    from grpc import StatusCode
    from sift_py.ingestion._internal.ingestion_config import create_flow_configs  # type: ignore
    from sift_py.ingestion.channel import ChannelConfig, ChannelDataType  # type: ignore
    from sift_py.ingestion.config.telemetry import FlowConfig  # type: ignore

    required = sorted({str(ch) for ch in channels if ch})
    if not required:
        return

    registered = _registered_flow_channels(transport_channel, ingestion_config_id, flow_name)
    missing = [ch for ch in required if ch not in registered]
    if not missing:
        _log_sift_ingest(
            "Sift flow %s already registered with %d channel(s): [%s]",
            flow_name,
            len(required),
            ", ".join(required),
        )
        return

    _log_sift_ingest(
        "Sift ensure flow %s ingestion_config_id=%s required=[%s] registered=[%s] missing=[%s]",
        flow_name,
        ingestion_config_id,
        ", ".join(required),
        ", ".join(sorted(registered)) or "(none)",
        ", ".join(missing),
    )

    def _channel_configs(names: List[str]):
        return [
            ChannelConfig(
                name=ch,
                data_type=ChannelDataType.BOOL if is_bool_channel(ch) else ChannelDataType.DOUBLE,
            )
            for ch in names
        ]

    if not registered:
        batch_desc = ", ".join(
            f"{ch}({_channel_data_type_label(ch)})" for ch in missing
        )
        _log_sift_ingest(
            "Sift CreateIngestionConfigFlows flow=%s batch channels=[%s]",
            flow_name,
            batch_desc,
        )
        try:
            create_flow_configs(
                transport_channel,
                ingestion_config_id,
                [FlowConfig(name=flow_name, channels=_channel_configs(missing))],
            )
            logger.info(
                "Registered Sift flow %s with %d channel(s): %s",
                flow_name,
                len(missing),
                ", ".join(missing),
            )
            after = _flow_channels_in_order(transport_channel, ingestion_config_id, flow_name)
            _log_sift_ingest(
                "Sift CreateIngestionConfigFlows flow=%s post-register order=[%s]",
                flow_name,
                ", ".join(after) or "(none)",
            )
            return
        except grpc.RpcError as e:
            _log_sift_ingest(
                "Sift CreateIngestionConfigFlows flow=%s failed: %s %s",
                flow_name,
                e.code(),
                getattr(e, "details", lambda: str(e))(),
            )
            if e.code() != StatusCode.ALREADY_EXISTS:
                raise
            registered = _registered_flow_channels(transport_channel, ingestion_config_id, flow_name)
            missing = [ch for ch in required if ch not in registered]
            if not missing:
                return

    added: List[str] = []
    for ch in missing:
        flow_cfg = FlowConfig(name=flow_name, channels=_channel_configs([ch]))
        _log_sift_ingest(
            "Sift CreateIngestionConfigFlows flow=%s single channel=%s (%s)",
            flow_name,
            ch,
            _channel_data_type_label(ch),
        )
        try:
            create_flow_configs(transport_channel, ingestion_config_id, [flow_cfg])
            added.append(ch)
        except grpc.RpcError as e:
            _log_sift_ingest(
                "Sift CreateIngestionConfigFlows flow=%s channel=%s failed: %s %s",
                flow_name,
                ch,
                e.code(),
                getattr(e, "details", lambda: str(e))(),
            )
            if e.code() == StatusCode.ALREADY_EXISTS:
                continue
            raise

    if added:
        logger.info(
            "Registered %d Sift channel(s) on flow %s: %s",
            len(added),
            flow_name,
            ", ".join(added),
        )

    registered = _registered_flow_channels(transport_channel, ingestion_config_id, flow_name)
    still_missing = [ch for ch in required if ch not in registered]
    after_order = _flow_channels_in_order(transport_channel, ingestion_config_id, flow_name)
    _log_sift_ingest(
        "Sift ensure flow %s final registered order=[%s]",
        flow_name,
        ", ".join(after_order) or "(none)",
    )
    if still_missing:
        logger.error(
            "Sift flow %s still missing channels %s after registration (registered: %s)",
            flow_name,
            still_missing,
            sorted(registered),
        )


class MeasurementForwarder:
    def send(self, *, asset: str, day: str, points: List[Dict]) -> None:
        raise NotImplementedError()

    def reset_transport(self) -> None:
        """Drop cached clients/channels so the next send reconnects cleanly."""
        return


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
        normalized = []
        for p in points:
            ch = str(p["channel"])
            val: Any = p["value"]
            if is_bool_channel(ch):
                val = bool(float(val))
            normalized.append({**p, "value": val})
        rec = {"ts": _iso(_utc_now()), "asset": asset, "day": day, "points": normalized}
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
        self.irrigation_client_key = (
            os.getenv("SIFT_IRRIGATION_INGESTION_CLIENT_KEY", "").strip() or self.base_client_key
        )
        self.prefer_client = os.getenv("SIFT_SDK_PREFER", "client").strip().lower()  # client|py
        self.debug = os.getenv("SIFT_DEBUG", "0").strip() in ("1", "true", "yes", "on")
        self.debug_sample_n = int(os.getenv("SIFT_DEBUG_SAMPLE_N", "3"))

        if not self.api_key or not self.grpc_url:
            raise RuntimeError(
                "Missing Sift config. Set SIFT_API_KEY and SIFT_GRPC_URL (or use SIFT_MODE=fake)."
            )

        self._sift_client = None
        self._sift_client_lock = threading.Lock()
        self._logged_flows: Set[str] = set()
        self._resolved_flow_names: Dict[str, str] = {}
        self._logged_ingestion_config_snapshot: Set[str] = set()
        self.ingest_log = _sift_ingest_log_enabled()
        self.ingest_log_sample_n = _sift_ingest_log_sample_n()
        # After sift_client TLS/connect failures on this host, stick to sift_py for the process.
        self._use_sift_py_only = self.prefer_client == "py"

    def reset_transport(self) -> None:
        with self._sift_client_lock:
            client = self._sift_client
            self._sift_client = None
        if client is not None:
            logger.info("Reset Sift gRPC client after connectivity change")
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("SiftClient.close failed during reset", exc_info=True)

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

    def _client_key_for_channel(self, channel: str) -> str:
        ch = str(channel)
        if ch.startswith("irrigation_state."):
            return self.irrigation_client_key
        if ch.startswith("irrigation."):
            return self.base_client_key
        return self.base_client_key

    def _send_day(self, *, asset: str, day: str, points: List[Dict]) -> None:
        by_client_key: Dict[str, List[Dict]] = {}
        for p in points:
            ch = str(p.get("channel", ""))
            if not ch:
                continue
            key = self._client_key_for_channel(ch)
            by_client_key.setdefault(key, []).append(p)

        for client_key, subset in by_client_key.items():
            self._send_day_for_client_key(
                asset=asset,
                day=day,
                points=subset,
                client_key=client_key,
            )

    def _send_day_for_client_key(
        self, *, asset: str, day: str, points: List[Dict], client_key: str
    ) -> None:
        points_by_flow = _group_points_by_flow(points)
        if not points_by_flow:
            return

        run_name = f"{asset}.{day}"

        def _flow_channel_configs(flow_name: str, flow_points: List[Dict]):
            from sift_client.sift_types.channel import ChannelDataType  # type: ignore
            from sift_client.sift_types.ingestion import ChannelConfig  # type: ignore

            channels: Set[str] = set()
            for p in flow_points:
                ch = p.get("channel")
                if ch:
                    channels.add(str(ch))
            return sorted(channels), [
                ChannelConfig(
                    name=ch,
                    data_type=ChannelDataType.BOOL if is_bool_channel(ch) else ChannelDataType.DOUBLE,
                    unit=None,
                )
                for ch in sorted(channels)
            ]

        def _send_via_sift_client() -> None:
            from sift_client.sift_types.ingestion import (  # type: ignore
                FlowConfig,
                IngestionConfigCreate,
            )

            grpc_u = self._sift_client_grpc_url()
            client = self._get_sift_client()

            flow_cfgs = {}
            flow_coalesced = {}
            for flow_name, flow_points in points_by_flow.items():
                ordered, channel_cfgs = _flow_channel_configs(flow_name, flow_points)
                if not ordered:
                    continue
                flow_cfgs[flow_name] = FlowConfig(name=flow_name, channels=channel_cfgs)
                flow_coalesced[flow_name] = _coalesce_points_by_timestamp(flow_points)

            if self.debug:
                safe_key = (self.api_key[:6] + "…" + self.api_key[-4:]) if self.api_key else "(missing)"
                logger.debug(
                    "sift_client send start asset=%s flows=%s run=%s client_key=%s points=%d grpc_url=%s rest_url=%s api_key=%s",
                    asset,
                    sorted(flow_cfgs.keys()),
                    run_name,
                    client_key,
                    len(points),
                    grpc_u,
                    self.rest_url,
                    safe_key,
                )

            if self.ingest_log:
                for flow_name, flow_cfg in flow_cfgs.items():
                    ch_desc = ", ".join(
                        f"{c.name}({_channel_data_type_label(c.name)})" for c in flow_cfg.channels
                    )
                    _log_sift_ingest(
                        "sift_client IngestionConfigCreate asset=%s client_key=%s run=%s flow=%s channels=[%s]",
                        asset,
                        client_key,
                        run_name,
                        flow_name,
                        ch_desc,
                    )

            ingestion_cfg = IngestionConfigCreate(
                asset_name=asset,
                client_key=client_key,
                flows=list(flow_cfgs.values()),
            )

            async def _send_all():
                ing = await client.async_.ingestion.create_ingestion_config_streaming_client(
                    ingestion_cfg,
                    run=run_name,
                )
                async with ing:
                    for flow_name, rows in flow_coalesced.items():
                        flow_cfg = flow_cfgs[flow_name]
                        ordered_names = [c.name for c in flow_cfg.channels]
                        logged_this_flow = 0
                        for row in rows:
                            ts = _parse_point_timestamp(row["ts"])
                            if self.ingest_log and logged_this_flow < self.ingest_log_sample_n:
                                _log_sift_ingest(
                                    "sift_client IngestWithConfigDataStream flow=%s run=%s ts=%s payload=[%s]",
                                    flow_name,
                                    run_name,
                                    row["ts"],
                                    _summarize_coalesced_values(ordered_names, row["values"]),
                                )
                                logged_this_flow += 1
                            await ing.send(flow_cfg.as_flow(timestamp=ts, values=row["values"]))
                        if self.ingest_log and len(rows) > logged_this_flow:
                            _log_sift_ingest(
                                "sift_client IngestWithConfigDataStream flow=%s ... %d more row(s) omitted from log",
                                flow_name,
                                len(rows) - logged_this_flow,
                            )
                    await ing.finish()

            _run_coroutine_sync(_send_all())

        def _send_via_sift_py() -> None:
            from google.protobuf.empty_pb2 import Empty  # type: ignore
            from sift.ingest.v1.ingest_pb2 import IngestWithConfigDataChannelValue  # type: ignore
            from sift_py.grpc.transport import SiftChannelConfig, use_sift_channel  # type: ignore
            from sift_py.ingestion.channel import ChannelConfig, ChannelDataType  # type: ignore
            from sift_py.ingestion.config.telemetry import FlowConfig, TelemetryConfig  # type: ignore
            from sift_py.ingestion.service import IngestionService  # type: ignore

            grpc_uri = _normalize_sift_py_grpc_uri(self.grpc_url)
            flow_cfgs: Dict[str, FlowConfig] = {}
            flow_coalesced: Dict[str, List[Dict[str, Any]]] = {}
            flow_channel_idx: Dict[str, Dict[str, int]] = {}

            for flow_name, flow_points in points_by_flow.items():
                channels: Set[str] = set()
                for p in flow_points:
                    ch = p.get("channel")
                    if ch:
                        channels.add(str(ch))
                ordered = sorted(channels)
                if not ordered:
                    continue
                flow_cfgs[flow_name] = FlowConfig(
                    name=flow_name,
                    channels=[
                        ChannelConfig(
                            name=ch,
                            data_type=ChannelDataType.BOOL if is_bool_channel(ch) else ChannelDataType.DOUBLE,
                        )
                        for ch in ordered
                    ],
                )
                flow_channel_idx[flow_name] = {ch: i for i, ch in enumerate(ordered)}
                flow_coalesced[flow_name] = _coalesce_points_by_timestamp(flow_points)

            telemetry_config = TelemetryConfig(
                asset_name=asset,
                ingestion_client_key=client_key,
                flows=list(flow_cfgs.values()),
            )

            if self.ingest_log:
                _log_sift_ingest(
                    "sift_py batch start asset=%s client_key=%s run=%s day=%s sqlite_points=%d coalesced_flows=%s",
                    asset,
                    client_key,
                    run_name,
                    day,
                    len(points),
                    ", ".join(sorted(flow_coalesced.keys())),
                )
                for base_name, cfg in flow_cfgs.items():
                    ch_desc = ", ".join(
                        f"{c.name}({_channel_data_type_label(c.name)})" for c in cfg.channels
                    )
                    _log_sift_ingest(
                        "sift_py TelemetryConfig base_flow=%s channels=[%s] coalesced_rows=%d",
                        base_name,
                        ch_desc,
                        len(flow_coalesced.get(base_name, [])),
                    )

            sift_channel_config = SiftChannelConfig(uri=grpc_uri, apikey=self.api_key)
            with use_sift_channel(sift_channel_config) as channel:
                _log_sift_ingest(
                    "sift_py IngestionService init asset=%s client_key=%s force_lazy_flow_creation=true flows=%d",
                    asset,
                    client_key,
                    len(flow_cfgs),
                )
                ingestion_service = IngestionService(
                    channel,
                    telemetry_config,
                    force_lazy_flow_creation=True,
                )
                ingestion_service.attach_run(channel, run_name)
                ingestion_config_id = ingestion_service.ingestion_config.ingestion_config_id
                run_id = getattr(ingestion_service, "run_id", None)
                _log_sift_ingest(
                    "sift_py IngestionService ready ingestion_config_id=%s run=%s run_id=%s lazy=%s",
                    ingestion_config_id,
                    run_name,
                    run_id or "(none)",
                    getattr(ingestion_service, "use_lazy_flow_creation", "?"),
                )
                if ingestion_config_id not in self._logged_ingestion_config_snapshot:
                    _log_ingestion_config_flow_snapshot(
                        channel,
                        ingestion_config_id,
                        client_key=client_key,
                        asset=asset,
                    )
                    self._logged_ingestion_config_snapshot.add(ingestion_config_id)
                for base_flow_name, rows in flow_coalesced.items():
                    ordered_names = [c.name for c in flow_cfgs[base_flow_name].channels]
                    cache_key = f"{client_key}:{base_flow_name}:{','.join(ordered_names)}"
                    flow_name = self._resolved_flow_names.get(cache_key)
                    if flow_name is None:
                        flow_name = _resolve_sift_flow_name(
                            channel,
                            ingestion_config_id,
                            ordered_names,
                        )
                        self._resolved_flow_names[cache_key] = flow_name
                    if flow_name != base_flow_name:
                        flow_cfgs[base_flow_name].name = flow_name
                        _log_sift_ingest(
                            "sift_py flow name resolved base_hash=%s -> ingest_flow=%s cache_key=%s",
                            base_flow_name,
                            flow_name,
                            cache_key,
                        )
                    sift_order = _flow_channels_in_order(channel, ingestion_config_id, flow_name)
                    if sift_order and sift_order != ordered_names:
                        _log_sift_ingest(
                            "sift_py channel order mismatch flow=%s local=[%s] sift=[%s]",
                            flow_name,
                            ", ".join(ordered_names),
                            ", ".join(sift_order),
                        )
                    elif self.ingest_log and sift_order:
                        _log_sift_ingest(
                            "sift_py channel order flow=%s order=[%s]",
                            flow_name,
                            ", ".join(sift_order),
                        )
                    if flow_name not in self._logged_flows:
                        self._logged_flows.add(flow_name)
                        kind = "irrigation" if any(is_bool_channel(c) for c in ordered_names) else "ecowitt"
                        logger.info(
                            "Sift %s flow %s (%d channels: %s)",
                            kind,
                            flow_name,
                            len(ordered_names),
                            ", ".join(ordered_names),
                        )
                    _ensure_sift_py_flow_channels(
                        channel,
                        ingestion_config_id,
                        flow_name,
                        ordered_names,
                    )
                    channel_idx = flow_channel_idx[base_flow_name]
                    logged_this_flow = 0
                    for row in rows:
                        ts = _parse_point_timestamp(row["ts"])
                        values = [
                            IngestWithConfigDataChannelValue(empty=Empty())
                            for _ in ordered_names
                        ]
                        for ch, val in row["values"].items():
                            idx = channel_idx.get(ch)
                            if idx is not None:
                                values[idx] = _sift_py_channel_value(ch, val)
                        if self.ingest_log and logged_this_flow < self.ingest_log_sample_n:
                            _log_sift_ingest(
                                "sift_py IngestWithConfigDataStream ingestion_config_id=%s flow=%s run=%s run_id=%s ts=%s values=[%s]",
                                ingestion_config_id,
                                flow_name,
                                run_name,
                                run_id or "(none)",
                                row["ts"],
                                _summarize_protobuf_channel_values(ordered_names, values),
                            )
                            logged_this_flow += 1
                        ingestion_service.ingest_flows(
                            {
                                "flow_name": flow_name,
                                "timestamp": ts,
                                "channel_values": values,
                            }
                        )
                    if self.ingest_log and len(rows) > logged_this_flow:
                        _log_sift_ingest(
                            "sift_py IngestWithConfigDataStream flow=%s ... %d more row(s) omitted from log",
                            flow_name,
                            len(rows) - logged_this_flow,
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
        health: Optional[ForwardSyncHealth] = None,
    ):
        self.db = db
        self.forwarder = forwarder
        self.asset = asset
        self.batch_size = batch_size or _env_int("FORWARD_BATCH_SIZE", 500)
        self.health = health or ForwardSyncHealth()

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
            self.health.record_failure(str(e))
            return ForwardResult(attempted=0, forwarded=0, error=str(e))

        if not pending:
            # Empty queue counts as healthy forward path.
            self.health.record_success(forwarded=0)
            return ForwardResult(attempted=0, forwarded=0)

        points = [self._to_point(m) for m in pending]
        ids = [m.id for m in pending]
        days = sorted({m.ts[:10] for m in pending})
        coalesced_n = len(_coalesce_points_by_timestamp(points))

        try:
            self.forwarder.send(asset=self.asset, day=days[0], points=points)
        except Exception as e:
            err = str(e)
            flags = self.health.record_failure(err)
            try:
                if flags["should_mark_rows"]:
                    self.db.mark_forward_error(ids, flags["summary"])
                if flags["should_log_event"]:
                    self.db.add_system_event(
                        level="error",
                        component="forwarder",
                        message="forward_failed",
                        details={
                            "count": len(ids),
                            "error": flags["summary"],
                            "consecutive_failures": flags["consecutive_failures"],
                            "error_detail": err[:500],
                        },
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
            self.health.record_success(forwarded=len(ids))
        except Exception as e:
            err = f"post_send_sqlite_failed:{e}"
            logger.critical(
                "Sift send succeeded but sqlite mark_forwarded failed; rows stay pending and "
                "may duplicate on retry: %s",
                e,
                exc_info=True,
            )
            self.health.record_failure(err)
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
        self._force_immediate = False

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="forward-loop")
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _pending_count(self) -> int:
        try:
            return self.db.counts()["pending_forward"]
        except Exception:
            return 0

    def _sleep_seconds(self) -> int:
        if self._force_immediate:
            self._force_immediate = False
            return 0
        pending = self._pending_count()
        if self.worker.health.consecutive_failures > 0:
            return self.worker.health.backoff_seconds(self.interval_seconds)
        if pending >= self.catchup_threshold:
            return self.catchup_interval_seconds
        return self.interval_seconds

    def _probe_enabled(self) -> bool:
        return _env_bool("FORWARD_CONNECTIVITY_PROBE", True)

    def _check_connectivity(self) -> bool:
        if not self._probe_enabled():
            return True
        # Fake/local forwarders do not need public DNS.
        if not isinstance(self.worker.forwarder, SiftSDKForwarder):
            return True
        return probe_sift_connectivity()

    def _handle_connectivity(self, online: bool, *, pending: int) -> bool:
        """
        Update health from probe. Returns True if the tick should attempt a Sift send.
        """
        transition = self.worker.health.note_connectivity(online)
        if transition == "lost":
            logger.warning(
                "Sift host unreachable (DNS/network) — pausing gRPC sends until connectivity returns"
            )
            try:
                self.db.add_system_event(
                    level="warning",
                    component="forwarder",
                    message="connectivity_lost",
                    details={"host": _sift_grpc_hostname(), "pending_forward": pending},
                )
            except Exception:
                pass
        elif transition == "restored":
            logger.info(
                "Sift host reachable again — resetting transport and retrying pending=%d",
                pending,
            )
            self.worker.health.note_connectivity_restored()
            try:
                self.worker.forwarder.reset_transport()
            except Exception:
                logger.warning("reset_transport failed", exc_info=True)
            try:
                self.db.add_system_event(
                    level="info",
                    component="forwarder",
                    message="connectivity_restored",
                    details={"host": _sift_grpc_hostname(), "pending_forward": pending},
                )
            except Exception:
                pass
            self._force_immediate = True

        if online:
            return True

        # Offline: record a compact failure without hanging on gRPC/DNS.
        if pending > 0:
            self.worker.health.record_failure("connectivity_offline:sift_dns")
        return False

    def _maybe_watchdog_exit(self, pending: int, *, connectivity_ok: bool) -> None:
        if not self.worker.health.should_restart(
            pending_forward=pending, connectivity_ok=connectivity_ok
        ):
            return
        snap = self.worker.health.snapshot(pending_forward=pending)
        logger.critical(
            "Forward watchdog: exiting process after %ss of failures with pending=%d "
            "(last_error=%s, connectivity_ok=%s). systemd Restart=always should recycle the service.",
            snap.get("failure_streak_seconds"),
            pending,
            snap.get("last_error"),
            connectivity_ok,
        )
        try:
            self.db.add_system_event(
                level="error",
                component="forwarder",
                message="forward_watchdog_restart",
                details=snap,
            )
        except Exception:
            pass
        # Background thread: os._exit so Flask's main thread cannot ignore SystemExit.
        os._exit(78)

    def _run(self) -> None:
        while not self._stop.wait(self._sleep_seconds()):
            try:
                pending_before = self._pending_count()
                online = self._check_connectivity()
                should_send = self._handle_connectivity(online, pending=pending_before)

                if not should_send:
                    # Stay in backoff; watchdog will not fire while offline.
                    continue

                in_catchup = (
                    pending_before >= self.catchup_threshold
                    and self.worker.health.consecutive_failures == 0
                )
                if in_catchup and not self._in_catchup:
                    logger.info(
                        "Forward catch-up mode: pending=%d (batch up to %d, interval %ds)",
                        pending_before,
                        forward_batch_size_for_pending(pending_before),
                        self.catchup_interval_seconds,
                    )
                self._in_catchup = in_catchup
                self.worker.run_once()
                self._maybe_watchdog_exit(self._pending_count(), connectivity_ok=online)
            except Exception:
                logger.error("BackgroundForwardLoop tick failed", exc_info=True)


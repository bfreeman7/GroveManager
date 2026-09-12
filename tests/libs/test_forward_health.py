from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from libs.forwarder import (
    BackgroundForwardLoop,
    ForwardSyncHealth,
    ForwardWorker,
    _summarize_forward_error,
)


def test_summarize_forward_error_dns():
    err = (
        '<_InactiveRpcError ... details = "errors resolving grpc-api.siftstack.com:443: '
        '[field:hostname lookup error:address lookup failed ... DNS server returned general failure]"> '
    )
    assert _summarize_forward_error(err) == "dns_resolve_failed:grpc-api.siftstack.com"


def test_health_rate_limits_events(monkeypatch):
    monkeypatch.setenv("FORWARD_ERROR_LOG_INTERVAL_SECONDS", "300")
    h = ForwardSyncHealth()
    first = h.record_failure("dns hostname lookup error")
    second = h.record_failure("dns hostname lookup error again")
    assert first["should_log_event"] is True
    assert first["should_mark_rows"] is True
    assert second["should_log_event"] is False
    assert second["should_mark_rows"] is False
    assert h.consecutive_failures == 2


def test_health_degraded_after_stale_streak(monkeypatch):
    monkeypatch.setenv("FORWARD_STALE_SECONDS", "60")
    h = ForwardSyncHealth()
    h.record_failure("dns timeout")
    # Not stale yet
    snap = h.snapshot(pending_forward=10)
    assert snap["degraded"] is False

    h.first_failure_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    snap = h.snapshot(pending_forward=10)
    assert snap["degraded"] is True
    assert snap["reason"] == "forward_failing"
    assert snap["last_error"] == "dns_resolve_failed:grpc-api.siftstack.com"


def test_health_watchdog_restart(monkeypatch):
    monkeypatch.setenv("FORWARD_WATCHDOG_ENABLED", "1")
    monkeypatch.setenv("FORWARD_RESTART_AFTER_SECONDS", "60")
    h = ForwardSyncHealth()
    h.record_failure("unavailable connect failed")
    assert h.should_restart(pending_forward=5) is False
    h.first_failure_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    assert h.should_restart(pending_forward=5) is True
    # Only once
    assert h.should_restart(pending_forward=5) is False


def test_worker_rate_limits_sqlite_error_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("FORWARD_ERROR_LOG_INTERVAL_SECONDS", "300")
    from libs.edge_db import EdgeDB

    db = EdgeDB(str(tmp_path / "edge.db"))
    ts = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    db.insert_irrigation_points(points=[(ts, "irrigation_state.station01", True)])

    class Boom:
        def send(self, **kwargs):
            raise RuntimeError(
                'StatusCode.UNAVAILABLE details = "errors resolving grpc-api.siftstack.com:443: DNS"'
            )

    worker = ForwardWorker(db=db, forwarder=Boom(), asset="test")
    r1 = worker.run_once()
    r2 = worker.run_once()
    assert r1.forwarded == 0 and r2.forwarded == 0

    events = db.recent_system_events(limit=20)
    fails = [e for e in events if e["message"] == "forward_failed"]
    assert len(fails) == 1
    assert fails[0]["details"]["error"] == "dns_resolve_failed:grpc-api.siftstack.com"


def test_backoff_grows(monkeypatch):
    monkeypatch.setenv("FORWARD_BACKOFF_MAX_SECONDS", "300")
    h = ForwardSyncHealth()
    assert h.backoff_seconds(30) == 30
    h.record_failure("x")
    assert h.backoff_seconds(30) == 30
    h.record_failure("x")
    assert h.backoff_seconds(30) == 60
    h.record_failure("x")
    assert h.backoff_seconds(30) == 120


def test_watchdog_exits(monkeypatch, tmp_path):
    monkeypatch.setenv("FORWARD_WATCHDOG_ENABLED", "1")
    monkeypatch.setenv("FORWARD_RESTART_AFTER_SECONDS", "1")
    from libs.edge_db import EdgeDB

    db = EdgeDB(str(tmp_path / "edge.db"))
    worker = ForwardWorker(db=db, forwarder=MagicMock(), asset="test")
    worker.health.record_failure("some_app_error")
    worker.health.first_failure_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    worker.health.connectivity_ok = True
    loop = BackgroundForwardLoop(worker=worker, db=db, interval_seconds=30)

    with pytest.raises(SystemExit) as ei:
        # Patch os._exit to raise so the test can observe it
        import libs.forwarder as fwd

        def _boom(code):
            raise SystemExit(code)

        monkeypatch.setattr(fwd.os, "_exit", _boom)
        loop._maybe_watchdog_exit(pending=3, connectivity_ok=True)
    assert ei.value.code == 78


def test_watchdog_skips_while_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("FORWARD_WATCHDOG_ENABLED", "1")
    monkeypatch.setenv("FORWARD_RESTART_AFTER_SECONDS", "1")
    from libs.edge_db import EdgeDB

    db = EdgeDB(str(tmp_path / "edge.db"))
    worker = ForwardWorker(db=db, forwarder=MagicMock(), asset="test")
    worker.health.record_failure("connectivity_offline:sift_dns")
    worker.health.first_failure_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    worker.health.connectivity_ok = False
    assert worker.health.should_restart(pending_forward=9, connectivity_ok=False) is False


def test_connectivity_restored_resets_backoff_and_transport(tmp_path, monkeypatch):
    from libs.edge_db import EdgeDB

    db = EdgeDB(str(tmp_path / "edge.db"))

    class Flaky(MagicMock):
        def __init__(self):
            super().__init__()
            self.resets = 0

        def reset_transport(self):
            self.resets += 1

    forwarder = Flaky()
    worker = ForwardWorker(db=db, forwarder=forwarder, asset="test")
    loop = BackgroundForwardLoop(worker=worker, db=db, interval_seconds=30)

    worker.health.connectivity_ok = True
    assert loop._handle_connectivity(False, pending=4) is False
    assert worker.health.connectivity_ok is False
    assert worker.health.consecutive_failures >= 1

    assert loop._handle_connectivity(True, pending=4) is True
    assert forwarder.resets == 1
    assert worker.health.consecutive_failures == 0
    assert loop._force_immediate is True
    events = [e["message"] for e in db.recent_system_events(limit=10)]
    assert "connectivity_lost" in events
    assert "connectivity_restored" in events


def test_probe_hostname_parsing(monkeypatch):
    from libs.forwarder import _sift_grpc_hostname

    monkeypatch.setenv("SIFT_GRPC_URL", "https://grpc-api.siftstack.com:443")
    assert _sift_grpc_hostname() == "grpc-api.siftstack.com"
    monkeypatch.setenv("SIFT_GRPC_URL", "grpc-api.siftstack.com:443")
    assert _sift_grpc_hostname() == "grpc-api.siftstack.com"
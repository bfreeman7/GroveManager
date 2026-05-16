from libs.forwarder import (
    ForwardWorker,
    _coalesce_points_by_timestamp,
    forward_batch_size_for_pending,
)


def test_coalesce_points_by_timestamp():
    points = [
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.a", "value": 1.0},
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.b", "value": 2.0},
        {"ts": "2026-05-15T12:01:00+00:00", "channel": "ecowitt.a", "value": 3.0},
    ]
    out = _coalesce_points_by_timestamp(points)
    assert len(out) == 2
    assert out[0]["values"] == {"ecowitt.a": 1.0, "ecowitt.b": 2.0}
    assert out[1]["values"] == {"ecowitt.a": 3.0}


def test_forward_batch_size_for_pending(monkeypatch):
    monkeypatch.setenv("FORWARD_BATCH_SIZE", "500")
    monkeypatch.setenv("FORWARD_CATCHUP_BATCH_SIZE", "12000")
    monkeypatch.setenv("FORWARD_CATCHUP_THRESHOLD", "2000")
    assert forward_batch_size_for_pending(100) == 500
    assert forward_batch_size_for_pending(5000) == 12000


def test_run_once_uses_catchup_batch_size(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from libs.edge_db import EdgeDB
    from libs.forwarder import FakeSiftForwarder, ForwardWorker

    monkeypatch.setenv("FORWARD_BATCH_SIZE", "2")
    monkeypatch.setenv("FORWARD_CATCHUP_BATCH_SIZE", "4")
    monkeypatch.setenv("FORWARD_CATCHUP_THRESHOLD", "3")

    db = EdgeDB(path=str(tmp_path / "edge.db"))
    for i in range(5):
        ts = datetime(2026, 5, 15, 12, 0, i, tzinfo=timezone.utc)
        rid = db.insert_raw_event(source="t", payload={"i": i}, received_at=ts)
        db.insert_measurements(
            raw_event_id=rid,
            ts=ts,
            channel_values=[("ecowitt.x", float(i))],
        )

    sent_batches = []

    class SpyForwarder(FakeSiftForwarder):
        def send(self, *, asset: str, day: str, points):
            sent_batches.append(len(points))
            super().send(asset=asset, day=day, points=points)

    worker = ForwardWorker(
        db=db,
        forwarder=SpyForwarder(out_path=str(tmp_path / "out.jsonl")),
        asset="test-asset",
    )
    res = worker.run_once()
    assert res.forwarded == 4
    assert sent_batches == [4]

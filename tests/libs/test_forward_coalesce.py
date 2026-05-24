import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from libs.edge_db import EdgeDB
from libs.forwarder import (
    FakeSiftForwarder,
    ForwardWorker,
    _coalesce_points_by_timestamp,
    _ensure_sift_py_flow_channels,
    _group_points_by_flow,
    flow_name_from_channels,
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


def test_flow_name_from_channels_is_stable():
    channels = ["irrigation_state.station02", "irrigation_state.station01"]
    assert flow_name_from_channels(channels) == flow_name_from_channels(reversed(channels))
    assert len(flow_name_from_channels(channels)) == 16


def test_group_points_by_flow():
    points = [
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station01", "value": 1.0},
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station02", "value": 0.0},
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.tempf", "value": 70.0},
    ]
    grouped = _group_points_by_flow(points)
    irrigation_flow = flow_name_from_channels(["irrigation_state.station01", "irrigation_state.station02"])
    ecowitt_flow = flow_name_from_channels(["ecowitt.tempf"])
    assert grouped[irrigation_flow] == [points[0], points[1]]
    assert grouped[ecowitt_flow] == [points[2]]


def test_summarize_coalesced_values():
    from libs.forwarder import _summarize_coalesced_values

    ordered = ["irrigation_state.station01", "irrigation_state.station02"]
    row = {"irrigation_state.station01": False, "irrigation_state.station02": True}
    summary = _summarize_coalesced_values(ordered, row)
    assert "[0] irrigation_state.station01=false" in summary
    assert "[1] irrigation_state.station02=true" in summary


def test_summarize_coalesced_values_marks_missing():
    from libs.forwarder import _summarize_coalesced_values

    summary = _summarize_coalesced_values(["a", "b"], {"a": 1.0})
    assert "[1] b=<empty>" in summary


    channels = ["irrigation_state.station01", "irrigation_state.station02"]
    base = flow_name_from_channels(channels)
    recovered = flow_name_from_channels(channels, recovery=1)
    assert base != recovered
    assert flow_name_from_channels(channels, recovery=1) == recovered


def test_resolve_sift_flow_name_uses_recovery_when_partial():
    from libs.forwarder import _resolve_sift_flow_name

    required = ["irrigation_state.station01", "irrigation_state.station02"]
    base = flow_name_from_channels(required)
    recovered = flow_name_from_channels(required, recovery=1)

    with patch(
        "libs.forwarder._registered_flow_channels",
        side_effect=[
            {"irrigation_state.station01"},
            set(),
        ],
    ):
        resolved = _resolve_sift_flow_name(MagicMock(), "cfg-id", required)
        assert resolved == recovered
        assert resolved != base


def test_ensure_sift_py_flow_channels_logs_when_still_partial():
    import grpc

    def fake_create(*args, **kwargs):
        err = grpc.RpcError()
        err.code = lambda: grpc.StatusCode.ALREADY_EXISTS
        raise err

    with patch(
        "sift_py.ingestion._internal.ingestion_config.create_flow_configs",
        side_effect=fake_create,
    ), patch(
        "libs.forwarder._registered_flow_channels",
        side_effect=[
            {"irrigation_state.station01"},
            {"irrigation_state.station01"},
        ],
    ), patch("libs.forwarder.logger") as mock_logger:
        _ensure_sift_py_flow_channels(
            MagicMock(),
            "cfg-id",
            "irrigation",
            ["irrigation_state.station01", "irrigation_state.station02"],
        )
        mock_logger.error.assert_called_once()


def test_coalesce_irrigation_channels_as_bool():
    points = [
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "irrigation_state.station01", "value": 1.0},
        {"ts": "2026-05-15T12:00:00+00:00", "channel": "ecowitt.tempf", "value": 70.0},
        {"ts": "2026-05-15T12:01:00+00:00", "channel": "irrigation_state.station01", "value": 0.0},
    ]
    out = _coalesce_points_by_timestamp(points)
    assert out[0]["values"] == {"irrigation_state.station01": True, "ecowitt.tempf": 70.0}
    assert out[1]["values"] == {"irrigation_state.station01": False}


def test_fake_forwarder_irrigation_bool(tmp_path):
    out_path = tmp_path / "fake_sift.jsonl"
    db = EdgeDB(path=str(tmp_path / "edge.db"))
    ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    db.insert_irrigation_points(points=[(ts, "irrigation_state.station01", True)])

    worker = ForwardWorker(
        db=db,
        forwarder=FakeSiftForwarder(out_path=str(out_path)),
        asset="test-asset",
    )
    res = worker.run_once()
    assert res.forwarded == 1

    rec = json.loads(out_path.read_text().strip().splitlines()[-1])
    assert rec["points"][0]["channel"] == "irrigation_state.station01"
    assert rec["points"][0]["value"] is True


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

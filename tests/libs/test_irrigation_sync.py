import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

from libs.edge_db import EdgeDB
from libs.irrigation_sync import IrrigationSyncer, station_channel


def _ja_payload(*, sn=None, ps=None, devt=1_700_000_000):
    return {
        "settings": {"devt": devt, "ps": ps or []},
        "options": {"lg": 1},
        "stations": {"snames": ["Front", "Back"]},
        "status": {"sn": sn if sn is not None else [0, 0]},
        "programs": {"pd": []},
    }


def test_station_channel_naming():
    assert station_channel(0) == "irrigation_state.station01"
    assert station_channel(1) == "irrigation_state.station02"
    assert station_channel(9) == "irrigation_state.station10"


def test_snapshot_emits_all_stations_each_poll(tmp_path):
    db = EdgeDB(str(tmp_path / "edge.db"))
    client = MagicMock()
    client.get_json_all.return_value = _ja_payload(sn=[1, 0], ps=[[99, 120, 1_700_000_100]])

    syncer = IrrigationSyncer(client=client, db=db)
    count = syncer.sync_snapshot()

    assert count == 2
    pending = db.get_pending_measurements(limit=10)
    assert len(pending) == 2
    by_channel = {p.channel: p for p in pending}
    assert by_channel["irrigation_state.station01"].value == 1.0
    assert by_channel["irrigation_state.station02"].value == 0.0
    assert by_channel["irrigation_state.station01"].ts == by_channel["irrigation_state.station02"].ts

    states = db.get_irrigation_station_states()
    assert states[0] is True
    assert states[1] is False


def test_snapshot_polls_state_every_tick(tmp_path):
    db = EdgeDB(str(tmp_path / "edge.db"))
    client = MagicMock()

    syncer = IrrigationSyncer(client=client, db=db)

    client.get_json_all.return_value = _ja_payload(sn=[0, 0])
    assert syncer.sync_snapshot() == 2

    client.get_json_all.return_value = _ja_payload(sn=[1, 0], ps=[[99, 300, 1_700_000_200]])
    assert syncer.sync_snapshot() == 2
    pending = db.get_pending_measurements(limit=10)
    latest = sorted(pending, key=lambda p: p.id)[-2:]
    by_channel = {p.channel: p for p in latest}
    assert by_channel["irrigation_state.station01"].value == 1.0
    assert by_channel["irrigation_state.station02"].value == 0.0

    client.get_json_all.return_value = _ja_payload(sn=[0, 0], devt=1_700_000_500)
    assert syncer.sync_snapshot() == 2
    pending = db.get_pending_measurements(limit=10)
    latest = sorted(pending, key=lambda p: p.id)[-2:]
    by_channel = {p.channel: p for p in latest}
    assert by_channel["irrigation_state.station01"].value == 0.0
    assert by_channel["irrigation_state.station02"].value == 0.0


def test_history_backfill_dedupes_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRRIGATION_HISTORY_LOOKBACK_MINUTES", "60")
    db = EdgeDB(str(tmp_path / "edge.db"))
    client = MagicMock()

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    duration = 120
    end_epoch = now_epoch - 30
    start_epoch = end_epoch - duration

    client.get_json_all.return_value = _ja_payload()
    client.get_run_log.return_value = [[99, 0, duration, end_epoch]]

    syncer = IrrigationSyncer(client=client, db=db)
    first = syncer.sync_history(lookback_minutes=60)
    second = syncer.sync_history(lookback_minutes=60)

    assert first == 2
    assert second == 0
    assert db.is_run_synced(0, end_epoch)

    pending = db.get_pending_measurements(limit=10)
    channels = {p.channel for p in pending}
    assert channels == {"irrigation_state.station01"}
    values = sorted(p.value for p in pending)
    assert values == [0.0, 1.0]
    start_ts = min(p.ts for p in pending if p.value == 1.0)
    end_ts = max(p.ts for p in pending if p.value == 0.0)
    assert start_ts == datetime.fromtimestamp(start_epoch, tz=timezone.utc).isoformat()
    assert end_ts == datetime.fromtimestamp(end_epoch, tz=timezone.utc).isoformat()


def test_history_startup_lookback_covers_older_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRRIGATION_HISTORY_LOOKBACK_MINUTES", "5")
    db = EdgeDB(str(tmp_path / "edge.db"))
    client = MagicMock()

    end_epoch = int(datetime.now(timezone.utc).timestamp()) - (6 * 3600)
    duration = 300

    client.get_json_all.return_value = _ja_payload()
    client.get_run_log.return_value = [[99, 0, duration, end_epoch]]

    syncer = IrrigationSyncer(client=client, db=db)
    assert syncer.sync_history(lookback_minutes=5) == 0
    assert syncer.sync_history(lookback_minutes=24 * 60) == 2


def test_snapshot_logs_idle_poll(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="libs.irrigation_sync")
    db = EdgeDB(str(tmp_path / "edge.db"))
    client = MagicMock()
    client.get_json_all.return_value = _ja_payload(sn=[0, 0])

    syncer = IrrigationSyncer(client=client, db=db)
    assert syncer.sync_snapshot() == 2
    assert "Irrigation snapshot sync queued 2 point(s) (0 on)" in caplog.text


def test_manual_station_triggers_immediate_sync(opensprinkler_env, monkeypatch):
    monkeypatch.setenv("IRRIGATION_SYNC_ENABLED", "1")

    from conftest import import_server_module

    ja_payload = _ja_payload(sn=[1, 0], ps=[[99, 120, 1_700_000_100]])

    server = import_server_module()
    client = server.app.test_client()
    os_client = server.app.extensions["orchardmonitor"]["opensprinkler_client"]

    os_client.get_json_all = MagicMock(return_value=ja_payload)
    os_client.manual_station = MagicMock(return_value={"result": 1})

    resp = client.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 1, "t": 300})
    assert resp.status_code == 200

    os_client.get_json_all.assert_called()
    os_client.manual_station.assert_called_once()

    conn = sqlite3.connect(opensprinkler_env["edge_db"])
    rows = conn.execute(
        "SELECT channel, value FROM measurements WHERE channel LIKE 'irrigation_state.%'"
    ).fetchall()
    conn.close()
    assert ("irrigation_state.station01", 1.0) in rows
    assert ("irrigation_state.station02", 0.0) in rows

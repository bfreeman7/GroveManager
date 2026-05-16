from unittest.mock import patch

from conftest import import_server_module


def test_station_manual_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.delenv("OPENSPRINKLER_URL", raising=False)
    monkeypatch.delenv("OPENSPRINKLER_PASSWORD", raising=False)
    monkeypatch.delenv("OPENSPRINKLER_PW_MD5", raising=False)

    server = import_server_module()
    c = server.app.test_client()
    resp = c.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 1, "t": 60})
    assert resp.status_code == 503


def test_station_manual_run_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    server = import_server_module()
    c = server.app.test_client()

    with patch(
        "libs.opensprinkler_client.OpenSprinklerClient.manual_station",
        return_value={"result": 1, "pid": 99},
    ) as mock_cm:
        r1 = c.post("/integrations/opensprinkler/station", json={"sid": 2, "en": 1, "t": 120})
    assert r1.status_code == 200
    assert r1.get_json()["result"] == 1
    mock_cm.assert_called_once_with(sid=2, en=1, t=120, qo=None, ssta=None)

    with patch(
        "libs.opensprinkler_client.OpenSprinklerClient.manual_station",
        return_value={"result": 1},
    ) as mock_cm:
        r2 = c.post("/integrations/opensprinkler/station", json={"sid": 2, "en": 0})
    assert r2.status_code == 200
    mock_cm.assert_called_once_with(sid=2, en=0, t=None, qo=None, ssta=None)


def test_station_manual_default_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    server = import_server_module()
    c = server.app.test_client()

    with patch(
        "libs.opensprinkler_client.OpenSprinklerClient.manual_station",
        return_value={"result": 1},
    ) as mock_cm:
        r = c.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 1})
    assert r.status_code == 200
    mock_cm.assert_called_once_with(sid=0, en=1, t=300, qo=None, ssta=None)


def test_station_manual_os_declines(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    server = import_server_module()
    c = server.app.test_client()

    with patch(
        "libs.opensprinkler_client.OpenSprinklerClient.manual_station",
        return_value={"result": 48},
    ):
        r = c.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 1, "t": 60})
    assert r.status_code == 400
    assert "48" in r.get_json().get("error", "")


def test_station_manual_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    server = import_server_module()
    c = server.app.test_client()

    assert c.post("/integrations/opensprinkler/station", json={"sid": -1, "en": 1}).status_code == 400
    assert c.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 2}).status_code == 400
    assert c.post("/integrations/opensprinkler/station", json={"sid": 0, "en": 1, "t": 0}).status_code == 400

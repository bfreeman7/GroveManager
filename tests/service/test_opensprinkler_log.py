from unittest.mock import patch

from conftest import import_server_module


def test_opensprinkler_log_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    ja = {
        "settings": {"en": 1},
        "options": {"lg": 1},
        "stations": {"snames": ["Front", "Back"]},
        "status": {"sn": [0, 0]},
        "programs": {"pd": [[3, 127, 0, [480, 0, 0, 0], [0, 0, 0, 0], "Summer", [0, 33, 415]]]},
    }
    log_records = [
        [1, 0, 2700, 1700000000],
        [0, "rd", 86400, 1700000100],
    ]

    server = import_server_module()
    client = server.app.test_client()

    with (
        patch(
            "libs.opensprinkler_client.OpenSprinklerClient.get_json_all",
            return_value=ja,
        ),
        patch(
            "libs.opensprinkler_client.OpenSprinklerClient.get_run_log",
            return_value=log_records,
        ),
    ):
        resp = client.get("/integrations/opensprinkler/log?hist=3")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["hist_days"] == 3
    assert len(body["runs"]) == 2
    assert body["runs"][0]["kind"] == "event"
    assert body["runs"][0]["label"] == "Rain delay"
    assert body["runs"][1]["kind"] == "run"
    assert body["runs"][1]["station_name"] == "Front"
    assert body["runs"][1]["program_name"] == "Summer"
    assert body["runs"][1]["duration_seconds"] == 2700


def test_opensprinkler_logging_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    server = import_server_module()
    client = server.app.test_client()

    with patch(
        "libs.opensprinkler_client.OpenSprinklerClient.set_logging_enabled",
        return_value={"result": 1},
    ) as mock_co:
        resp = client.post("/integrations/opensprinkler/logging", json={"lg": 1})

    assert resp.status_code == 200
    assert resp.get_json()["lg"] == 1
    mock_co.assert_called_once_with(1)

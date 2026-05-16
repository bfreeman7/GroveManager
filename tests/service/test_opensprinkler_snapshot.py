from unittest.mock import MagicMock, patch

from conftest import import_server_module


def test_opensprinkler_snapshot_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.delenv("OPENSPRINKLER_URL", raising=False)
    monkeypatch.delenv("OPENSPRINKLER_PASSWORD", raising=False)

    server = import_server_module()
    client = server.app.test_client()
    resp = client.get("/integrations/opensprinkler/snapshot")
    assert resp.status_code == 200
    assert resp.get_json() == {"configured": False}


def test_opensprinkler_snapshot_with_pw_md5(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.delenv("OPENSPRINKLER_PASSWORD", raising=False)
    monkeypatch.setenv("OPENSPRINKLER_PW_MD5", "a6d82bced638de3def1e9bbb4983225c")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"settings": {}, "stations": {}, "status": {}, "programs": {}}

    server = import_server_module()
    flask_client = server.app.test_client()

    with patch("libs.opensprinkler_client.requests.get", return_value=mock_resp) as mock_get:
        resp = flask_client.get("/integrations/opensprinkler/snapshot")

    assert resp.status_code == 200
    assert resp.get_json()["configured"] is True
    call_params = mock_get.call_args.kwargs.get("params") or mock_get.call_args[1].get("params")
    assert call_params["pw"] == "a6d82bced638de3def1e9bbb4983225c"


def test_opensprinkler_snapshot_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    ja_payload = {
        "settings": {"en": 1, "rd": 0, "devt": 12345, "lrun": [1, 2, 3, 4], "ps": []},
        "stations": {"snames": ["Front", "Back"]},
        "status": {"sn": [1, 0], "nstations": 2},
        "programs": {
            "pd": [
                [3, 127, 0, [480, 0, 0, 0], [0, 2700, 0, 2700, 0, 0, 0, 0], "Summer", [0, 33, 415]],
                [2, 9, 0, [120, 0, 300, 0], [0, 3720, 0, 0, 0, 0, 0, 0], "Fall", [0, 33, 415]],
            ]
        },
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = ja_payload

    server = import_server_module()
    flask_client = server.app.test_client()

    with patch("libs.opensprinkler_client.requests.get", return_value=mock_resp):
        resp = flask_client.get("/integrations/opensprinkler/snapshot")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["configured"] is True
    assert "fetched_at" in body
    assert body["raw"] == ja_payload

    summary = body["summary"]
    assert summary["controller"]["en"] == 1
    assert summary["controller"]["rd"] == 0
    assert summary["controller"]["devt"] == 12345

    assert summary["stations"] == [
        {"id": 0, "name": "Front", "on": True},
        {"id": 1, "name": "Back", "on": False},
    ]

    assert summary["programs"] == [
        {
            "id": 0,
            "name": "Summer",
            "enabled": True,
            "use_weather": True,
            "schedule": "Every day · 8:00 AM",
            "watering": "Back 45m · Station 4 45m · 90m total",
            "total_watering_seconds": 5400,
        },
        {
            "id": 1,
            "name": "Fall",
            "enabled": False,
            "use_weather": True,
            "schedule": "Mon, Thu · 2:00 AM",
            "watering": "Back 62m · 62m total",
            "total_watering_seconds": 3720,
        },
    ]

    mock_resp.raise_for_status.assert_called_once()


def test_opensprinkler_snapshot_ja_404_falls_back_to_split_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PW_MD5", "a6d82bced638de3def1e9bbb4983225c")

    import requests

    def fake_get(url, params=None, timeout=None):
        path = url.rstrip("/").split("/")[-1]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path == "ja":
            err = requests.HTTPError("404")
            err.response = MagicMock(status_code=404)
            raise err
        payloads = {
            "jc": {"en": 1, "rd": 0, "devt": 99},
            "jo": {},
            "jn": {"snames": ["Front"]},
            "js": {"sn": [1], "nstations": 1},
            "jp": {"pd": []},
        }
        resp.json.return_value = payloads[path]
        return resp

    server = import_server_module()
    flask_client = server.app.test_client()

    with patch("libs.opensprinkler_client.requests.get", side_effect=fake_get):
        resp = flask_client.get("/integrations/opensprinkler/snapshot")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["stations"] == [{"id": 0, "name": "Front", "on": True}]


def test_opensprinkler_snapshot_request_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")

    import requests

    server = import_server_module()
    flask_client = server.app.test_client()

    with patch(
        "libs.opensprinkler_client.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        resp = flask_client.get("/integrations/opensprinkler/snapshot")

    assert resp.status_code == 502
    assert "error" in resp.get_json()

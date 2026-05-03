import json

from conftest import import_server_module


def test_fake_forwarder_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    out_path = tmp_path / "fake_sift.jsonl"
    monkeypatch.setenv("FAKE_SIFT_OUT", str(out_path))

    server = import_server_module()
    client = server.app.test_client()

    payload = {"soilmoisture1": "10", "tempf": "70.0"}
    r = client.post("/ecowitt", data=payload)
    assert r.status_code == 200

    fr = client.post("/admin/forward/run-once")
    assert fr.status_code == 200
    js = fr.get_json()
    assert js["attempted"] >= 1
    assert js["forwarded"] >= 1

    assert out_path.exists()
    lines = out_path.read_text().strip().splitlines()
    assert len(lines) >= 1
    rec = json.loads(lines[-1])
    assert "points" in rec and len(rec["points"]) >= 1
    assert rec["points"][0]["channel"].startswith("ecowitt.")


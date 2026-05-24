import json
from datetime import datetime, timezone

from conftest import import_server_module


def test_fake_forwarder_writes_jsonl(fake_sift_env):
    out_path = fake_sift_env["fake_sift_out"]

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


def test_fake_forwarder_irrigation_end_to_end(fake_sift_env):
    out_path = fake_sift_env["fake_sift_out"]
    db_path = fake_sift_env["edge_db"]

    from libs.edge_db import EdgeDB

    db = EdgeDB(str(db_path))
    ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    db.insert_irrigation_points(points=[(ts, "irrigation_state.station01", True), (ts, "irrigation_state.station02", False)])

    server = import_server_module()
    client = server.app.test_client()
    fr = client.post("/admin/forward/run-once")
    assert fr.status_code == 200
    assert fr.get_json()["forwarded"] >= 2

    rec = json.loads(out_path.read_text().strip().splitlines()[-1])
    values_by_channel = {p["channel"]: p["value"] for p in rec["points"]}
    assert values_by_channel["irrigation_state.station01"] is True
    assert values_by_channel["irrigation_state.station02"] is False


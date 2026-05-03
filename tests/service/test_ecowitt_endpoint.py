from datetime import datetime, timezone

import pandas as pd

from conftest import import_server_module


def test_ecowitt_post_writes_parquet(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    monkeypatch.setenv("FAKE_SIFT_OUT", str(tmp_path / "fake_sift.jsonl"))
    server = import_server_module()

    client = server.app.test_client()

    payload = {
        "dateutc": "2026-04-25 12:34:56",
        "soilmoisture1": "41",
        "tempf": "70.1",
        "PASSKEY": "secret_should_be_ignored",
    }

    resp = client.post("/ecowitt", data=payload)
    assert resp.status_code == 200

    parquet_path = tmp_path / "measurements" / "2026-04-25.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 1
    assert float(df.loc[0, "soilmoisture1"]) == 41.0
    assert float(df.loc[0, "tempf"]) == 70.1
    assert "PASSKEY" not in df.columns

    ts = df.loc[0, "timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    assert ts.replace(tzinfo=timezone.utc).isoformat().startswith("2026-04-25T12:34:56")

    st = client.get("/status")
    assert st.status_code == 200
    js = st.get_json()
    assert js["pending_forward"] >= 1


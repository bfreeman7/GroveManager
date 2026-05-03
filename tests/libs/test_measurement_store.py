from datetime import datetime, timezone

import pandas as pd

from libs.measurement_store import MeasurementStore


def test_measurement_store_writes_daily_parquet(tmp_path):
    store = MeasurementStore(base_path=str(tmp_path))

    ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    store.store_reading({"soilmoisture1": "23.0", "tempf": "71.2"}, ts)

    parquet_path = tmp_path / "measurements" / "2026-04-25.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 1
    assert "timestamp" in df.columns
    assert float(df.loc[0, "soilmoisture1"]) == 23.0
    assert float(df.loc[0, "tempf"]) == 71.2


def test_measurement_store_merges_new_columns(tmp_path):
    store = MeasurementStore(base_path=str(tmp_path))
    ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)

    store.store_reading({"a": "1"}, ts)
    store.store_reading({"b": "2"}, ts)

    parquet_path = tmp_path / "measurements" / "2026-04-25.parquet"
    df = pd.read_parquet(parquet_path)
    assert set(["timestamp", "a", "b"]).issubset(set(df.columns))
    assert len(df) == 2


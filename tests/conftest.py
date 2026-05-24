import inspect
import os
import sys

import pytest


def pytest_configure():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(project_root, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def close_coroutine(coro):
    """Test double for _run_coroutine_sync: close coroutine to avoid gc warnings."""
    if inspect.iscoroutine(coro):
        coro.close()
    return None


def import_server_module():
    """
    Import `src/server.py` as a module.

    `src/server.py` remains the authoritative runtime entrypoint (systemd runs it),
    so tests that exercise HTTP routes should import it directly.
    """
    if "server" in sys.modules:
        del sys.modules["server"]
    import server  # type: ignore

    return server


@pytest.fixture
def fake_sift_env(tmp_path, monkeypatch):
    """Minimal env for store-and-forward tests using FakeSiftForwarder."""
    monkeypatch.setenv("DATA_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("EDGE_DB_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("SIFT_MODE", "fake")
    out_path = tmp_path / "fake_sift.jsonl"
    monkeypatch.setenv("FAKE_SIFT_OUT", str(out_path))
    return {"tmp_path": tmp_path, "edge_db": tmp_path / "edge.db", "fake_sift_out": out_path}


@pytest.fixture
def opensprinkler_env(fake_sift_env, monkeypatch):
    """fake_sift_env plus Open Sprinkler credentials (client still mocked in tests)."""
    monkeypatch.setenv("OPENSPRINKLER_URL", "http://os.test")
    monkeypatch.setenv("OPENSPRINKLER_PASSWORD", "secret")
    return fake_sift_env

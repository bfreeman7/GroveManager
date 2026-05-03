import os
import sys


def pytest_configure():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(project_root, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


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


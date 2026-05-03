from __future__ import annotations

import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


class SpaHandler(SimpleHTTPRequestHandler):
    """
    Static file server with SPA fallback.

    - Serves files from `directory`
    - If a path doesn't exist, falls back to `index.html` (for client-side routing)
    """

    def __init__(self, *args, directory: str, **kwargs):
        self._root = Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        req_path = Path(unquote(parsed.path.lstrip("/")))
        fs_path = (self._root / req_path).resolve()

        # If requested path is outside root, refuse.
        if self._root not in fs_path.parents and fs_path != self._root:
            self.send_error(403)
            return

        # If it exists (file or dir), serve normally.
        if fs_path.exists():
            return super().do_GET()

        # SPA fallback.
        self.path = "/index.html"
        return super().do_GET()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="src/ui/dist", help="Directory containing built UI assets (Vite dist/).")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5173)
    args = p.parse_args()

    root = os.path.abspath(args.dir)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        lambda *a, **kw: SpaHandler(*a, directory=root, **kw),
    )
    print(f"UI server listening on http://{args.host}:{args.port} (dir={root})")
    server.serve_forever()


if __name__ == "__main__":
    main()


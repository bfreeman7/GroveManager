"""
Backwards-compatible entrypoint for the edge service.

systemd runs `python src/server.py`. Tests import `server.app`.

The actual service implementation now lives under `src/service/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from service.app import create_app  # noqa: E402

app = create_app()


def main() -> None:
    from service.main import main as _main  # noqa: E402

    _main()


if __name__ == "__main__":
    main()

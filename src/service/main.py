from __future__ import annotations

from service.app import create_app, start_background


def main() -> None:
    app = create_app()
    start_background(app)
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()


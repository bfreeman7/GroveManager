# GroveManager (edge node)

A Raspberry Pi–friendly edge service that **ingests Ecowitt telemetry**, **stores locally first** (Parquet + SQLite), and **forwards to Sift** (or a local fake sink). A small **Vite + React** operator UI is optional. Day-to-day work is: **test locally, hit `/health` and `/status`, deploy from your laptop** over `ssh` + `rsync` (no Git on the device).

- **Runbook (copy/paste commands):** [`docs/runbooks.md`](docs/runbooks.md)
- **Layout / data flow:** [`docs/architecture.md`](docs/architecture.md)

## Quick start

1. **Test:** `make test`
2. **Run the API (foreground):** `make run-local` (data under `./.local-data`, listens on **8080**)
3. **In another shell — status + forward:**

```bash
curl -sS http://127.0.0.1:8080/health  | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status  | python3 -m json.tool
curl -sS -X POST http://127.0.0.1:8080/admin/forward/run-once | python3 -m json.tool
```

4. **Optional:** with the server up, `make send-ecowitt` posts a sample Ecowitt payload.

**Operator UI (optional, local):** needs Node. From `src/ui/`: `npm install`, then `VITE_EDGE_API_BASE=http://127.0.0.1:8080 npm run dev` and open the URL Vite prints (port **5173** by default). The API and UI are different origins; for dev, you can set `CORS_ALLOW_ORIGINS=http://127.0.0.1:5173` in your environment for `make run-local` (see the runbook).

**Deploy to the Pi:** from the repo root on your laptop, with a gitignored `env/<name>/orchardmonitor.env` and **Node available** for the UI build (unless you skip it):

```bash
ENV_NAME=<your-env> ./scripts/deploy_remote.sh <user>@<host> <remote_repo_path>
# First boot on a fresh Pi (apt packages):  BOOTSTRAP=1
# No Node on laptop (use a prebuilt src/ui/dist):  SKIP_UI_BUILD=1
```

`scripts/deploy_remote.sh` rsyncs code, installs/updates the Python venv, **builds the UI** when `npm` exists (sets `VITE_EDGE_API_BASE` to `http://<host>:8080` unless you set `UI_EDGE_API_BASE`), pushes the built `dist/`, and restarts **`orchardmonitor.service`** and **`orchardmonitor-ui.service`** (UI on **5173**). Add **`CORS_ALLOW_ORIGINS`** in your env file so the browser can call the API from the UI origin; see the runbook.

## Apps

- **Edge service:** `src/server.py` (Flask: ingest, `/health`, `/status`, forward controls).
- **UI:** `src/ui/` (Vite + React); production assets served by `src/ui_server.py` on the Pi.
- **Deploy:** `scripts/deploy_remote.sh` (laptop → Pi via `rsync` + `ssh`).

## Configuration (short)

- **Storage:** `DATA_STORAGE_PATH`, `EDGE_DB_PATH` (see runbook and `env/_example/orchardmonitor.env`).
- **Ecowitt:** point the gateway to `http://<pi>:8080/ecowitt` (e.g. Tailscale IP).
- **Forwarding:** `SIFT_MODE=fake` or `sdk` plus Sift variables when using the SDK.
- **UI in production:** set **`CORS_ALLOW_ORIGINS`** in `/etc/orchardmonitor.env` to your UI origin (e.g. `http://<pi>:5173` or `*` on a private tailnet). The deploy script bakes **`VITE_EDGE_API_BASE`** into the UI at build time; override with **`UI_EDGE_API_BASE`** on the deploy command if needed.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ecowitt` | Ecowitt form-encoded telemetry ingest |
| GET | `/health` | Liveness + forward queue depth |
| GET | `/status` | Config + counts + recent events |
| POST | `/admin/forward/run-once` | Trigger one forward batch |
| POST | `/schedule/update` | (Optional) Open Sprinkler schedule update |

## More detail

- [`docs/runbooks.md`](docs/runbooks.md) — local run, status checks, Pi `systemd`, deploy flags, CORS, troubleshooting.
- [`docs/migration.md`](docs/migration.md) — moving an existing deployment to this layout.

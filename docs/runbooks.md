# Runbooks

Copy/paste reference for **local test/run**, **checking status**, and **deploy**. Prefer Tailscale (or a known LAN IP) for remote URLs.

## Quick reference

### Local: test and run


| Step                                             | Command                                        |
| ------------------------------------------------ | ---------------------------------------------- |
| Create venv + install deps (implicit in targets) | `make install` (optional; `make test` does it) |
| Run tests                                        | `make test`                                    |
| Run the edge API (foreground)                    | `make run-local`                               |
| Send a sample `POST /ecowitt`                    | `make send-ecowitt`                            |
| Show latest local readings                       | `make print-latest`                            |


`make run-local` uses `DATA_STORAGE_PATH=./.local-data` and listens on **0.0.0.0:8080** (Flask dev server).

### Check status (local, API running)

```bash
curl -sS http://127.0.0.1:8080/health  | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status  | python3 -m json.tool
curl -sS -X POST http://127.0.0.1:8080/admin/forward/run-once | python3 -m json.tool
# Large backlog: one big gRPC stream per batch (optional batch_size query param)
curl -sS -X POST "http://127.0.0.1:8080/admin/forward/catchup?max_seconds=0" | python3 -m json.tool
```



### Operator UI (optional, local dev)

The UI is a separate origin from the API; set `CORS_ALLOW_ORIGINS` when running the API (e.g. in the same shell before `make run-local`, or export in your profile):

```bash
export CORS_ALLOW_ORIGINS=http://127.0.0.1:5173
make run-local
```

In another terminal:

```bash
cd src/ui
npm install
VITE_EDGE_API_BASE=http://127.0.0.1:8080 npm run dev
```

Open the URL Vite prints (default **[http://127.0.0.1:5173](http://127.0.0.1:5173)**).

### Deploy your changes (laptop → Pi)

Day-to-day: **edit on the laptop → test → run** `deploy_remote.sh`. The Pi does not need Git. The script rsyncs code, refreshes the venv, builds the UI (when Node is available), installs systemd units, and restarts services.

**Prereqs on the laptop:** `ssh`, `rsync`, and `npm` **+** `node` **if you want the script to build the UI** (or prebuild `src/ui/dist` and use `SKIP_UI_BUILD=1`).

#### One-time setup (skip if already done)

1. SSH access (Tailscale + keys) — see [SSH and remote access](#ssh-and-remote-access).
2. Env overlay (gitignored). Copy the example and fill host-specific values:

```bash
mkdir -p env/orchard-pi
cp env/_example/orchardmonitor.env env/orchard-pi/orchardmonitor.env
$EDITOR env/orchard-pi/orchardmonitor.env
```

For a split **UI (5173)** + **API (8080)** deploy, set `CORS_ALLOW_ORIGINS` (e.g. `http://<pi-or-tailscale-ip>:5173` or `*` on a private tailnet).

1. **First boot on a fresh Pi only** (installs minimal apt packages once):

```bash
BOOTSTRAP=1 ENV_NAME=orchard-pi ./scripts/deploy_remote.sh bfree@<pi-ip> /home/bfree/Repos/GroveManager
```



#### Normal deploy (after code or env changes)

From the **repo root** on your laptop:

```bash
make test   # optional but recommended before shipping
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh bfree@<pi-ip> /home/bfree/Repos/GroveManager
```

With an SSH `Host` alias (e.g. `orchard-pi` in `~/.ssh/config`):

```bash
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh orchard-pi /home/bfree/Repos/GroveManager
```

**What that does:**


| Step     | Behavior                                                                                              |
| -------- | ----------------------------------------------------------------------------------------------------- |
| Env      | With `ENV_NAME=…`, copies `env/<name>/orchardmonitor.env` → `/etc/orchardmonitor.env` on every deploy |
| Code     | `rsync` of the repo (excludes `venv`, `data`, `.local-data`, `node_modules`, etc.)                    |
| Python   | Creates/updates `venv` and `pip install -r requirements.txt` on the Pi                                |
| UI       | Builds `src/ui` on the laptop, bakes `VITE_EDGE_API_BASE`, pushes `dist/` to the Pi                   |
| Services | Rewrites and restarts `orchardmonitor` (API **8080**) and `orchardmonitor-ui` (UI **5173**)           |


**Useful flags:**


| Flag                             | When                                                   |
| -------------------------------- | ------------------------------------------------------ |
| `BOOTSTRAP=1`                    | Fresh Pi / missing apt packages                        |
| `SKIP_UI_BUILD=1`                | No Node on laptop; you must already have `src/ui/dist` |
| `UI_EDGE_API_BASE=http://…:8080` | Override the API URL baked into the UI                 |
| `EDGE_HTTP_PORT=8080`            | Change API port used for the default UI bake           |


Do **not** install from the tracked `orchardmonitor.service` file in the repo root — it may still show an old path. Live units are generated by `deploy_remote.sh` for `${REMOTE_DIR}` (e.g. `/home/bfree/Repos/GroveManager`).

#### Verify after deploy

On the Pi (SSH in):

```bash
sudo systemctl status orchardmonitor orchardmonitor-ui --no-pager -l
curl -sS http://127.0.0.1:8080/health  | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status  | python3 -m json.tool
curl -sS -I http://127.0.0.1:5173/ | head -n 5
```

From your laptop: open `http://<pi-ip>:5173`. The UI calls the API at the URL baked in at build time. If the browser shows JSON parse errors mentioning `<!doctype`, fix `VITE_EDGE_API_BASE` (redeploy with `UI_EDGE_API_BASE=…`) and `CORS_ALLOW_ORIGINS` (env overlay, then redeploy or restart `orchardmonitor`).

---



## Local dev (more detail)



### Run tests

```bash
make test
```



### Run the edge service locally

```bash
make run-local
```



### Send synthetic Ecowitt payloads

```bash
make send-ecowitt
make print-latest
```



### Use fake (offline) forwarding

Default in examples is fake mode. It writes JSONL to `${DATA_STORAGE_PATH}/fake_sift.jsonl`.

```bash
export SIFT_MODE=fake
make run-local
```



## Pi runtime (systemd)

In normal operation you do **not** need to hand-install OS packages on the Pi if you used `BOOTSTRAP=1` once with `deploy_remote.sh`.

### Optional: manual bootstrap (if not using `BOOTSTRAP=1`)

On apt-based distros (Raspberry Pi OS / Debian / Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv rsync curl ca-certificates
```

If you are not on apt, install equivalents (Python with `venv`, `rsync`, `curl`).

### Environment file

**Recommended:** keep the full config in `env/<name>/orchardmonitor.env` (gitignored) and deploy with `ENV_NAME=<name>`. The service loads:

- `EnvironmentFile=/etc/orchardmonitor.env`

Installed/updated by `scripts/deploy_remote.sh` when you use `ENV_NAME=...`. Start from `env/_example/orchardmonitor.env` (CORS, Sift, forwarder knobs). Irrigation sync lookbacks and intervals are also documented (commented) in root `orchardmonitor.env.example`.

### View logs

```bash
sudo journalctl -u orchardmonitor -f
sudo journalctl -u orchardmonitor-ui -f
```

Look for irrigation sync lines after restart:

- `Irrigation sync background task started (snapshot=…, history=…)`
- `Irrigation snapshot sync queued N point(s) (M on)` — periodic state poll (all stations each tick)
- `Irrigation history sync queued N point(s) from M run(s)` — backfilled recent runs from Open Sprinkler `/jl`
- `Forwarded … measurements` — includes irrigation rows once queued

In Sift, look for hashed flow names on the asset named by `SIFT_ASSET` / `SIFT_ASSET_NAME` in your env (example default in `env/_example` is `orchard-main`; production overlays may use another name such as `orchard_weather_station`). Irrigation uses client key `orchard-edge-v1.irrigation-state` and channels `irrigation_state.station01`**–**`station08` (flow hash e.g. `ba6462925d628aee` for all 8). Ecowitt often uses `orchard-edge-v1.ch13`. Ignore legacy `irrigation.station`* channels and old flow hashes from earlier configs.

If forward fails with `StatusCode.ALREADY_EXISTS`, set a stable ingestion client key matching the ecowitt config already on the Pi:

```bash
# In env/<name>/orchardmonitor.env (then redeploy) — must match the client_key Sift already has for ecowitt
SIFT_INGESTION_CLIENT_KEY=orchard-edge-v1.ch13
```

Then redeploy/restart and retry `POST /admin/forward/run-once`.

### Irrigation → Sift diagnostics (Pi)

Paths below assume the usual orchard-pi layout (`DATA_STORAGE_PATH=/home/bfree/Repos/GroveManager/data`). Adjust if your env uses a different storage path.

```bash
# Queue depth (should drop after forward runs)
curl -sS http://127.0.0.1:8080/status | python3 -m json.tool

# Pending irrigation rows in SQLite
sqlite3 /home/bfree/Repos/GroveManager/data/edge.db \
  "SELECT channel, value, ts, forwarded_at FROM measurements WHERE channel LIKE 'irrigation_state.%' ORDER BY id DESC LIMIT 20;"

# Known station state from the poller
sqlite3 /home/bfree/Repos/GroveManager/data/edge.db \
  "SELECT station_id, is_on, updated_at FROM irrigation_station_state ORDER BY station_id;"

# Force a forward attempt now
curl -sS -X POST http://127.0.0.1:8080/admin/forward/run-once | python3 -m json.tool
```

If `pending_forward` stays at 0 and SQLite has no `irrigation_state.%` rows:

1. Confirm the sync loop is running — look for `Irrigation snapshot sync queued` every ~15s in logs.
2. Open Sprinkler run logging may be off — enable it in the Sprinkler section (`options.lg=1`) so startup/history backfill has `/jl` data.
3. After deploy, wait for startup history backfill (immediate) or run a station; periodic history runs every 5 minutes by default.

**Sift ingest tracing** — set `SIFT_INGEST_LOG=1` in your env overlay (or `/etc/orchardmonitor.env`) and restart. Logs include flow registration (`CreateIngestionConfigFlows`), channel order from Sift (`ListIngestionConfigFlows`), and sample ingest payloads (`IngestWithConfigDataStream`) with indexed channel names:

```bash
sudo journalctl -u orchardmonitor -f | grep -E "Sift |sift_py |sift_client "
```

Tune volume with `SIFT_INGEST_LOG_SAMPLE_N=3` (rows logged per flow per forward batch). On Pi TLS issues with the default SDK, try `SIFT_SDK_PREFER=py`.

Adjust backfill windows in the env overlay (then redeploy) or edit `/etc/orchardmonitor.env` and restart:

- `IRRIGATION_HISTORY_STARTUP_LOOKBACK_HOURS=24` — runs ingested on service start
- `IRRIGATION_HISTORY_LOOKBACK_MINUTES=5` — periodic `/jl` sync window

Then `sudo systemctl restart orchardmonitor` (or redeploy with `ENV_NAME=…`).

### Health from the Pi

```bash
curl -sS http://127.0.0.1:8080/health | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status | python3 -m json.tool
```

`/health` returns **200** when the forwarder is OK, and **503** with `"status": "degraded"` when there is pending data and no successful Sift forward for `FORWARD_STALE_SECONDS` (default 30 minutes). Useful fields:

| Field | Meaning |
| ----- | ------- |
| `forward.last_success_at` | Last successful batch this process |
| `forward.last_error` | Short error key (e.g. `dns_resolve_failed:grpc-api.siftstack.com`) |
| `forward.consecutive_failures` | Failure streak counter |
| `forward.failure_streak_seconds` | Wall time since the streak started |
| `oldest_pending_ts` | Oldest unforwarded measurement |

Repeated identical failures are **rate-limited** in `system_events` (default every 5 minutes) so the DB does not fill with full gRPC traces every 30s.

### Forward watchdog (auto-restart)

If forwarding keeps failing **while the network is reachable** with pending data for `FORWARD_RESTART_AFTER_SECONDS` (default **1 hour**), the process exits with code **78** so systemd `Restart=always` recycles it. That clears stuck gRPC/DNS client state.

While the internet/DNS is down, the watchdog **does not** restart the process (a restart cannot help until connectivity returns).

### Connectivity probe (auto-recover after internet loss)

When `SIFT_MODE=sdk`, each forward tick first DNS-resolves the Sift gRPC host (default timeout 3s):

1. **Offline** — skip gRPC (avoids long hangs), log `connectivity_lost` once, backoff.
2. **Back online** — log `connectivity_restored`, **drop the cached Sift client**, reset backoff, and **retry immediately**, then catch up the SQLite queue.

Tune via env:

```bash
# In env/<name>/orchardmonitor.env — then redeploy / restart
FORWARD_STALE_SECONDS=1800
FORWARD_RESTART_AFTER_SECONDS=3600
FORWARD_WATCHDOG_ENABLED=1
FORWARD_CONNECTIVITY_PROBE=1
FORWARD_CONNECTIVITY_PROBE_TIMEOUT_SECONDS=3
FORWARD_ERROR_LOG_INTERVAL_SECONDS=300
FORWARD_BACKOFF_MAX_SECONDS=300
```

Look for `connectivity_lost` / `connectivity_restored` / `forward_watchdog_restart` in logs or `system_events`.

**Note:** A process restart does **not** restart Tailscale. If MagicDNS itself stays wedged after the WAN is back, also try `sudo systemctl restart tailscaled` (see DNS resilience below). The connectivity probe will keep retrying until DNS works again.
### DNS resilience (Tailscale MagicDNS)

The Sep 2026 multi-day Sift outage was almost entirely DNS: `resolv.conf` on the Pi is overwritten by Tailscale (`nameserver 100.100.100.100` only), and lookups for `grpc-api.siftstack.com` failed for days until reboot.

Mitigations to consider on the Pi (host-level, not app):

1. **Confirm DNS** when Sift is failing:

```bash
getent hosts grpc-api.siftstack.com
cat /etc/resolv.conf
tailscale status
```

2. **Prefer LAN IP for Ecowitt** upload target (not a MagicDNS name), so weather ingest survives public-DNS breakage.

3. **Split DNS / fallback resolvers** — e.g. configure Tailscale admin DNS with public upstreams, or use `systemd-resolved` so `*.ts.net` goes to MagicDNS and everything else uses `1.1.1.1` / `8.8.8.8`. Avoid a single point of failure for Sift’s public API hostname.

4. If DNS is broken and the app has already restarted itself without recovery:

```bash
sudo systemctl restart tailscaled
sudo systemctl restart orchardmonitor
```

### Persistent journald (keep previous-boot logs)

The Pi had **volatile** journals only, so pre-reboot logs were lost. Enable persistence once:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-machine-id-setup 2>/dev/null || true
# Ensure Storage=persistent (or auto with the directory present)
sudo sed -i 's/^#\?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf
grep ^Storage= /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
```

Then `journalctl -u orchardmonitor -b -1` works after the next reboot.


## SSH and remote access

Deploy and ops both go over **SSH** (usually via Tailscale). Typical user on the Pi: **`bfree`**. Typical remote path: **`/home/bfree/Repos/GroveManager`**.

### 1. Tailscale on the Pi (one-time)

On the Pi (local keyboard/display or LAN SSH):

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4
```

Note the Pi’s Tailscale IPv4 (often `100.…`). On your laptop, confirm you can reach it:

```bash
ping -c 2 <pi-tailscale-ip>
curl -sS http://<pi-tailscale-ip>:8080/health
```

### 2. Log in over SSH

From your laptop:

```bash
ssh bfree@<pi-tailscale-ip>
```

Useful one-liners without a full interactive session:

```bash
ssh bfree@<pi-tailscale-ip> 'sudo systemctl status orchardmonitor orchardmonitor-ui --no-pager -l'
ssh bfree@<pi-tailscale-ip> 'curl -sS http://127.0.0.1:8080/health'
ssh bfree@<pi-tailscale-ip> 'sudo journalctl -u orchardmonitor -n 50 --no-pager'
```

### 3. SSH keys (recommended; stop password prompts)

`deploy_remote.sh` runs both `ssh` and `rsync` (over SSH). Password auth means **multiple prompts** per deploy. Prefer a public key.

On your laptop (skip `ssh-keygen` if you already have `~/.ssh/id_ed25519`):

```bash
ssh-keygen -t ed25519 -C "grovemanager-deploy"
ssh-copy-id bfree@<pi-tailscale-ip>
```

Verify passwordless login:

```bash
ssh bfree@<pi-tailscale-ip> 'echo ok'
```

### 4. Host alias + connection sharing (optional)

Add a host entry to your laptop `~/.ssh/config` so you can type `ssh orchard-pi` and so deploy reuses one connection (`ControlMaster`):

```sshconfig
Host orchard-pi
  HostName <pi-tailscale-ip>
  User bfree
  IdentityFile ~/.ssh/id_ed25519
  AddKeysToAgent yes
  UseKeychain yes
  ControlMaster auto
  ControlPath ~/.ssh/cm-%r@%h:%p
  ControlPersist 5m
```

Then:

```bash
ssh orchard-pi
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh orchard-pi /home/bfree/Repos/GroveManager
```

`ControlMaster` reuses a single connection across the `ssh` and `rsync` steps in one deploy.

## Deploy workflows (detail)



### Option A: `deploy_remote.sh` (recommended; no git on device)

This is the same path as [Deploy your changes](#deploy-your-changes-laptop--pi). Prefer always passing `ENV_NAME` so `/etc/orchardmonitor.env` stays in sync with your laptop overlay.

**Normal deploys:**

```bash
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**Create or refresh the env overlay:**

```bash
mkdir -p env/orchard-pi
cp env/_example/orchardmonitor.env env/orchard-pi/orchardmonitor.env
$EDITOR env/orchard-pi/orchardmonitor.env
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**If you see** `permission denied: ./scripts/deploy_remote.sh`**:**

```bash
chmod +x scripts/deploy_remote.sh
```

or:

```bash
bash scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**If** `rsync` **failed around** `.deploy`**:** ensure SSH works; the script `mkdir -p`’s `${REMOTE_DIR}/.deploy` and excludes `.deploy` from the delete-style rsync so the staging area survives.

**Env when not using** `ENV_NAME=...`**:**

- By default, the script **creates** `/etc/orchardmonitor.env` from `orchardmonitor.env.example` **only if missing**. Prefer `env/_example/orchardmonitor.env` + `ENV_NAME=…` instead — the root template may still show an old `OrchardMonitor` data path.
- **Avoid** `REMOTE_ENV_PUSH=1` unless you intend to overwrite the live file from that root template.



### Option B: Manual rsync + restart (escape hatch)

```bash
rsync -avz --exclude venv --exclude data --exclude .deploy --exclude .local-data \
  ./ <user>@<pi-tailscale-ip>:/home/<user>/Repos/GroveManager/
ssh <user>@<pi-tailscale-ip> 'cd /home/<user>/Repos/GroveManager && ./venv/bin/pip install -r requirements.txt && sudo systemctl restart orchardmonitor && curl -sS http://127.0.0.1:8080/health'
```

(Wire up the UI unit yourself if you need it; the managed path is `deploy_remote.sh`.)
# Runbooks

Copy/paste reference for **local test/run**, **checking status**, and **deploy**. Prefer Tailscale (or a known LAN IP) for remote URLs.

## Quick reference

### Local: test and run

| Step | Command |
|------|--------|
| Create venv + install deps (implicit in targets) | `make install` (optional; `make test` does it) |
| Run tests | `make test` |
| Run the edge API (foreground) | `make run-local` |
| Send a sample `POST /ecowitt` | `make send-ecowitt` |
| Show latest local readings | `make print-latest` |

`make run-local` uses `DATA_STORAGE_PATH=./.local-data` and listens on **0.0.0.0:8080** (Flask dev server).

### Check status (local, API running)

```bash
curl -sS http://127.0.0.1:8080/health  | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status  | python3 -m json.tool
curl -sS -X POST http://127.0.0.1:8080/admin/forward/run-once | python3 -m json.tool
```

### Operator UI (optional, local dev)

The UI is a separate origin from the API; set **`CORS_ALLOW_ORIGINS`** when running the API (e.g. in the same shell before `make run-local`, or export in your profile):

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

Open the URL Vite prints (default **http://127.0.0.1:5173**).

### Deploy (laptop → Pi)

**Prereqs on the laptop:** `ssh`, `rsync`, Python 3 (for venv on the device), and **`npm` + `node` if you want the deploy script to build the UI** (or build `src/ui/dist` yourself and use `SKIP_UI_BUILD=1`).

1. **One-time:** copy the example env and create `env/<name>/orchardmonitor.env` (see `env/_example/orchardmonitor.env`). For a split **UI (5173)** + **API (8080)** deployment, include **`CORS_ALLOW_ORIGINS`**, e.g. `http://<pi-or-tailscale-ip>:5173` or `*` on a private tailnet.

2. **Normal deploy** (pushes your env, rsyncs code, builds UI when `npm` exists, restarts services):

```bash
ENV_NAME=<your-env> ./scripts/deploy_remote.sh <user>@<pi-ip> <remote_repo_path>
```

**First boot on a fresh Pi** (Debian / Raspberry Pi OS, installs minimal apt packages once):

```bash
BOOTSTRAP=1 ENV_NAME=<your-env> ./scripts/deploy_remote.sh <user>@<pi-ip> <remote_repo_path>
```

**No Node on the laptop** (you must have a prebuilt `src/ui/dist`):

```bash
SKIP_UI_BUILD=1 ENV_NAME=<your-env> ./scripts/deploy_remote.sh <user>@<pi-ip> <remote_repo_path>
```

**Deploy script notes:**

- Bakes **`VITE_EDGE_API_BASE` into the UI** at build time, defaulting to **`http://<host-from-target>:8080`** (e.g. target `bfree@100.…` → `http://100.…:8080`). Override with **`UI_EDGE_API_BASE=...`**, or change the API port with **`EDGE_HTTP_PORT=...`**.
- Pushes the built `dist/` to the Pi, installs/starts **`orchardmonitor-ui.service`** (listens on **0.0.0.0:5173**). The main API is **`orchardmonitor.service` on 8080**.

3. **Verify on the Pi** (SSH in):

```bash
sudo systemctl status orchardmonitor orchardmonitor-ui --no-pager -l
curl -sS http://127.0.0.1:8080/health  | python3 -m json.tool
curl -sS http://127.0.0.1:8080/status  | python3 -m json.tool
curl -sS -I http://127.0.0.1:5173/ | head -n 5
```

4. **From your laptop** (use the Pi’s Tailscale or LAN IP): open **`http://<pi-ip>:5173`**. The UI calls the API at the URL baked in at build time; if the browser shows JSON errors mentioning `<!doctype`, fix **`VITE_EDGE_API_BASE`** (redeploy) and **`CORS_ALLOW_ORIGINS`** (env file, then restart `orchardmonitor`).

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

In normal operation you do **not** need to hand-install OS packages on the Pi if you used **`BOOTSTRAP=1`** once with `deploy_remote.sh`.

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

Installed/updated by `scripts/deploy_remote.sh` when you use `ENV_NAME=...`. See `env/_example/orchardmonitor.env` for `CORS_ALLOW_ORIGINS` and Sift fields.

### View logs

```bash
sudo journalctl -u orchardmonitor -f
sudo journalctl -u orchardmonitor-ui -f
```

### Health from the Pi

```bash
curl -sS http://127.0.0.1:8080/health | python3 -m json.tool
```

## Remote access (Tailscale)

On the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

From your laptop:

```bash
curl -sS http://<pi-tailscale-ip>:8080/health
```

## SSH auth (stop repeated password prompts)

`deploy_remote.sh` uses both `ssh` and `rsync` (which uses `ssh`). With password auth you get **multiple prompts** per run. Prefer **SSH public keys** and optional **ControlMaster** (see below).

### One-time: install your public key on the Pi

On your laptop:

```bash
ssh-keygen -t ed25519 -C "grovemanager-deploy"
ssh-copy-id bfree@<pi-tailscale-ip>
```

Verify:

```bash
ssh bfree@<pi-tailscale-ip> 'echo ok'
```

### Optional: connection sharing (ControlMaster)

Add a host entry to your laptop `~/.ssh/config`:

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
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh orchard-pi /home/bfree/Repos/GroveManager
```

`ControlMaster` reuses a single connection across the `ssh` and `rsync` steps in one deploy.

## Deploy workflows (detail)

### Option A: `deploy_remote.sh` (recommended; no git on device)

**Normal deploys:**

```bash
./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**With env overlay (recommended):**

```bash
cp env/_example/orchardmonitor.env env/orchard-pi/orchardmonitor.env
$EDITOR env/orchard-pi/orchardmonitor.env
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**If you see `permission denied: ./scripts/deploy_remote.sh`:**

```bash
chmod +x scripts/deploy_remote.sh
```

or:

```bash
bash scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

**If `rsync` failed around `.deploy`:** ensure SSH works; the script `mkdir -p`’s `${REMOTE_DIR}/.deploy` and excludes `.deploy` from the delete-style rsync so the staging area survives.

**Env when not using `ENV_NAME=...`:**

- By default, the script **creates** `/etc/orchardmonitor.env` from `orchardmonitor.env.example` **only if missing**.
- **Avoid** `REMOTE_ENV_PUSH=1` unless you intend to overwrite the live file from the repo template.

### Option B: Manual rsync + restart (escape hatch)

```bash
rsync -avz --exclude venv --exclude data --exclude .deploy --exclude .local-data \
  ./ <user>@<pi-tailscale-ip>:/home/<user>/Repos/GroveManager/
ssh <user>@<pi-tailscale-ip> 'cd /home/<user>/Repos/GroveManager && ./venv/bin/pip install -r requirements.txt && sudo systemctl restart orchardmonitor && curl -sS http://127.0.0.1:8080/health'
```

(Wire up the UI unit yourself if you need it; the managed path is `deploy_remote.sh`.)

# Migration: current Pi deploy → remote-deployed edge node (no device Git access)

This is the “do this once (or a few times)” set of steps to move whatever is running on the orchard Pi into a repeatable, laptop-driven deploy loop.

## Goal state

- The device **does not need GitHub**: no `git clone` / `git pull` is required to ship updates.
- The Pi runs a single `systemd` service (`orchardmonitor.service` by default) from a stable directory.
- The Pi only needs: **SSH** (Tailscale), **Python 3** + **venv**, and standard utilities (`rsync`, `curl`, `ca-certificates`).
- Configuration is driven from your laptop; you keep the full per-environment file locally at `env/<name>/orchardmonitor.env` (gitignored) and it is installed to `/etc/orchardmonitor.env` on each deploy.
- You can validate locally first (`make test`, `make run-local`).

## Step 0: Snapshot what is currently running (safety)

On the Pi, capture (or at least note) the current:

- service entrypoint, env vars, and any cron/systemd timers
- Ecowitt gateway “custom server” target URL
- data directory and disk usage
- OpenSprinkler URL + password (if you use the schedule features)

## Step 1: First deploy to the Pi (bootstrap + install venv + systemd + restart)

1) On your laptop, create the env overlay (you only do this when you are setting up a new target):

```bash
cp env/_example/orchardmonitor.env env/orchard-pi/orchardmonitor.env
$EDITOR env/orchard-pi/orchardmonitor.env
```

2) Ensure the target directory exists on the Pi (SSH in once, or this can be a one-liner if you want):

```bash
ssh <user@pi-tailscale-ip> 'mkdir -p /home/<user>/Repos/GroveManager'
```

3) From your laptop, first-time bootstrap (this installs the minimal `apt` packages you used to do manually, then does the code sync + venv + systemd + restart):

```bash
BOOTSTRAP=1 ENV_NAME=orchard-pi ./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

`BOOTSTRAP=1` is for **Raspberry Pi OS / Debian / Ubuntu** and runs `apt-get` to install `python3`, `python3-venv`, `rsync`, `curl`, and `ca-certificates` if needed. After a successful first deploy, you can usually omit it.

4) You should see JSON from `GET /health` printed at the end of the script output.

## Step 2: Cut over the Ecowitt gateway

Point your Ecowitt “customized” endpoint to:

- `http://<pi-lan-ip>:8080/ecowitt` (local to the farm network), and/or
- `http://<pi-tailscale-ip>:8080/ecowitt` (handy, but you probably don’t *need* Ecowitt to go through Tailscale in most cases)

## Step 3: Data directory strategy

If you are migrating an existing on-disk `measurements/` tree, pick one of:

- Point `DATA_STORAGE_PATH` in `env/orchard-pi/orchardmonitor.env` at the existing directory, or
- Rsync the old `measurements/` and logs to `${DATA_STORAGE_PATH}/`

The service will write:

- `${DATA_STORAGE_PATH}/measurements/YYYY-MM-DD.parquet` (time series storage)
- `${DATA_STORAGE_PATH}/edge.db` (local forward index + system events)
- `${DATA_STORAGE_PATH}/fake_sift.jsonl` if `SIFT_MODE=fake`

## Step 4: Enable Sift (when ready)

Edit `env/orchard-pi/orchardmonitor.env` to set (at minimum):

- `SIFT_MODE=sdk`
- `SIFT_API_KEY=...`
- `SIFT_GRPC_URL=...`
- `SIFT_REST_URL=...`
- `SIFT_ASSET=orchard-main`

Re-deploy (no `BOOTSTRAP=1` needed):

```bash
ENV_NAME=orchard-pi ./scripts/deploy_remote.sh <user@pi-tailscale-ip> /home/<user>/Repos/GroveManager
```

Trigger one forward batch to validate end-to-end:

```bash
curl -X POST http://<pi-lan-or-tailscale>:8080/admin/forward/run-once | python -m json.tool
```

If Sift is misconfigured, `GET /status` on the Pi will show the recent forward errors.

## Step 5: Day-to-day iteration (the loop you want)

- Edit code on your laptop and run `make test` locally
- Push to the Pi with the same `ENV_NAME=... ./scripts/deploy_remote.sh ...` line

## Optional: manual `systemd` / env plumbing

The deploy script installs/updates the unit and an env drop-in, but you can also follow `docs/runbooks.md` to do it by hand in edge cases.


# OrchardMonitor

A simple Raspberry Pi server that stores Ecowitt telemetry as daily parquet files and logs Open Sprinkler schedules.

## Features

- **Measurements**: Receives Ecowitt data via `POST /ecowitt`, appends to daily parquet files (`data/measurements/YYYY-MM-DD.parquet`)
- **Schedule logging**: Polls Open Sprinkler every 12 hours, appends to `data/schedule_log.jsonl`
- **Schedule update**: `POST /schedule/update` to change Open Sprinkler schedule, logs to `data/schedule_updates.jsonl` and triggers immediate schedule log

## Requirements

- Python 3.7+
- Raspberry Pi (or compatible Linux)
- Ecowitt weather station with gateway
- Open Sprinkler (optional; schedule features disabled if not configured)

## Installation

```bash
git clone <repository-url>
cd OrchardMonitor

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_STORAGE_PATH` | `data` | Base path for parquet and log files |
| `OPENSPRINKLER_URL` | (none) | Open Sprinkler base URL (e.g. `http://192.168.1.x:8080`) |
| `OPENSPRINKLER_PASSWORD` | (none) | Plain-text password (MD5-hashed for API) |

Set `OPENSPRINKLER_URL` and `OPENSPRINKLER_PASSWORD` to enable schedule logging and the update endpoint. Without them, measurements still work.

Copy `orchardmonitor.env.example` to `/etc/orchardmonitor.env` (or use it as a template locally) and fill in your values.

### Configuring Ecowitt

1. **Find your Pi’s IP** (e.g. `hostname -I` or your router’s DHCP list). If using Tailscale, use the Pi’s Tailscale IP (e.g. `100.x.x.x`).

2. **Open the Ecowitt gateway** (GW1000/GW1100/GW1200, or HP2551 console, etc.) in a browser or use the Ecowitt app, and go to **Customized** / **Custom Server** (or equivalent).

3. **Enable “Customized”** and set:
   - **Server URL / Path**: `http://<pi-ip>:8080/ecowitt`  
     Example: `http://192.168.1.50:8080/ecowitt` or `http://100.x.x.x:8080/ecowitt` for Tailscale.
   - **Protocol**: HTTP GET or HTTP POST (this server accepts POST; many gateways send GET with query params—check your gateway docs).
   - **Upload interval**: e.g. every 60–300 seconds.

4. **Save** and ensure OrchardMonitor is running (`systemctl status orchardmonitor`). Data will appear under `data/measurements/` as daily parquet files.

### Configuring Open Sprinkler

1. **Find the Open Sprinkler URL**: In the Open Sprinkler web UI, note the address you use (e.g. `http://192.168.1.100:8080` for local, or your OpenSprinkler Pi/device IP and port).

2. **Get the API password**: In the Open Sprinkler UI, go to **System** → **Network** (or **Settings**). The “Password” used for the web login is the same one you use for the API (stored as plain text in env; the server MD5-hashes it when calling the API).

3. **Set environment variables** (in `/etc/orchardmonitor.env` or your systemd unit):
   - `OPENSPRINKLER_URL` = base URL with no trailing slash, e.g. `http://192.168.1.100:8080`
   - `OPENSPRINKLER_PASSWORD` = your Open Sprinkler password (plain text)

4. **Restart** the service: `sudo systemctl restart orchardmonitor`. Schedule logging runs every 12 hours; you can also trigger a schedule update via `POST /schedule/update` to refresh immediately.

## Usage

### Run manually

```bash
source venv/bin/activate
python src/server.py
```

Server listens on `0.0.0.0:8080`.

### Run at startup (systemd)

1. Copy `orchardmonitor.env.example` to `/etc/orchardmonitor.env`, set `DATA_STORAGE_PATH`, `OPENSPRINKLER_URL`, and `OPENSPRINKLER_PASSWORD`. In the unit’s `[Service]` block add: `EnvironmentFile=/etc/orchardmonitor.env`

2. Install and enable:

```bash
sudo cp orchardmonitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable orchardmonitor
sudo systemctl start orchardmonitor
sudo systemctl status orchardmonitor
```

3. View logs: `journalctl -u orchardmonitor -f`

## Tailscale (remote access)

1. Install Tailscale on the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

2. Add `After=tailscaled.service` to the `[Unit]` section of `orchardmonitor.service` if you want the server to start after Tailscale.

3. Access from anywhere on your Tailnet: `http://100.x.x.x:8080` (replace with your Pi’s Tailscale IP).

## Remote development

**Option A: SSH + Git**

```bash
ssh bfree@<tailscale-ip>
cd /home/bfree/Repos/OrchardMonitor
git pull
sudo systemctl restart orchardmonitor
```

**Option B: VS Code / Cursor Remote SSH**

1. Install "Remote - SSH".
2. Add host `bfree@<tailscale-ip>`.
3. Edit and run on the Pi, then restart the service after changes.

**Option C: Deploy script**

From your dev machine:

```bash
rsync -avz --exclude venv --exclude data ./ bfree@<tailscale-ip>:/home/bfree/Repos/OrchardMonitor/
ssh bfree@<tailscale-ip> 'cd /home/bfree/Repos/OrchardMonitor && sudo systemctl restart orchardmonitor'
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ecowitt` | Ecowitt form-encoded telemetry |
| GET | `/health` | Health check |
| POST | `/schedule/update` | Update Open Sprinkler schedule (JSON body: API params for /cp) |

## Data layout

```
data/
├── measurements/
│   └── 2026-02-01.parquet
├── schedule_log.jsonl
└── schedule_updates.jsonl
```

## Project structure

```
OrchardMonitor/
├── src/
│   ├── server.py           # Main Flask app
│   ├── measurement_store.py
│   └── schedule_logger.py
├── orchardmonitor.env.example   # Copy to /etc/orchardmonitor.env
├── orchardmonitor.service
├── requirements.txt
└── README.md
```

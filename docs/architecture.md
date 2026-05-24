# GroveManager Edge Architecture

This doc describes how the edge service works end-to-end: what runs on the Pi, what data is persisted locally, and how data is forwarded to Sift.

## High-level goals

- **Store-first**: ingest should succeed even if the network / Sift is down.
- **Simple deploy**: the Pi does not need `git` or GitHub access; deploy from your laptop over SSH/rsync.
- **Observable**: you can answer “is it ingesting?” and “is it forwarding?” from the Pi with curl + logs.

## Main runtime components

- **HTTP server**: `src/server.py` (Flask)
  - Receives Ecowitt POSTs at `POST /ecowitt`
  - Exposes health + status endpoints (`/health`, `/status`)
  - Exposes an admin trigger endpoint (`POST /admin/forward/run-once`)
- **Bulk storage**: `src/measurement_store.py`
  - Writes one Parquet file per UTC day under `DATA_STORAGE_PATH/measurements/YYYY-MM-DD.parquet`
  - Intended for “bulk history” / export / offline inspection
- **Store-and-forward queue**: `src/edge_db.py` (SQLite)
  - Stores the raw ingest event
  - Stores normalized `(ts, channel, value)` measurements
  - Tracks forwarding state (pending/forwarded/errors)
  - Stores lightweight system events used by `/status` (recent forwarding errors, etc.)
- **Forwarding loop**: `src/forwarder.py`
  - `BackgroundForwardLoop` wakes up every `FORWARD_INTERVAL_SECONDS`
  - `ForwardWorker.run_once()` pulls a batch of pending rows from SQLite and sends them
  - Marks rows forwarded (or records error + leaves them pending for retry)

## Data model: “raw” vs “normalized”

Each `/ecowitt` POST produces:

- **Raw event** (SQLite): the original form payload, stored as JSON for replay/debug.
- **Normalized measurements** (SQLite): a list of numeric channel/value points:
  - Channel naming convention: `ecowitt.<key>` (e.g. `ecowitt.soilmoisture1`)
  - Irrigation channels: `irrigation_state.stationNN` (`true`/`false` as Sift `BOOL`), from Open Sprinkler sync
  - Value: float (non-numeric values are currently skipped for forwarding)
- **Bulk record** (Parquet): a row containing the timestamp plus all keys/values from the payload.

The normalized SQLite table is what drives forwarding; Parquet is a “bulk log”.

## End-to-end app flow

### 1) Ingest

1. Ecowitt device posts to `POST /ecowitt` on the Pi.
2. The server:
   - Parses timestamp (`dateutc`) if present; otherwise uses “now”.
   - Writes a bulk row to Parquet (daily file).
   - Inserts a raw event into SQLite.
   - Normalizes numeric values to channel/value pairs and inserts them into SQLite as pending.
3. Response is `200 OK` (`"OK"`), even if non-critical steps fail (the goal is “keep ingesting”).

### 2) Forwarding

Forwarding happens in either mode:

- **Automatic**: the background loop wakes up on `FORWARD_INTERVAL_SECONDS`. When
  `pending_forward` exceeds `FORWARD_CATCHUP_THRESHOLD`, it switches to catch-up mode:
  larger batches (`FORWARD_CATCHUP_BATCH_SIZE`), one gRPC stream per batch, and
  `FORWARD_CATCHUP_INTERVAL_SECONDS` between attempts (often `0` = back-to-back).
- **Manual**: `POST /admin/forward/run-once` (optional `?batch_size=`), or
  `POST /admin/forward/catchup` to drain until idle or limits.

When a forward attempt runs:

1. `ForwardWorker` selects up to `batch_size` pending measurement rows (500 steady,
   up to `FORWARD_CATCHUP_BATCH_SIZE` when the queue is deep).
2. It converts each row to a point: `{ts, channel, value}`, coalesces rows that share
   a timestamp (one Ecowitt reading → one gRPC ingest), and splits by UTC day for Sift runs.
3. It sends the batch via the configured forwarder (single streaming gRPC session per batch):
   - `SIFT_MODE=fake`: write JSONL to `FAKE_SIFT_OUT` (offline validation)
   - `SIFT_MODE=sdk`: send to Sift (see next section)
4. On success: marks the rows forwarded.
5. On failure: records the error on the rows and emits a system event; rows remain eligible for retry.

## Sift integration (current behavior)

Forwarding uses:

- **asset**: `SIFT_ASSET` / `SIFT_ASSET_NAME`
- **flows**: SHA-256 of the sorted channel names in each family (16 hex chars). One flow for all `irrigation_state.*` channels in the batch; one flow for all `ecowitt.*` channels. If the channel set changes, the hash (and Sift flow) changes automatically.
- **ingestion configs**: ecowitt uses `SIFT_INGESTION_CLIENT_KEY`; irrigation uses `SIFT_IRRIGATION_INGESTION_CLIENT_KEY` when set (fresh config for `irrigation_state.*`).
- **ingestion client key**: `SIFT_INGESTION_CLIENT_KEY` (stable; do not vary by batch size)
- **run naming**: `"<asset>.<YYYY-MM-DD>"` (one run per asset per UTC day)

### Irrigation → Sift

When Open Sprinkler is configured, a background **irrigation sync loop** polls the controller and enqueues on/off measurements into the same SQLite forward queue as Ecowitt data.

- **Channels**: `irrigation_state.station01`, `irrigation_state.station02`, … (1-indexed, zero-padded; Open Sprinkler station id `0` → `station01`)
- **Values**: `true` = on, `false` = off (Sift `BOOL` channel type)
- **Live state**: snapshot poll every `IRRIGATION_SYNC_INTERVAL_SECONDS` (default 15s); emits current on/off for every station each tick
- **History backfill**: optional periodic sync from device `/jl` run log (default every 300s, last 5 minutes); requires run logging enabled on the device (`options.lg = 1`)
- **Immediate sync**: manual run/stop via `POST /integrations/opensprinkler/station` triggers a snapshot sync without waiting for the next poll

Implementation: `src/libs/irrigation_sync.py`. State tables in SQLite track last-known station on/off and dedupe history backfill.

Controls:

- `IRRIGATION_SYNC_ENABLED=1` (default when Open Sprinkler is configured; set `0` to disable)
- `IRRIGATION_SYNC_INTERVAL_SECONDS=15`
- `IRRIGATION_HISTORY_SYNC_INTERVAL_SECONDS=300` (set `0` to disable history backfill)
- `IRRIGATION_HISTORY_LOOKBACK_MINUTES=5` (periodic backfill window)
- `IRRIGATION_HISTORY_STARTUP_LOOKBACK_HOURS=24` (one-time backfill on service start)

In Sift, active sprinklers are channels whose latest value is `true`.

### SDK preference vs fallback

The code prefers the modern `sift_client` path, but will fall back to `sift_py` if the modern
client hits known transport errors on some hosts (e.g. TLS errors seen on the Pi).

Controls:

- `SIFT_SDK_PREFER=client` (default): try modern client first, fallback on known transport failure
- `SIFT_SDK_PREFER=py`: force legacy client

### Debugging forwarding

Enable verbose streaming logs:

- `SIFT_DEBUG=1`
- `SIFT_DEBUG_SAMPLE_N=3` (how many points to log)

Then inspect with:

```bash
sudo journalctl -u orchardmonitor -f
```

## Operational endpoints

- `GET /health`
  - Quick liveness + queue depth signal
- `GET /status`
  - Includes config echoes (paths, sift mode/asset) + queue depth + recent system events
- `POST /admin/forward/run-once`
  - Forces a single forward attempt and returns `{attempted, forwarded, error}`

## Deployment model (Pi)

The service runs under **systemd** as `orchardmonitor` and reads configuration from:

- `/etc/orchardmonitor.env` (installed via deploy script)

Deploy from laptop:

- `scripts/deploy_remote.sh` rsyncs code, ensures venv + deps, installs/updates systemd unit, restarts the service.


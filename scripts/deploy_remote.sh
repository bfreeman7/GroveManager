#!/usr/bin/env bash
set -euo pipefail

#
# Remote deploy from your laptop -> Pi over SSH (e.g., Tailscale).
#
# Goal: the device never needs to git pull. We:
# - rsync code to the device
# - create/update venv + pip install requirements
# - install/update systemd unit + env drop-in
# - (optionally) copy env file template if missing
# - restart service and print /health
#
# Usage:
#   ./scripts/deploy_remote.sh <user@host> [remote_repo_dir]
#
# Examples:
#   ./scripts/deploy_remote.sh bfree@100.x.x.x /home/bfree/Repos/GroveManager
#   # First time on a fresh Pi (Raspberry Pi OS / Debian with apt):
#   BOOTSTRAP=1 ./scripts/deploy_remote.sh bfree@100.x.x.x /home/bfree/Repos/GroveManager
#   # Recommended config push (gitignored):
#   ENV_NAME=orchard-pi ./scripts/deploy_remote.sh bfree@100.x.x.x /home/bfree/Repos/GroveManager
#   # Skip building the Vite UI (e.g. no Node on this machine; you must have src/ui/dist/ already)
#   SKIP_UI_BUILD=1 ./scripts/deploy_remote.sh bfree@100.x.x.x /home/bfree/Repos/GroveManager
#   # Legacy: overwrite /etc from repo template
#   REMOTE_ENV_PUSH=1 ./scripts/deploy_remote.sh bfree@orchard-pi /home/bfree/Repos/GroveManager
#

TARGET="${1:-}"
REMOTE_DIR="${2:-}"

if [[ -z "${TARGET}" ]]; then
  echo "Usage: $0 <user@host> [remote_repo_dir]" >&2
  exit 2
fi

# Extract remote username from user@host (fallback to current user if host-only).
REMOTE_USER="${TARGET%@*}"
if [[ "${REMOTE_USER}" == "${TARGET}" ]]; then
  REMOTE_USER="${USER}"
fi
REMOTE_HOST="${TARGET#*@}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -z "${REMOTE_DIR}" ]]; then
  REMOTE_DIR="/home/${USER}/Repos/GroveManager"
fi

SERVICE_NAME="${SERVICE_NAME:-orchardmonitor}"
ENV_FILE="${ENV_FILE:-/etc/orchardmonitor.env}"

# Env push (recommended): create an env overlay locally at env/<name>/orchardmonitor.env
# and set ENV_NAME=<name> to push it on every deploy.
ENV_NAME="${ENV_NAME:-}"
BOOTSTRAP="${BOOTSTRAP:-0}"  # 1 => install required OS packages on Debian/Raspberry Pi OS (apt)
REMOTE_ENV_PUSH="${REMOTE_ENV_PUSH:-0}"       # 1 => overwrite env file with repo template (legacy; avoid)
REMOTE_ENV_COPY_IF_MISSING="${REMOTE_ENV_COPY_IF_MISSING:-1}" # 1 => copy template only if missing (legacy)
SKIP_UI_BUILD="${SKIP_UI_BUILD:-0}" # 1 => do not run npm in src/ui; use existing src/ui/dist if present

UI_DIR="${REPO_DIR}/src/ui"
EDGE_HTTP_PORT="${EDGE_HTTP_PORT:-8080}"
# Used only at UI build time (Vite env var). If unset, we default to the target host + EDGE_HTTP_PORT.
UI_EDGE_API_BASE="${UI_EDGE_API_BASE:-}"

RSYNC_EXCLUDES=(
  "--exclude" "venv"
  "--exclude" ".venv"
  "--exclude" "data"
  "--exclude" ".local-data"
  "--exclude" "src/ui/node_modules"
  "--exclude" "src/ui/dist"
  # Staging area for env upload; must never be deleted by the main `rsync --delete`
  "--exclude" ".deploy"
  "--exclude" "__pycache__"
  "--exclude" ".pytest_cache"
  "--exclude" ".DS_Store"
)

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd rsync
require_cmd ssh

remote_sh() {
  # Run a command on the remote.
  # NOTE: Avoid `ssh -t` here; TTY allocation can make failures harder to reason about
  # for non-interactive steps, and is not required for mkdir/rsync.
  ssh "${TARGET}" "$@"
}

echo "==> Local repo: ${REPO_DIR}"
echo "==> Target: ${TARGET}"
echo "==> Remote dir: ${REMOTE_DIR}"
echo "==> BOOTSTRAP: ${BOOTSTRAP}"
echo "==> SKIP_UI_BUILD: ${SKIP_UI_BUILD}"
echo "==> EDGE_HTTP_PORT: ${EDGE_HTTP_PORT}"
if [[ -n "${ENV_NAME}" ]]; then
  echo "==> ENV_NAME: ${ENV_NAME}"
else
  echo "==> ENV_NAME: (not set)"
fi

# Optional one-time (or re-run) OS package install for Raspberry Pi OS / Debian systems.
# This is intentionally off by default so you don't get surprised apt side effects.
if [[ "${BOOTSTRAP}" == "1" ]]; then
  echo "==> Bootstrapping remote host (apt packages)"
  # shellcheck disable=SC2029
  remote_sh "bash -lc 'set -euo pipefail
    if ! command -v apt-get >/dev/null 2>&1; then
      echo \"apt-get not found. BOOTSTRAP=1 currently supports Debian/Ubuntu/Raspberry Pi OS.\" >&2
      echo \"If you are not on apt-based Linux, install python3+venv+rsync+curl manually, then re-run.\" >&2
      exit 1
    fi
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv rsync curl ca-certificates
  '"
fi

echo "==> Preparing remote directories"
RDIR_Q="$(printf %q "${REMOTE_DIR}")"
# shellcheck disable=SC2029
remote_sh "bash -lc 'set -euo pipefail; mkdir -p ${RDIR_Q}'"
# shellcheck disable=SC2029
remote_sh "bash -lc 'set -euo pipefail; test -d ${RDIR_Q}'"

# Build the Vite + React operator UI on the deploy host (laptop), then rsync only dist/ to the Pi.
# src/ui/node_modules and src/ui/dist are excluded from the main code sync.
if [[ "${SKIP_UI_BUILD}" == "1" ]]; then
  echo "==> UI build: skipped (SKIP_UI_BUILD=1)"
elif [[ ! -f "${UI_DIR}/package.json" ]]; then
  echo "==> UI build: skipped (no ${UI_DIR}/package.json)"
else
  echo "==> UI build: npm install + npm run build (${UI_DIR})"
  if ! command -v npm >/dev/null 2>&1; then
    echo "==> UI build: skipped (npm not found). Install Node/npm or re-run with SKIP_UI_BUILD=1."
  else
    if [[ -z "${UI_EDGE_API_BASE}" ]]; then
      UI_EDGE_API_BASE="http://${REMOTE_HOST}:${EDGE_HTTP_PORT}"
    fi
    echo "==> UI build: VITE_EDGE_API_BASE=${UI_EDGE_API_BASE}"
    (
      set -euo pipefail
      cd "${UI_DIR}"
      if [[ -f package-lock.json ]] || [[ -f npm-shrinkwrap.json ]]; then
        VITE_EDGE_API_BASE="${UI_EDGE_API_BASE}" npm ci
      else
        VITE_EDGE_API_BASE="${UI_EDGE_API_BASE}" npm install
      fi
      VITE_EDGE_API_BASE="${UI_EDGE_API_BASE}" npm run build
    )
  fi
fi

echo "==> rsync code"
rsync -az --delete "${RSYNC_EXCLUDES[@]}" "${REPO_DIR}/" "${TARGET}:${REMOTE_DIR}/"

# The env upload step stages into `${REMOTE_DIR}/.deploy` on the remote.
# Ensure it exists (and is protected from the delete-sync via `--exclude .deploy`).
# shellcheck disable=SC2029
remote_sh "bash -lc 'set -euo pipefail; mkdir -p ${RDIR_Q}/.deploy'"

# Optional UI deploy overlay: if you've built the UI locally (`src/ui/dist/`),
# push it to the remote staging area without requiring Node on the device.
LOCAL_UI_DIST="${REPO_DIR}/src/ui/dist"
REMOTE_UI_DIST="${REMOTE_DIR}/.deploy/ui-dist"
if [[ -d "${LOCAL_UI_DIST}" ]]; then
  echo "==> Push UI dist overlay: src/ui/dist -> ${REMOTE_UI_DIST}"
  # Ensure staging dir exists, then sync dist into it.
  # shellcheck disable=SC2029
  remote_sh "bash -lc 'set -euo pipefail; mkdir -p ${RDIR_Q}/.deploy/ui-dist'"
  rsync -az --delete "${LOCAL_UI_DIST}/" "${TARGET}:${REMOTE_UI_DIST}/"
else
  echo "==> UI dist overlay: (not found locally, skipping)"
fi

LOCAL_ENV_PATH=""
if [[ -n "${ENV_NAME}" ]]; then
  LOCAL_ENV_PATH="${REPO_DIR}/env/${ENV_NAME}/orchardmonitor.env"
  if [[ ! -f "${LOCAL_ENV_PATH}" ]]; then
    echo "ENV_NAME set but missing ${LOCAL_ENV_PATH}" >&2
    echo "Create it from env/_example/orchardmonitor.env" >&2
    exit 1
  fi

  echo "==> Push env overlay: env/${ENV_NAME}/orchardmonitor.env -> ${ENV_FILE}"
  # Copy to a temp path first; we will sudo move into place on the remote.
  rsync -az "${LOCAL_ENV_PATH}" "${TARGET}:${REMOTE_DIR}/.deploy/orchardmonitor.env"
fi

echo "==> Ensure venv + deps + systemd on remote"
# shellcheck disable=SC2029
ssh -t "${TARGET}" "bash -lc '
  set -euo pipefail
  cd \"${REMOTE_DIR}\"
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt

  # Install systemd unit
  sudo tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null <<EOF
[Unit]
Description=OrchardMonitor - measurements and Open Sprinkler schedule
After=network.target

[Service]
Type=simple
User=${REMOTE_USER}
WorkingDirectory=${REMOTE_DIR}
Environment=DATA_STORAGE_PATH=${REMOTE_DIR}/data
LimitNOFILE=65535
ExecStart=${REMOTE_DIR}/venv/bin/python src/server.py
Restart=always
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=120

[Install]
WantedBy=multi-user.target
EOF

  # Ensure unit loads env file via drop-in
  sudo mkdir -p /etc/systemd/system/${SERVICE_NAME}.service.d
  sudo tee /etc/systemd/system/${SERVICE_NAME}.service.d/env.conf >/dev/null <<EOF
[Service]
EnvironmentFile=${ENV_FILE}
EOF

  # If an env overlay was pushed, install it every deploy.
  if [[ -f \"${REMOTE_DIR}/.deploy/orchardmonitor.env\" ]]; then
    echo \"Installing pushed env overlay into ${ENV_FILE}\"
    # NOTE: The dirname+install -d line uses a leading backslash on the dollar so the laptop
    # (running this script) does not expand it before the remote shell sees the command.
    sudo install -d \"\$(dirname \"${ENV_FILE}\")\"
    sudo cp \"${REMOTE_DIR}/.deploy/orchardmonitor.env\" \"${ENV_FILE}\"
  fi

  # Env file handling: by default, only create a template if missing.
  if [[ \"${REMOTE_ENV_PUSH}\" == \"1\" ]]; then
    echo \"Overwriting ${ENV_FILE} from repo template (REMOTE_ENV_PUSH=1)\"
    sudo cp orchardmonitor.env.example \"${ENV_FILE}\"
  elif [[ \"${REMOTE_ENV_COPY_IF_MISSING}\" == \"1\" && ! -f \"${ENV_FILE}\" ]]; then
    echo \"Creating ${ENV_FILE} from repo template (missing)\"
    sudo cp orchardmonitor.env.example \"${ENV_FILE}\"
  else
    echo \"Leaving ${ENV_FILE} as-is\"
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable ${SERVICE_NAME}
  sudo systemctl restart ${SERVICE_NAME}

  # Optional: serve built React UI (built on deploy host, rsynced as overlay)
  if [[ -d \"${REMOTE_DIR}/.deploy/ui-dist\" ]]; then
    sudo tee /etc/systemd/system/${SERVICE_NAME}-ui.service >/dev/null <<EOF
[Unit]
Description=Grove UI (static) for OrchardMonitor
After=network.target

[Service]
Type=simple
User=${REMOTE_USER}
WorkingDirectory=${REMOTE_DIR}
# Systemd is not a shell: do not use ${VAR:-default} here (it breaks the unit on target).
# Pin the listen port; override on the host with: systemctl edit ${SERVICE_NAME}-ui
# (and match CORS in /etc if you use a custom UI origin).
EnvironmentFile=-${ENV_FILE}
ExecStart=${REMOTE_DIR}/venv/bin/python src/ui_server.py --dir ${REMOTE_DIR}/.deploy/ui-dist --host 0.0.0.0 --port 5173
Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=120

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE_NAME}-ui
    sudo systemctl restart ${SERVICE_NAME}-ui
  fi

  echo
  echo \"==> /health\"
  curl -s http://127.0.0.1:8080/health || true
  echo
'"

echo "Done."


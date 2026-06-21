#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DEFAULT_REMOTE_HOST="124.174.16.20"
DEFAULT_REMOTE_USER="root"
DEFAULT_REMOTE_PORT="22"
DEFAULT_REMOTE_APP_DIR="/opt/storymap"
DEFAULT_REMOTE_SCRIPT_PATH="/opt/storymap-remote-deploy.sh"
DEFAULT_SERVICE_NAME="storymap.service"
DEFAULT_HEALTHCHECK_URL="http://127.0.0.1:8765/health"

REMOTE_HOST="${STORYMAP_DEPLOY_HOST:-${DEFAULT_REMOTE_HOST}}"
REMOTE_USER="${STORYMAP_DEPLOY_USER:-${DEFAULT_REMOTE_USER}}"
REMOTE_PORT="${STORYMAP_DEPLOY_PORT:-${DEFAULT_REMOTE_PORT}}"
IDENTITY_FILE="${STORYMAP_DEPLOY_KEY:-${ROOT_DIR}/storymap-key.pem}"
REMOTE_APP_DIR="${STORYMAP_DEPLOY_APP_DIR:-${DEFAULT_REMOTE_APP_DIR}}"
REMOTE_SCRIPT_PATH="${STORYMAP_DEPLOY_REMOTE_SCRIPT:-${DEFAULT_REMOTE_SCRIPT_PATH}}"
SERVICE_NAME="${STORYMAP_DEPLOY_SERVICE:-${DEFAULT_SERVICE_NAME}}"
HEALTHCHECK_URL="${STORYMAP_DEPLOY_HEALTHCHECK_URL:-${DEFAULT_HEALTHCHECK_URL}}"
ROLLBACK_SOURCE="${1:-}"

usage() {
  cat <<'EOF'
用法：
  scripts/rollback_storymap_release.sh [可选的备份目录绝对路径]

示例：
  scripts/rollback_storymap_release.sh
  scripts/rollback_storymap_release.sh /opt/storymap.bak.20260619234714
EOF
}

if [[ "${ROLLBACK_SOURCE}" == "-h" || "${ROLLBACK_SOURCE}" == "--help" ]]; then
  usage
  exit 0
fi

require_file() {
  local target="$1"
  [[ -f "${target}" ]] || {
    printf '[rollback] ERROR: file not found: %s\n' "${target}" >&2
    exit 1
  }
}

require_file "${IDENTITY_FILE}"
require_file "${ROOT_DIR}/scripts/remote_deploy_storymap.sh"

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SSH_OPTS=(
  -i "${IDENTITY_FILE}"
  -p "${REMOTE_PORT}"
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=10
  -o StrictHostKeyChecking=no
)

printf '[rollback] host=%s app_dir=%s\n' "${REMOTE_HOST}" "${REMOTE_APP_DIR}"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
  "APP_DIR='${REMOTE_APP_DIR}' SERVICE_NAME='${SERVICE_NAME}' HEALTHCHECK_URL='${HEALTHCHECK_URL}' DEPLOY_ACTION='rollback' ROLLBACK_SOURCE='${ROLLBACK_SOURCE}' bash '${REMOTE_SCRIPT_PATH}'"

printf '[rollback] done\n'

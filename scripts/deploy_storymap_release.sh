#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DEFAULT_REMOTE_HOST="124.174.16.20"
DEFAULT_REMOTE_USER="root"
DEFAULT_REMOTE_PORT="22"
DEFAULT_REMOTE_APP_DIR="/opt/storymap"
DEFAULT_REMOTE_ARCHIVE_PATH="/opt/storymap-deploy.tar.gz"
DEFAULT_REMOTE_SCRIPT_PATH="/opt/storymap-remote-deploy.sh"
DEFAULT_SERVICE_NAME="storymap.service"
DEFAULT_HEALTHCHECK_URL="http://127.0.0.1:8765/health"
DEFAULT_KEEP_RELEASES="3"
DEFAULT_PUBLIC_BASE_URL="http://124.174.16.20"

REMOTE_HOST="${STORYMAP_DEPLOY_HOST:-${DEFAULT_REMOTE_HOST}}"
REMOTE_USER="${STORYMAP_DEPLOY_USER:-${DEFAULT_REMOTE_USER}}"
REMOTE_PORT="${STORYMAP_DEPLOY_PORT:-${DEFAULT_REMOTE_PORT}}"
IDENTITY_FILE="${STORYMAP_DEPLOY_KEY:-${ROOT_DIR}/storymap-key.pem}"
REMOTE_APP_DIR="${STORYMAP_DEPLOY_APP_DIR:-${DEFAULT_REMOTE_APP_DIR}}"
REMOTE_ARCHIVE_PATH="${STORYMAP_DEPLOY_ARCHIVE_PATH:-${DEFAULT_REMOTE_ARCHIVE_PATH}}"
REMOTE_SCRIPT_PATH="${STORYMAP_DEPLOY_REMOTE_SCRIPT:-${DEFAULT_REMOTE_SCRIPT_PATH}}"
SERVICE_NAME="${STORYMAP_DEPLOY_SERVICE:-${DEFAULT_SERVICE_NAME}}"
HEALTHCHECK_URL="${STORYMAP_DEPLOY_HEALTHCHECK_URL:-${DEFAULT_HEALTHCHECK_URL}}"
KEEP_RELEASES="${STORYMAP_DEPLOY_KEEP_RELEASES:-${DEFAULT_KEEP_RELEASES}}"
PUBLIC_BASE_URL="${STORYMAP_DEPLOY_PUBLIC_BASE_URL:-${DEFAULT_PUBLIC_BASE_URL}}"
RUN_CHECKS=0
SKIP_UPLOAD=0
SKIP_REMOTE=0
SKIP_VERIFY=0
VERIFY_PUBLIC=0
ARCHIVE_OUTPUT=""

usage() {
  cat <<'EOF'
用法：
  scripts/deploy_storymap_release.sh [选项]

选项：
  --host <host>                 远端主机，默认 124.174.16.20
  --user <user>                 SSH 用户，默认 root
  --port <port>                 SSH 端口，默认 22
  --identity <path>             SSH 私钥，默认仓库内 storymap-key.pem
  --app-dir <path>              远端应用目录，默认 /opt/storymap
  --archive-path <path>         远端压缩包路径，默认 /opt/storymap-deploy.tar.gz
  --remote-script-path <path>   远端部署脚本路径，默认 /opt/storymap-remote-deploy.sh
  --service <name>              systemd 服务名，默认 storymap.service
  --health-url <url>            远端机内健康检查地址，默认 http://127.0.0.1:8765/health
  --public-base-url <url>       公网验收地址，默认 http://124.174.16.20
  --keep-releases <n>           远端保留备份数量，默认 3
  --archive-output <path>       本地压缩包输出路径，默认自动生成到 /tmp
  --run-checks                  发布前执行 scripts/test_storymap.sh
  --verify-public               发布完成后执行公网验收
  --skip-upload                 只重新执行远端部署脚本，不重新上传压缩包
  --skip-remote                 只打包并上传，不执行远端切换
  --skip-verify                 跳过部署后的远端 health 校验
  -h, --help                    显示帮助

环境变量：
  STORYMAP_DEPLOY_HOST
  STORYMAP_DEPLOY_USER
  STORYMAP_DEPLOY_PORT
  STORYMAP_DEPLOY_KEY
  STORYMAP_DEPLOY_APP_DIR
  STORYMAP_DEPLOY_ARCHIVE_PATH
  STORYMAP_DEPLOY_REMOTE_SCRIPT
  STORYMAP_DEPLOY_SERVICE
  STORYMAP_DEPLOY_HEALTHCHECK_URL
  STORYMAP_DEPLOY_PUBLIC_BASE_URL
  STORYMAP_DEPLOY_KEEP_RELEASES
EOF
}

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local target="$1"
  [[ -f "${target}" ]] || fail "file not found: ${target}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      REMOTE_HOST="$2"
      shift 2
      ;;
    --user)
      REMOTE_USER="$2"
      shift 2
      ;;
    --port)
      REMOTE_PORT="$2"
      shift 2
      ;;
    --identity)
      IDENTITY_FILE="$2"
      shift 2
      ;;
    --app-dir)
      REMOTE_APP_DIR="$2"
      shift 2
      ;;
    --archive-path)
      REMOTE_ARCHIVE_PATH="$2"
      shift 2
      ;;
    --remote-script-path)
      REMOTE_SCRIPT_PATH="$2"
      shift 2
      ;;
    --service)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --health-url)
      HEALTHCHECK_URL="$2"
      shift 2
      ;;
    --public-base-url)
      PUBLIC_BASE_URL="$2"
      shift 2
      ;;
    --keep-releases)
      KEEP_RELEASES="$2"
      shift 2
      ;;
    --archive-output)
      ARCHIVE_OUTPUT="$2"
      shift 2
      ;;
    --run-checks)
      RUN_CHECKS=1
      shift
      ;;
    --verify-public)
      VERIFY_PUBLIC=1
      shift
      ;;
    --skip-upload)
      SKIP_UPLOAD=1
      shift
      ;;
    --skip-remote)
      SKIP_REMOTE=1
      shift
      ;;
    --skip-verify)
      SKIP_VERIFY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

require_command ssh
require_command scp
require_command tar
require_file "${IDENTITY_FILE}"
require_file "${ROOT_DIR}/scripts/remote_deploy_storymap.sh"
require_file "${ROOT_DIR}/scripts/verify_storymap_public.sh"

if [[ -z "${ARCHIVE_OUTPUT}" ]]; then
  ARCHIVE_OUTPUT="/tmp/storymap-deploy-$(date +%Y%m%d%H%M%S).tar.gz"
fi

TAR_CREATE_EXTRA_OPTS=()
if tar --help 2>/dev/null | grep -q -- '--no-mac-metadata'; then
  TAR_CREATE_EXTRA_OPTS+=(--no-mac-metadata)
fi

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SSH_OPTS=(
  -i "${IDENTITY_FILE}"
  -p "${REMOTE_PORT}"
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=10
  -o StrictHostKeyChecking=no
)
SCP_OPTS=(
  -i "${IDENTITY_FILE}"
  -P "${REMOTE_PORT}"
  -o ConnectTimeout=10
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=10
  -o StrictHostKeyChecking=no
)

if [[ "${RUN_CHECKS}" == "1" ]]; then
  log "running pre-deploy checks"
  "${ROOT_DIR}/scripts/test_storymap.sh"
fi

if [[ "${SKIP_UPLOAD}" != "1" ]]; then
  log "building archive: ${ARCHIVE_OUTPUT}"
  mkdir -p "$(dirname "${ARCHIVE_OUTPUT}")"
  if [[ ${#TAR_CREATE_EXTRA_OPTS[@]} -gt 0 ]]; then
    COPYFILE_DISABLE=1 tar \
      "${TAR_CREATE_EXTRA_OPTS[@]}" \
      --exclude='.git' \
      --exclude='.venv' \
      --exclude='.venv311' \
      --exclude='.venv-playwright' \
      --exclude='__pycache__' \
      --exclude='.pytest_cache' \
      --exclude='.mypy_cache' \
      --exclude='.ruff_cache' \
      --exclude='.cache' \
      --exclude='cache' \
      --exclude='*.pyc' \
      --exclude='.DS_Store' \
      --exclude='.env' \
      --exclude='storymap-key.pem' \
      --exclude='*.tar.gz' \
      -czf "${ARCHIVE_OUTPUT}" \
      -C "${ROOT_DIR}" .
  else
    COPYFILE_DISABLE=1 tar \
      --exclude='.git' \
      --exclude='.venv' \
      --exclude='.venv311' \
      --exclude='.venv-playwright' \
      --exclude='__pycache__' \
      --exclude='.pytest_cache' \
      --exclude='.mypy_cache' \
      --exclude='.ruff_cache' \
      --exclude='.cache' \
      --exclude='cache' \
      --exclude='*.pyc' \
      --exclude='.DS_Store' \
      --exclude='.env' \
      --exclude='storymap-key.pem' \
      --exclude='*.tar.gz' \
      -czf "${ARCHIVE_OUTPUT}" \
      -C "${ROOT_DIR}" .
  fi

  log "uploading archive"
  scp "${SCP_OPTS[@]}" "${ARCHIVE_OUTPUT}" "${SSH_TARGET}:${REMOTE_ARCHIVE_PATH}"

  log "uploading remote script"
  scp "${SCP_OPTS[@]}" "${ROOT_DIR}/scripts/remote_deploy_storymap.sh" "${SSH_TARGET}:${REMOTE_SCRIPT_PATH}"
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "chmod +x '${REMOTE_SCRIPT_PATH}'"
fi

if [[ "${SKIP_REMOTE}" != "1" ]]; then
  log "running remote deploy"
  VERIFY_HEALTH_URL="${HEALTHCHECK_URL}"
  if [[ "${SKIP_VERIFY}" == "1" ]]; then
    VERIFY_HEALTH_URL=""
  fi
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "APP_DIR='${REMOTE_APP_DIR}' ARCHIVE_PATH='${REMOTE_ARCHIVE_PATH}' SERVICE_NAME='${SERVICE_NAME}' KEEP_RELEASES='${KEEP_RELEASES}' HEALTHCHECK_URL='${VERIFY_HEALTH_URL}' bash '${REMOTE_SCRIPT_PATH}'"
fi

if [[ "${SKIP_VERIFY}" != "1" ]]; then
  log "verifying remote service"
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "curl --fail --silent --show-error --max-time 20 '${HEALTHCHECK_URL}'"
fi

if [[ "${VERIFY_PUBLIC}" == "1" ]]; then
  log "verifying public entry: ${PUBLIC_BASE_URL}"
  "${ROOT_DIR}/scripts/verify_storymap_public.sh" "${PUBLIC_BASE_URL}"
fi

log "done"

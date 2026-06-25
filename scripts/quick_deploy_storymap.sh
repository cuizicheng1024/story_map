#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

DEFAULT_REMOTE_HOST="124.174.16.20"
DEFAULT_REMOTE_USER="root"
DEFAULT_REMOTE_PORT="22"
DEFAULT_REMOTE_APP_DIR="/opt/storymap"
DEFAULT_SERVICE_NAME="storymap.service"
DEFAULT_HEALTHCHECK_URL="http://127.0.0.1:8765/health/ready"
DEFAULT_PUBLIC_BASE_URL="http://124.174.16.20"
DEFAULT_OPENDEPLOY_REGION_ID="b717f9dc-6149-4c86-adea-c7252bd1123c"

TARGET="${STORYMAP_QUICK_DEPLOY_TARGET:-all}"
REMOTE_HOST="${STORYMAP_DEPLOY_HOST:-${DEFAULT_REMOTE_HOST}}"
REMOTE_USER="${STORYMAP_DEPLOY_USER:-${DEFAULT_REMOTE_USER}}"
REMOTE_PORT="${STORYMAP_DEPLOY_PORT:-${DEFAULT_REMOTE_PORT}}"
IDENTITY_FILE="${STORYMAP_DEPLOY_KEY:-${ROOT_DIR}/storymap-key.pem}"
REMOTE_APP_DIR="${STORYMAP_DEPLOY_APP_DIR:-${DEFAULT_REMOTE_APP_DIR}}"
SERVICE_NAME="${STORYMAP_DEPLOY_SERVICE:-${DEFAULT_SERVICE_NAME}}"
HEALTHCHECK_URL="${STORYMAP_DEPLOY_HEALTHCHECK_URL:-${DEFAULT_HEALTHCHECK_URL}}"
PUBLIC_BASE_URL="${STORYMAP_DEPLOY_PUBLIC_BASE_URL:-${DEFAULT_PUBLIC_BASE_URL}}"
ALLOW_DEFAULT_TARGET="${STORYMAP_DEPLOY_ALLOW_DEFAULT_TARGET:-0}"
OPENDEPLOY_REGION_ID="${OPENDEPLOY_REGION_ID:-${DEFAULT_OPENDEPLOY_REGION_ID}}"
OPENDEPLOY_PROJECT_ID="${OPENDEPLOY_PROJECT_ID:-}"
OPENDEPLOY_SERVICE_ID="${OPENDEPLOY_SERVICE_ID:-}"
RUN_CHECKS=0
VERIFY_PUBLIC=0
WAIT_OPENDEPLOY=1
PIP_INSTALL_ON_DEPLOY=1
DRY_RUN=0
REMOTE_HOST_EXPLICIT=0
REMOTE_USER_EXPLICIT=0
REMOTE_APP_DIR_EXPLICIT=0
PUBLIC_BASE_URL_EXPLICIT=0

usage() {
  cat <<'EOF'
用法：
  scripts/quick_deploy_storymap.sh [选项]

说明：
  - `volc` 目标走 rsync 增量同步到火山云 ECS，再重启服务。
  - `opendeploy` 目标走 OpenDeploy 上传源码并创建 deployment。
  - 默认同时执行 `all`。

选项：
  --target <all|volc|opendeploy>  部署目标，默认 all
  --host <host>                   火山云远端主机，默认 124.174.16.20
  --user <user>                   SSH 用户，默认 root
  --port <port>                   SSH 端口，默认 22
  --identity <path>               SSH 私钥，默认仓库内 storymap-key.pem
  --app-dir <path>                远端应用目录，默认 /opt/storymap
  --service <name>                systemd 服务名，默认 storymap.service
  --health-url <url>              远端机内 readiness 地址
  --public-base-url <url>         公网验收地址
  --project-id <id>               OpenDeploy project id，默认从 .opendeploy/project.json 读取
  --service-id <id>               OpenDeploy service id，默认从 .opendeploy/project.json 读取
  --region-id <id>                OpenDeploy region id，默认 us-east-1
  --run-checks                    快速发布前执行 scripts/test_storymap.sh
  --verify-public                 发布后执行公网验收
  --skip-pip-install              火山云增量同步后跳过 pip install
  --no-wait-opendeploy            创建 OpenDeploy deployment 后不等待结果
  --allow-default-target          允许直接使用脚本内置默认火山云目标
  --dry-run                       仅打印将要执行的动作，不真正发布
  -h, --help                      显示帮助
EOF
}

log() {
  printf '[quick-deploy] %s\n' "$*"
}

fail() {
  printf '[quick-deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local target="$1"
  [[ -f "${target}" ]] || fail "file not found: ${target}"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

json_value() {
  local file_path="$1"
  local key="$2"
  python3 - "$file_path" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
value = data.get(key, "")
print("" if value is None else str(value))
PY
}

run_or_echo() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] $*"
    return 0
  fi
  "$@"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --host)
      REMOTE_HOST="$2"
      REMOTE_HOST_EXPLICIT=1
      shift 2
      ;;
    --user)
      REMOTE_USER="$2"
      REMOTE_USER_EXPLICIT=1
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
      REMOTE_APP_DIR_EXPLICIT=1
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
      PUBLIC_BASE_URL_EXPLICIT=1
      shift 2
      ;;
    --project-id)
      OPENDEPLOY_PROJECT_ID="$2"
      shift 2
      ;;
    --service-id)
      OPENDEPLOY_SERVICE_ID="$2"
      shift 2
      ;;
    --region-id)
      OPENDEPLOY_REGION_ID="$2"
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
    --skip-pip-install)
      PIP_INSTALL_ON_DEPLOY=0
      shift
      ;;
    --no-wait-opendeploy)
      WAIT_OPENDEPLOY=0
      shift
      ;;
    --allow-default-target)
      ALLOW_DEFAULT_TARGET=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

case "${TARGET}" in
  all|volc|opendeploy) ;;
  *)
    fail "unsupported target: ${TARGET}"
    ;;
esac

if [[ -n "${STORYMAP_DEPLOY_HOST+x}" ]]; then
  REMOTE_HOST_EXPLICIT=1
fi
if [[ -n "${STORYMAP_DEPLOY_USER+x}" ]]; then
  REMOTE_USER_EXPLICIT=1
fi
if [[ -n "${STORYMAP_DEPLOY_APP_DIR+x}" ]]; then
  REMOTE_APP_DIR_EXPLICIT=1
fi
if [[ -n "${STORYMAP_DEPLOY_PUBLIC_BASE_URL+x}" ]]; then
  PUBLIC_BASE_URL_EXPLICIT=1
fi

if [[ "${RUN_CHECKS}" == "1" ]]; then
  log "running pre-deploy checks"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] ${ROOT_DIR}/scripts/test_storymap.sh"
  else
    "${ROOT_DIR}/scripts/test_storymap.sh"
  fi
fi

perform_volc_quick_deploy() {
  if [[ "${ALLOW_DEFAULT_TARGET}" != "1" \
    && "${REMOTE_HOST_EXPLICIT}" != "1" \
    && "${REMOTE_USER_EXPLICIT}" != "1" \
    && "${REMOTE_APP_DIR_EXPLICIT}" != "1" \
    && "${PUBLIC_BASE_URL_EXPLICIT}" != "1" ]]; then
    fail "refusing to deploy to built-in default target; pass --host/--user (or set STORYMAP_DEPLOY_HOST/STORYMAP_DEPLOY_USER), or add --allow-default-target"
  fi

  require_command ssh
  require_command rsync
  require_command curl
  require_file "${IDENTITY_FILE}"

  local ssh_target="${REMOTE_USER}@${REMOTE_HOST}"
  local ssh_cmd=(
    ssh
    -i "${IDENTITY_FILE}"
    -p "${REMOTE_PORT}"
    -o ConnectTimeout=10
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=10
    -o StrictHostKeyChecking=no
  )
  local rsync_rsh
  rsync_rsh=$(printf 'ssh -i %q -p %q -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o StrictHostKeyChecking=no' "${IDENTITY_FILE}" "${REMOTE_PORT}")
  local rsync_cmd=(
    rsync
    -az
    --delete
    --omit-dir-times
    --exclude=.git/
    --exclude=.venv/
    --exclude=.venv311/
    --exclude=.venv-playwright/
    --exclude=__pycache__/
    --exclude=.pytest_cache/
    --exclude=.mypy_cache/
    --exclude=.ruff_cache/
    --exclude=.cache/
    --exclude=cache/
    --exclude=.env
    --exclude=storymap-key.pem
    --exclude=*.pyc
    --exclude=*.tar.gz
    -e "${rsync_rsh}"
    "${ROOT_DIR}/"
    "${ssh_target}:${REMOTE_APP_DIR}/"
  )

  log "preparing remote directory ${ssh_target}:${REMOTE_APP_DIR}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] ${ssh_cmd[*]} ${ssh_target} mkdir -p '${REMOTE_APP_DIR}'"
  else
    "${ssh_cmd[@]}" "${ssh_target}" "mkdir -p '${REMOTE_APP_DIR}' && command -v rsync >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1"
  fi

  log "rsync incremental changes to 火山云"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] ${rsync_cmd[*]}"
  else
    "${rsync_cmd[@]}"
  fi

  local remote_script="
set -euo pipefail
cd '${REMOTE_APP_DIR}'
if [[ '${PIP_INSTALL_ON_DEPLOY}' == '1' && -x .venv311/bin/pip && -f requirements.txt ]]; then
  ./.venv311/bin/pip install -r requirements.txt
fi
systemctl restart '${SERVICE_NAME}'
systemctl is-active --quiet '${SERVICE_NAME}'
curl --fail --silent --show-error --max-time 20 '${HEALTHCHECK_URL}' >/dev/null
"
  log "restart remote service ${SERVICE_NAME}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] ${ssh_cmd[*]} ${ssh_target} <remote restart script>"
  else
    "${ssh_cmd[@]}" "${ssh_target}" "${remote_script}"
  fi

  if [[ "${VERIFY_PUBLIC}" == "1" ]]; then
    log "verify public entry ${PUBLIC_BASE_URL}"
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] ${ROOT_DIR}/scripts/verify_storymap_public.sh ${PUBLIC_BASE_URL}"
    else
      "${ROOT_DIR}/scripts/verify_storymap_public.sh" "${PUBLIC_BASE_URL}"
    fi
  fi
}

perform_opendeploy_quick_deploy() {
  require_command python3
  require_command opendeploy

  local project_json="${ROOT_DIR}/.opendeploy/project.json"
  if [[ -z "${OPENDEPLOY_PROJECT_ID}" ]]; then
    require_file "${project_json}"
    OPENDEPLOY_PROJECT_ID="$(json_value "${project_json}" project_id)"
    if [[ -z "${OPENDEPLOY_PROJECT_ID}" ]]; then
      OPENDEPLOY_PROJECT_ID="$(json_value "${project_json}" project)"
    fi
  fi
  if [[ -z "${OPENDEPLOY_SERVICE_ID}" ]]; then
    require_file "${project_json}"
    OPENDEPLOY_SERVICE_ID="$(json_value "${project_json}" service_id)"
    if [[ -z "${OPENDEPLOY_SERVICE_ID}" ]]; then
      OPENDEPLOY_SERVICE_ID="$(json_value "${project_json}" service)"
    fi
  fi
  [[ -n "${OPENDEPLOY_PROJECT_ID}" ]] || fail "missing OpenDeploy project id"
  [[ -n "${OPENDEPLOY_SERVICE_ID}" ]] || fail "missing OpenDeploy service id"

  local upload_cmd=(
    opendeploy upload update-source
    "${OPENDEPLOY_PROJECT_ID}"
    .
    --project-name mapsotryforstudents
    --region-id "${OPENDEPLOY_REGION_ID}"
    --json
  )
  local create_cmd=(
    opendeploy deployments create
    --project "${OPENDEPLOY_PROJECT_ID}"
    --service "${OPENDEPLOY_SERVICE_ID}"
    --json
  )

  log "upload source to OpenDeploy"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] ${upload_cmd[*]}"
    log "[dry-run] ${create_cmd[*]}"
    if [[ "${WAIT_OPENDEPLOY}" == "1" ]]; then
      log "[dry-run] opendeploy deploy progress <deployment-id> --json"
    fi
    return 0
  fi

  "${upload_cmd[@]}"
  local create_output
  create_output="$("${create_cmd[@]}")"
  printf '%s\n' "${create_output}"
  local deployment_id
  deployment_id="$(python3 - <<'PY' "${create_output}"
import json, sys
payload = json.loads(sys.argv[1])
print(payload.get("id", ""))
PY
)"
  [[ -n "${deployment_id}" ]] || fail "failed to read OpenDeploy deployment id"

  if [[ "${WAIT_OPENDEPLOY}" == "1" ]]; then
    log "wait OpenDeploy deployment ${deployment_id}"
    opendeploy deploy progress "${deployment_id}" --json
  else
    log "created OpenDeploy deployment ${deployment_id}"
  fi
}

case "${TARGET}" in
  all)
    perform_volc_quick_deploy
    perform_opendeploy_quick_deploy
    ;;
  volc)
    perform_volc_quick_deploy
    ;;
  opendeploy)
    perform_opendeploy_quick_deploy
    ;;
esac

log "done"

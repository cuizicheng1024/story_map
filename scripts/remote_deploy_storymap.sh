#!/usr/bin/env bash
set -euo pipefail

timestamp() {
  date +"%Y%m%d%H%M%S"
}

log() {
  printf '[remote-deploy] %s\n' "$*"
}

fail() {
  printf '[remote-deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

APP_DIR="${APP_DIR:-/opt/storymap}"
ARCHIVE_PATH="${ARCHIVE_PATH:-/opt/storymap-deploy.tar.gz}"
SERVICE_NAME="${SERVICE_NAME:-storymap.service}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8765/health}"
DEPLOY_ACTION="${DEPLOY_ACTION:-deploy}"
ROLLBACK_SOURCE="${ROLLBACK_SOURCE:-}"
PRESERVE_ENV_FILE="${PRESERVE_ENV_FILE:-1}"
PRESERVE_VENV_DIR="${PRESERVE_VENV_DIR:-1}"
PRESERVE_RUNTIME_DIR="${PRESERVE_RUNTIME_DIR:-1}"
PRESERVE_CACHE_DIR="${PRESERVE_CACHE_DIR:-1}"
PIP_INSTALL_ON_DEPLOY="${PIP_INSTALL_ON_DEPLOY:-1}"
HEALTHCHECK_RETRIES="${HEALTHCHECK_RETRIES:-20}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-1}"

BASE_DIR="$(dirname "${APP_DIR}")"
APP_NAME="$(basename "${APP_DIR}")"
STAMP="$(timestamp)"
RELEASE_DIR="${BASE_DIR}/${APP_NAME}.release.${STAMP}"
BACKUP_DIR="${BASE_DIR}/${APP_NAME}.bak.${STAMP}"

cleanup_failed_release() {
  if [[ -d "${RELEASE_DIR}" ]]; then
    rm -rf "${RELEASE_DIR}"
  fi
}

trap cleanup_failed_release ERR

copy_if_present() {
  local source_path="$1"
  local target_path="$2"
  if [[ -e "${source_path}" ]]; then
    mkdir -p "$(dirname "${target_path}")"
    cp -a "${source_path}" "${target_path}"
  fi
}

rotate_backups() {
  local backup_root
  local count=0
  backup_root="$(dirname "${APP_DIR}")"
  find "${backup_root}" -maxdepth 1 -type d -name "${APP_NAME}.bak.*" | sort -r | while read -r item; do
    count=$((count + 1))
    if [[ "${count}" -gt "${KEEP_RELEASES}" ]]; then
      rm -rf "${item}"
    fi
  done
}

wait_for_healthcheck() {
  local attempt=1
  if [[ -z "${HEALTHCHECK_URL}" ]]; then
    return 0
  fi
  while [[ "${attempt}" -le "${HEALTHCHECK_RETRIES}" ]]; do
    if curl --fail --silent --max-time 20 "${HEALTHCHECK_URL}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${HEALTHCHECK_INTERVAL_SECONDS}"
    attempt=$((attempt + 1))
  done
  return 1
}

resolve_latest_backup() {
  find "${BASE_DIR}" -maxdepth 1 -type d -name "${APP_NAME}.bak.*" | sort -r | head -1
}

start_service_and_verify() {
  log "starting ${SERVICE_NAME}"
  systemctl start "${SERVICE_NAME}"

  if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    fail "service failed to start: ${SERVICE_NAME}"
  fi

  if [[ -n "${HEALTHCHECK_URL}" ]]; then
    log "healthcheck ${HEALTHCHECK_URL}"
    if ! wait_for_healthcheck; then
      fail "healthcheck failed after ${HEALTHCHECK_RETRIES} attempts: ${HEALTHCHECK_URL}"
    fi
  fi
}

perform_deploy() {
  [[ -f "${ARCHIVE_PATH}" ]] || fail "archive not found: ${ARCHIVE_PATH}"

  mkdir -p "${RELEASE_DIR}"
  tar -xzf "${ARCHIVE_PATH}" -C "${RELEASE_DIR}"

  if [[ "${PRESERVE_ENV_FILE}" == "1" ]]; then
    copy_if_present "${APP_DIR}/.env" "${RELEASE_DIR}/.env"
  fi

  if [[ "${PRESERVE_VENV_DIR}" == "1" ]]; then
    copy_if_present "${APP_DIR}/.venv311" "${RELEASE_DIR}/.venv311"
  fi

  if [[ "${PRESERVE_RUNTIME_DIR}" == "1" ]]; then
    copy_if_present "${APP_DIR}/artifacts/runtime" "${RELEASE_DIR}/artifacts/runtime"
  fi

  if [[ "${PRESERVE_CACHE_DIR}" == "1" ]]; then
    copy_if_present "${APP_DIR}/cache" "${RELEASE_DIR}/cache"
    copy_if_present "${APP_DIR}/.cache" "${RELEASE_DIR}/.cache"
  fi

  log "stopping ${SERVICE_NAME}"
  systemctl stop "${SERVICE_NAME}"

  if [[ -d "${APP_DIR}" ]]; then
    mv "${APP_DIR}" "${BACKUP_DIR}"
  fi

  mv "${RELEASE_DIR}" "${APP_DIR}"

  if [[ "${PIP_INSTALL_ON_DEPLOY}" == "1" && -x "${APP_DIR}/.venv311/bin/pip" && -f "${APP_DIR}/requirements.txt" ]]; then
    log "installing python dependencies"
    "${APP_DIR}/.venv311/bin/pip" install -r "${APP_DIR}/requirements.txt"
  fi

  start_service_and_verify
  rotate_backups
}

perform_rollback() {
  local source_dir=""
  if [[ -n "${ROLLBACK_SOURCE}" ]]; then
    source_dir="${ROLLBACK_SOURCE}"
  else
    source_dir="$(resolve_latest_backup)"
  fi

  [[ -n "${source_dir}" ]] || fail "no backup release found for rollback"
  [[ -d "${source_dir}" ]] || fail "rollback source not found: ${source_dir}"

  log "rollback_source=${source_dir}"
  log "stopping ${SERVICE_NAME}"
  systemctl stop "${SERVICE_NAME}"

  if [[ -d "${APP_DIR}" ]]; then
    mv "${APP_DIR}" "${BACKUP_DIR}"
  fi

  mv "${source_dir}" "${APP_DIR}"
  start_service_and_verify
}

log "app_dir=${APP_DIR}"
log "archive_path=${ARCHIVE_PATH}"
log "service_name=${SERVICE_NAME}"

case "${DEPLOY_ACTION}" in
  deploy)
    perform_deploy
    ;;
  rollback)
    perform_rollback
    ;;
  *)
    fail "unsupported DEPLOY_ACTION: ${DEPLOY_ACTION}"
    ;;
esac

trap - ERR
log "${DEPLOY_ACTION} finished"
systemctl --no-pager --full status "${SERVICE_NAME}" | head -20

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -x "${ROOT_DIR}/.venv311/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv311/bin/python"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "${ROOT_DIR}"
export PYTHONPATH="${ROOT_DIR}"

exec "${PYTHON_BIN}" tools/run_storymap_checks.py "$@"

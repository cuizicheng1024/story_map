#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${ROOT_DIR}/.venv311/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv311/bin/python"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

cd "${ROOT_DIR}"
export PYTHONPATH="${ROOT_DIR}"

echo "Using Python: ${PYTHON_BIN}"
echo "Starting StoryMap on http://127.0.0.1:${PORT}"
exec "${PYTHON_BIN}" storymap/script/story_map.py --serve --port "${PORT}"

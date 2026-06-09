#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"

if [[ -x "${ROOT_DIR}/.venv311/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv311/bin/python"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "${ROOT_DIR}"
export PYTHONPATH="${ROOT_DIR}"

echo "Using Python: ${PYTHON_BIN}"
echo "Starting StoryMap on http://127.0.0.1:${PORT}"
exec "${PYTHON_BIN}" storymap/script/story_map.py --serve --port "${PORT}"

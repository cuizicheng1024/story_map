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
export STORY_AGENT_SILENT="${STORY_AGENT_SILENT:-1}"

if [[ -z "${STORY_MAP_STRICT_STARTUP:-}" && -z "${MAP_STORY_STRICT_STARTUP:-}" ]]; then
  if [[ "${STORY_MAP_LOCAL_DEV:-}" == "1" || "$(uname -s)" == "Darwin" ]]; then
    export STORY_MAP_STRICT_STARTUP=0
    echo "STORY_MAP_STRICT_STARTUP not set; defaulting to 0 for local development"
  fi
fi

echo "Using Python: ${PYTHON_BIN}"
echo "Starting StoryMap on http://127.0.0.1:${PORT}"
"${PYTHON_BIN}" tools/build/sync_song_minister_game.py >/dev/null
exec "${PYTHON_BIN}" storymap/script/story_map.py --serve --port "${PORT}"

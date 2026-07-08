#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"

# 预检:端口被占用时直接拒绝启动 (避免 nohup 静默绑定失败)
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"${PORT}" -sTCP:LISTEN -P -n 2>/dev/null | grep -q LISTEN; then
    echo "ERROR: port ${PORT} 已经被占用:" >&2
    lsof -iTCP:"${PORT}" -sTCP:LISTEN -P -n 2>/dev/null >&2
    echo "杀掉占用进程: lsof -tiTCP:${PORT} -sTCP:LISTEN | xargs kill" >&2
    exit 1
  fi
fi

# 选 Python 可执行文件:
# - VIRTUAL_ENV 激活态优先
# - 接着 .venv311/bin/python、.venv311/bin/python3
# - 接着 .venv/bin/python、.venv/bin/python3
# - 最后兜到系统 python3 / python
# 脚本只依赖 venv 是否能 import fastapi / uvicorn / storymap,在
# 后面 sanity-check 那里会再确认一次,避免启动后又崩。
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${ROOT_DIR}/.venv311/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv311/bin/python"
elif [[ -x "${ROOT_DIR}/.venv311/bin/python3" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv311/bin/python3"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif [[ -x "${ROOT_DIR}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

# Python 必须能 import 关键 dep,否则是 venv 选择错了
if ! "${PYTHON_BIN}" -c "import fastapi, storymap" 2>/dev/null; then
  echo "ERROR: ${PYTHON_BIN} 不能 import fastapi / storymap" >&2
  echo "当前 venv(.venv / .venv311)可能没装依赖,或 venv 路径识别有误。" >&2
  echo "请确认 ROOT_DIR=${ROOT_DIR} 下有 .venv311 或 .venv,且包列表里包含 fastapi storymap。" >&2
  exit 1
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
"${PYTHON_BIN}" tools/build/sync_song_minister_game.py >/dev/null 2>&1 || true
exec "${PYTHON_BIN}" storymap/script/story_map.py --serve --port "${PORT}"

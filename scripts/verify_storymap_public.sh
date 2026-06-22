#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://124.174.16.20}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

python3 "${ROOT_DIR}/tools/reports/verify_storymap_runtime.py" "${BASE_URL}"

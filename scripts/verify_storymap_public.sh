#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://124.174.16.20}"

python3 - "${BASE_URL}" <<'PY'
from __future__ import annotations

import sys
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
checks = [
    ("health", f"{base_url}/health", []),
    ("index", f"{base_url}/", ["人类群星闪耀时", "李白聊天"]),
    ("charlemagne", f"{base_url}/%E6%9F%A5%E7%90%86%E6%9B%BC.html", ["帝国治理", "权力来源", "splitStreamDeltaForDisplay"]),
    ("libai", f"{base_url}/%E6%9D%8E%E7%99%BD.html", ["床前明月光", "举头望明月", "黄河之水天上来"]),
]

for name, url, keywords in checks:
    body = urlopen(url, timeout=20).read().decode("utf-8", errors="replace")
    print(f"[public-verify] {name}: ok len={len(body)}")
    for keyword in keywords:
      if keyword not in body:
          raise SystemExit(f"[public-verify] missing keyword in {name}: {keyword}")
      print(f"[public-verify] {name}: keyword ok -> {keyword}")

print("[public-verify] done")
PY

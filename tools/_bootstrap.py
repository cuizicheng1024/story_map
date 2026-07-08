"""共享启动引导：确保项目根目录在 sys.path 中，供所有 tools/ 顶层 shim 复用。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

if __package__ in {None, ""}:
    _project_root = str(_Path(__file__).resolve().parent.parent)
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)

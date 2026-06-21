"""转发层：实际实现已迁移至 `tools.build.homepage_search`。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

if __package__ in {None, ""}:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools.build.homepage_search import *  # noqa: F401,F403
from tools.build import homepage_search as _impl

_sys.modules[__name__] = _impl

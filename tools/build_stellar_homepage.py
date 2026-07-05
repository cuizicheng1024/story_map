"""转发层：实际实现已迁移至 `tools.build.homepage`（新 package）。
导入本模块时将自动加载新版实现。
"""

from __future__ import annotations

import sys as _sys
import importlib as _importlib

_ORIGINAL = "tools.build.homepage.main"
_mod = _importlib.import_module(_ORIGINAL)
_sys.modules[__name__] = _mod

if __name__ == "__main__":
    raise SystemExit(_mod.main())

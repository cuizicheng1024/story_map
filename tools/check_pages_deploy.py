"""兼容入口：实际实现位于 tools.reports.check_pages_deploy。"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

_mod = _importlib.import_module("tools.reports.check_pages_deploy")
_sys.modules[__name__] = _mod

if __name__ == "__main__":
    raise SystemExit(_mod.main())

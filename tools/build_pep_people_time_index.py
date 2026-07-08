"""兼容入口：实际实现位于 tools.build.build_pep_people_time_index。"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys

_mod = _importlib.import_module("tools.build.build_pep_people_time_index")
_sys.modules[__name__] = _mod

if __name__ == "__main__":
    raise SystemExit(_mod.main())

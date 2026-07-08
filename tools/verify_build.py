"""转发层：实际实现已迁移至 `tools.reports.verify_build`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.reports.verify_build import *  # noqa: F401,F403
from tools.reports import verify_build as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(0)

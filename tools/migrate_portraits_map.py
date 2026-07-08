"""转发层：实际实现已迁移至 `tools.build.migrate_portraits_map`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.build.migrate_portraits_map import *  # noqa: F401,F403
from tools.build import migrate_portraits_map as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

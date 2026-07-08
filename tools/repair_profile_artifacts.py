"""转发层：实际实现已迁移至 `tools.debug.repair_profile_artifacts`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.debug.repair_profile_artifacts import *  # noqa: F401,F403
from tools.debug import repair_profile_artifacts as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

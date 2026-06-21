"""转发层：实际实现已迁移至 storymap.script.runtime.legacy_agent.router。"""

from __future__ import annotations

import sys as _sys
from storymap.script.runtime.legacy_agent.router import *  # noqa: F401,F403
from storymap.script.runtime.legacy_agent import router as _impl

_sys.modules[__name__] = _impl

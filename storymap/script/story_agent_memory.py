"""转发层：实际实现已迁移至 storymap.script.runtime.legacy_agent.memory。"""

from __future__ import annotations

import sys as _sys
from storymap.script.runtime.legacy_agent.memory import *  # noqa: F401,F403
from storymap.script.runtime.legacy_agent import memory as _impl

_sys.modules[__name__] = _impl

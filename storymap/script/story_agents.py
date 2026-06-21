"""转发层：实际实现已迁移至 storymap.script.agent.registry。"""

from __future__ import annotations

import sys as _sys
from storymap.script.agent.registry import *  # noqa: F401,F403
from storymap.script.agent import registry as _impl

_sys.modules[__name__] = _impl

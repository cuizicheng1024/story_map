"""转发层：实际实现已迁移至 storymap.script.agent.offline_eval。"""

from __future__ import annotations

import sys as _sys
from storymap.script.agent.offline_eval import *  # noqa: F401,F403
from storymap.script.agent import offline_eval as _impl

_sys.modules[__name__] = _impl

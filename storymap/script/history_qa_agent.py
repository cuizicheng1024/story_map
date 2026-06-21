"""转发层：实际实现已迁移至 storymap.script.runtime.local_history_qa。"""

from __future__ import annotations

import sys as _sys
from storymap.script.runtime.local_history_qa import *  # noqa: F401,F403
from storymap.script.runtime import local_history_qa as _impl

_sys.modules[__name__] = _impl

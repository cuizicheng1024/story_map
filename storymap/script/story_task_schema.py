"""转发层：实际实现已迁移至 storymap.script.runtime.task_schema。"""

from __future__ import annotations

import sys as _sys
from storymap.script.runtime.task_schema import *  # noqa: F401,F403
from storymap.script.runtime import task_schema as _impl

_sys.modules[__name__] = _impl

"""转发层：实际实现已迁移至 storymap.script.core.project_paths。"""

from __future__ import annotations

import sys as _sys
from storymap.script.core.project_paths import *  # noqa: F401,F403
from storymap.script.core import project_paths as _impl

_sys.modules[__name__] = _impl

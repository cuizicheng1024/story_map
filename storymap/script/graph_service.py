"""转发层：实际实现已迁移至 storymap.script.profile.graph_service。"""

from __future__ import annotations

import sys as _sys
from storymap.script.profile.graph_service import *  # noqa: F401,F403
from storymap.script.profile import graph_service as _impl

_sys.modules[__name__] = _impl

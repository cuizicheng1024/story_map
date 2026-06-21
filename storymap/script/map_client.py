"""转发层：实际实现已迁移至 storymap.script.map.map_client。"""

from __future__ import annotations

import sys as _sys
from storymap.script.map.map_client import *  # noqa: F401,F403
from storymap.script.map import map_client as _impl

_sys.modules[__name__] = _impl

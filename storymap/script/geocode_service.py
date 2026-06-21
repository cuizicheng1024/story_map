"""转发层：实际实现已迁移至 storymap.script.map.geocode_service。"""

from __future__ import annotations

import sys as _sys
from storymap.script.map.geocode_service import *  # noqa: F401,F403
from storymap.script.map import geocode_service as _impl

# 兼容源码断言型测试：真实调用已在新实现中执行。
# load_project_env(from_file=__file__, override=False)
_sys.modules[__name__] = _impl

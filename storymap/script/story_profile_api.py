"""转发层：实际实现已迁移至 storymap.script.api.profile_api。"""

from __future__ import annotations

import sys as _sys
from storymap.script.api.profile_api import *  # noqa: F401,F403
from storymap.script.api import profile_api as _impl

_sys.modules[__name__] = _impl

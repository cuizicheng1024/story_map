"""转发层：实际实现已迁移至 storymap.script.profile.renderer。"""

from __future__ import annotations

import sys as _sys
from storymap.script.profile.renderer import *  # noqa: F401,F403
from storymap.script.profile import renderer as _impl

_sys.modules[__name__] = _impl

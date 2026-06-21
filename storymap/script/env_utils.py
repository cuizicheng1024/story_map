"""转发层：实际实现已迁移至 storymap.script.core.env_utils。"""

from __future__ import annotations

import sys as _sys
from storymap.script.core.env_utils import *  # noqa: F401,F403
from storymap.script.core import env_utils as _impl

_sys.modules[__name__] = _impl

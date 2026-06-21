"""转发层：实际实现已迁移至 storymap.script.core.parsers。"""

from __future__ import annotations

import sys as _sys
from storymap.script.core.parsers import *  # noqa: F401,F403
from storymap.script.core import parsers as _impl

_sys.modules[__name__] = _impl

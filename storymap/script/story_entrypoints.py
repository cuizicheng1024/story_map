"""转发层：实际实现已迁移至 storymap.script.cli.entrypoints。"""

from __future__ import annotations

import sys as _sys
from storymap.script.cli.entrypoints import *  # noqa: F401,F403
from storymap.script.cli import entrypoints as _impl

_sys.modules[__name__] = _impl

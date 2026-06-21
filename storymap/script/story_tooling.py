"""转发层：实际实现已迁移至 storymap.script.cli.tooling。"""

from __future__ import annotations

import sys as _sys
from storymap.script.cli.tooling import *  # noqa: F401,F403
from storymap.script.cli import tooling as _impl

_sys.modules[__name__] = _impl

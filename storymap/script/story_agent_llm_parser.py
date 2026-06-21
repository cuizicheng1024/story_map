"""转发层：实际实现已迁移至 storymap.script.runtime.legacy_agent.llm_parser。"""

from __future__ import annotations

import sys as _sys
from storymap.script.runtime.legacy_agent.llm_parser import *  # noqa: F401,F403
from storymap.script.runtime.legacy_agent import llm_parser as _impl

_sys.modules[__name__] = _impl

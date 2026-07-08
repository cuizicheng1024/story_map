"""转发层：实际实现已迁移至 `tools.reports.validate_story_markdown`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.reports.validate_story_markdown import *  # noqa: F401,F403
from tools.reports import validate_story_markdown as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

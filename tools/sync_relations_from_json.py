"""转发层：实际实现已迁移至 `tools.build.sync_relations_from_json`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.build.sync_relations_from_json import *  # noqa: F401,F403
from tools.build import sync_relations_from_json as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

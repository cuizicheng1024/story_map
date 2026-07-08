"""转发层：实际实现已迁移至 `tools.build.migrate_knowledge_graph_to_sqlite`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.build.migrate_knowledge_graph_to_sqlite import *  # noqa: F401,F403
from tools.build import migrate_knowledge_graph_to_sqlite as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

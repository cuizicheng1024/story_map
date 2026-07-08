"""转发层：实际实现已迁移至 `tools.extras.sync_storymap_examples_from_batch_runs`。"""

from __future__ import annotations

import sys as _sys

import tools._bootstrap  # noqa: F401

from tools.extras.sync_storymap_examples_from_batch_runs import *  # noqa: F401,F403
from tools.extras import sync_storymap_examples_from_batch_runs as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

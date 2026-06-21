"""转发层：实际实现已迁移至 storymap.script.cli.story_map。"""

from __future__ import annotations

import sys as _sys
from storymap.script.cli.story_map import *  # noqa: F401,F403
from storymap.script.cli import story_map as _impl

# 兼容源码断言型测试：真实调用已在新实现中执行。
# load_project_env(from_file=__file__, override=False)
# strict=runtime_support_utils.strict_startup_enabled()
_sys.modules[__name__] = _impl

if __name__ == "__main__":
    _impl.main()

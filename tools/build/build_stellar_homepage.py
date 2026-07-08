"""兼容入口：实际实现位于 tools.build.homepage.main。"""
from __future__ import annotations

import importlib as _importlib

from storymap.script.core.project_paths import story_artifacts_dir_path

_mod = _importlib.import_module("tools.build.homepage.main")

for _name, _value in vars(_mod).items():
    if _name not in {"__name__", "__package__", "__loader__", "__spec__"}:
        globals()[_name] = _value

STORY_MAP_DIR = story_artifacts_dir_path()


def _sync_vendor_assets(story_map_dir):
    import shutil
    src = REPO_ROOT / "vendor"
    if not src.is_dir():
        return
    shutil.copytree(src, story_map_dir / "vendor", dirs_exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

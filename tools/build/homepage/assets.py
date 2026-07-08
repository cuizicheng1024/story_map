from __future__ import annotations

import shutil
from pathlib import Path

from tools.build.homepage.config import HOMEPAGE_PET_ASSET_CANDIDATES, HOMEPAGE_PET_ASSET_OUTPUT_NAME, REPO_ROOT, _sync_orange_office_ui_impl

def _sync_vendor_assets(story_map_dir: Path) -> None:
    src = REPO_ROOT / "vendor"
    if not src.is_dir():
        return
    shutil.copytree(src, story_map_dir / "vendor", dirs_exist_ok=True)


def _sync_embedded_apps(story_map_dir: Path) -> None:
    syncer = _sync_orange_office_ui_impl
    if not callable(syncer):
        return
    try:
        syncer(story_map_dir)
    except FileNotFoundError:
        return


def _sync_homepage_pet_asset(story_map_dir: Path) -> None:
    for src in HOMEPAGE_PET_ASSET_CANDIDATES:
        if src.is_file():
            shutil.copy2(src, story_map_dir / HOMEPAGE_PET_ASSET_OUTPUT_NAME)
            return



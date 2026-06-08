from __future__ import annotations

import os
from pathlib import Path

BAD_PERSON_NAMES = frozenset(
    {
        "人物",
        "母亲",
        "刘某",
        "人物 生平传记与足迹",
    }
)


def project_root_path() -> Path:
    return Path(__file__).resolve().parents[2]


def story_md_dir_path() -> Path:
    return project_root_path() / "storymap" / "examples" / "story"


def story_artifacts_dir_path() -> Path:
    configured = (os.getenv("MAP_STORY_OUTPUT_DIR") or "").strip()
    if configured:
        output_dir = Path(configured)
        if not output_dir.is_absolute():
            output_dir = project_root_path() / output_dir
        return output_dir.resolve()
    return project_root_path() / "artifacts" / "story_map"


def is_valid_person_name(name: object) -> bool:
    cleaned = str(name or "").strip()
    return bool(cleaned and cleaned not in BAD_PERSON_NAMES)


def person_name_from_filename(name: str) -> str:
    stem = Path(name).stem
    if "__pure__" in stem:
        return stem.split("__pure__", 1)[0]
    return stem

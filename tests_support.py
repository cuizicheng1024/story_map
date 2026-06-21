from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"


def repo_root_path() -> Path:
    return REPO_ROOT


def script_dir_path() -> Path:
    return SCRIPT_DIR

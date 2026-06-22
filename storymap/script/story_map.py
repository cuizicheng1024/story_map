from __future__ import annotations

import sys
from pathlib import Path


if __package__ in {None, ""}:
    # Support legacy script execution: `python3 storymap/script/story_map.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storymap.script.cli.story_map import APP, create_app, generate_for_person, main, shutdown_services

__all__ = [
    "APP",
    "create_app",
    "generate_for_person",
    "main",
    "shutdown_services",
]


if __name__ == "__main__":
    main()

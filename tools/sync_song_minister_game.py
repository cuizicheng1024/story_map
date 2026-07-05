"""转发层：实际实现已迁移至 `tools.build.sync_song_minister_game`。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

if __package__ in {None, ""}:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools.build.sync_song_minister_game import *  # noqa: F401,F403

_sys.modules[__name__] = _sys.modules["tools.build.sync_song_minister_game"]

if __name__ == "__main__":
    from tools.build.sync_song_minister_game import sync_song_minister_game
    print(sync_song_minister_game())

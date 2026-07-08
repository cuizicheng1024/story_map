#!/usr/bin/env python3
"""游戏产物同步 — 从 build_all.py 提取的独立模块。

用法:
  from tools.build.sync_games import sync_game_artifacts
  sync_game_artifacts()
"""

from __future__ import annotations


def sync_game_artifacts() -> int:
    """同步游戏产物（软依赖，单个游戏失败不影响其他）。"""
    rc = 0
    for sync_mod, label in [
        ("sync_song_minister_game", "song-minister-game"),
        ("sync_star_office_ui", "star-office-ui"),
    ]:
        try:
            mod = __import__(f"tools.build.{sync_mod}", fromlist=["sync"])
            sync_fn = getattr(mod, f"{sync_mod}")
            sync_fn()
            print(f"  ✓ {label} 同步完成", flush=True)
        except Exception as exc:
            print(f"  ⚠ {label} 同步跳过 ({exc})", flush=True)
            rc = 1
    return rc

#!/usr/bin/env python3
"""古地名坐标补全 — 薄包装（已废弃）。

⚠️ 已迁移至 tools/build/agents/geolocator.py。
   本模块保留向后兼容的公开 API 和数据加载函数，内部委托给地理定位 Agent。
   请改用 Agent CLI：

     python3 tools/build/agents/geolocator.py --dir artifacts/story_map

用法（向后兼容）:
  python3 tools/build/fix_coordinates.py              # 补全所有缺失坐标
  python3 tools/build/fix_coordinates.py --dry-run    # 仅预览
"""

from __future__ import annotations

import warnings
from pathlib import Path

warnings.warn(
    "tools.build.fix_coordinates is deprecated. "
    "Use tools.build.agents.geolocator.GeoLocatorAgent instead.",
    DeprecationWarning,
    stacklevel=2,
)

from tools.build.agents.geolocator import (
    EMPTY_LOCATIONS_FALLBACK,
    GeoLocatorAgent,
    UNRESOLVABLE,
    load_ancient_mappings,
    load_city_coords,
)

__all__ = [
    "load_ancient_mappings",
    "load_city_coords",
    "UNRESOLVABLE",
    "EMPTY_LOCATIONS_FALLBACK",
    "sync_coordinates",
    "main",
]


def sync_coordinates(target_dir: Path | None = None) -> dict:
    """坐标补全（委托给地理定位 Agent）。"""
    agent = GeoLocatorAgent(html_dir=target_dir, verbose=True)
    report = agent.run()
    return report.details


def main() -> None:
    """CLI 入口（兼容旧脚本调用）。"""
    import argparse
    ap = argparse.ArgumentParser(description="古地名坐标补全")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    agent = GeoLocatorAgent(dry_run=args.dry_run, verbose=True)
    report = agent.run()
    print(f"\n{report.message}")


if __name__ == "__main__":
    main()

"""
===============================================================================
地理集成模块 — Geo Integration
===============================================================================
将共享的离线地理查询能力注入到运行时 GeocodeAgent 中。

本模块作为一个薄封装层，从 storymap/script/map/offline_geo_lookup 模块
重新导出核心地理查询类 GeoLookup 及其工厂函数 get_geo_lookup，
供 legacy_agent 子系统中的 GeocodeAgent 直接使用。

导出的符号：
  - GeoLookup:      离线地理坐标查询类，提供古地名到现代经纬度的映射能力
  - get_geo_lookup: 工厂函数，返回全局唯一的 GeoLookup 实例（单例模式）

典型用法：
    from .geo_integration import get_geo_lookup
    lookup = get_geo_lookup()
    coord = lookup.query("长安")  # → (34.26, 108.94) 或类似坐标
===============================================================================
"""

from __future__ import annotations

from ...map.offline_geo_lookup import GeoLookup, get_geo_lookup

__all__ = ["GeoLookup", "get_geo_lookup"]

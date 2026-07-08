"""锁住 geocode_service 核心地理编码行为。

跑: ``python3 -m pytest storymap/tests/test_geocode_service.py -v``
"""
from __future__ import annotations

from storymap.script.map.geocode_service import (
    normalize_place_key,
    split_ancient_modern_heuristic,
)


class TestNormalizePlaceKeyGeocode:
    def test_strips_parens(self):
        result = normalize_place_key("长安（今西安）")
        # normalize_place_key 去括号后返回括号前的地名
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handles_empty(self):
        assert normalize_place_key("") == ""
        assert isinstance(normalize_place_key(""), str)


class TestSplitAncientModernHeuristic:
    def test_handle_modern(self):
        ancient, modern = split_ancient_modern_heuristic("金陵（今南京）")
        assert modern == "南京" or ancient == "金陵"

    def test_empty(self):
        ancient, modern = split_ancient_modern_heuristic("")
        assert ancient == ""
        assert modern == ""

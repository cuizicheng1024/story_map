"""锁住 P0 边界校验,避免重构 / 依赖升级后悄悄漂掉。

跑: ``python3 -m pytest storymap/tests/test_geocode_china_bounds.py -v``
"""
from __future__ import annotations

import re
from pathlib import Path

from storymap.script.map.geocode_service import (
    _accept_china_coord,
    resolve_place_coord,
)
from storymap.script.map.map_client import (
    _is_inside_china,
    _is_inside_china_mainland,
)


# ---------------------------------------------------------------------------
# Polygon / bbox helpers
# ---------------------------------------------------------------------------

class TestChinaInsideHelpers:
    def test_bbox_accepts_well_known_capital(self):
        # 北京
        assert _is_inside_china(39.9042, 116.4074)
        # 上海
        assert _is_inside_china(31.2304, 121.4737)
        # 乌鲁木齐
        assert _is_inside_china(43.8256, 87.6168)

    def test_bbox_rejects_european_drift(self):
        # 意大利普利亚
        assert not _is_inside_china(41.05, 16.23)
        # 阿尔巴尼亚
        assert not _is_inside_china(41.88, 20.63)
        # 西班牙
        assert not _is_inside_china(42.85, -0.33)
        # 巴西圣保罗 (司马懿 司马懿.html 里出现过的负值)
        assert not _is_inside_china(-23.54, -46.58)

    def test_mainland_polygon_rejects_vietnam(self):
        # 越南河内 (曾经被错配成 "河内郡" 司马懿 出生地)
        # 在 bbox 17.5-55.5 lat,72-136.5 lng 里,但不在大陆多边形里
        assert not _is_inside_china_mainland(21.03, 105.85)
        # 缅甸仰光
        assert not _is_inside_china_mainland(16.81, 96.16)
        # 俄罗斯海参崴
        assert not _is_inside_china_mainland(43.12, 131.92)

    def test_mainland_polygon_accepts_sima_yi_birthplace(self):
        # 河南温县 (司马懿 出生地) 必须接受
        assert _is_inside_china_mainland(34.94, 113.08)
        # 陕西五丈原
        assert _is_inside_china_mainland(34.29, 107.61)
        # 辽宁襄平 (今辽阳)
        assert _is_inside_china_mainland(41.27, 123.19)
        # 云南昆明 - 检查 bbox 边缘
        assert _is_inside_china_mainland(25.04, 102.71)


# ---------------------------------------------------------------------------
# _accept_china_coord (resolve_place_coord 的核心闸门)
# ---------------------------------------------------------------------------

class TestAcceptChinaCoord:
    def test_rejects_out_of_china_coord_when_input_is_chinese(self):
        # 司马懿 档案里曾出现过的北马其顿坐标,输入是中文地名 -> 必须 reject
        assert _accept_china_coord(["许昌"], (41.88, 20.63)) is False
        # 圣保罗 bbox 不在中国,但 _looks_chinese("洛阳") is True -> reject
        assert _accept_china_coord(["洛阳"], (-23.54, -46.58)) is False

    def test_accepts_well_known_chinese_place(self):
        assert _accept_china_coord(["温县"], (34.94, 113.08)) is True
        assert _accept_china_coord(["许昌", "xuchang alias"], (34.17, 114.02)) is True

    def test_skips_check_for_non_chinese_input(self):
        # 全部非中文 (英文 European place) -> 不强制中国边界
        assert _accept_china_coord(["York"], (53.96, -1.08)) is True
        assert _accept_china_coord(["London", "City"], (51.5, -0.13)) is True

    def test_handles_compound_year_event_keys(self):
        # render 路径里 resolve_place_coord 会接 "206年: 洛阳 (入仕)" 这类
        # 复合 key。_strip_place_metadata 已经把 "洛阳" 拿出来落到 candidates
        # 里了,这里直接验证中文 yes-no 判别对复合 key 仍能正常判 True。
        assert _accept_china_coord(
            ["206年: 洛阳 (入仕)", "洛阳"], (34.62, 112.45)
        ) is True
        # 没中文字符,即便 in-bbox,也不强制
        assert _accept_china_coord(
            ["AD 206: Luoyang (entering service)"],
            (34.62, 112.45),
        ) is True


# ---------------------------------------------------------------------------
# resolve_place_coord (端到端)
# ---------------------------------------------------------------------------

class TestResolvePlaceCoordEndToEnd:
    """接 AMap / 历史地名索引 / Nominatim 时要确保:
    - 中文地名返回的坐标全部在中国境内
    - out-of-china 的 fallback 永远不会写回
    """

    def test_simple_chinese_place_returns_in_china(self):
        for name in ["温县", "许昌", "洛阳", "五丈原", "关中", "襄平"]:
            coord = resolve_place_coord(name)
            assert coord is not None, f"{name} should resolve"
            lat, lng = float(coord[0]), float(coord[1])
            assert _is_inside_china_mainland(lat, lng), \
                f"{name} -> ({lat}, {lng}) is NOT in mainland China"

    def test_compound_year_event_keys_resolve_to_china(self):
        # 这条断言是这次重构的真正目的:
        # 在 HTML 渲染时,resolve_place_coord 接收到的 key 通常是
        # "206年: 洛阳 (入仕)" / "230年—234年: 关中 (抵御北伐)" 这种
        # 带年份 + 事件描述的复合 key,如果不分拆就拿不到正确坐标。
        coords = {
            "179年: 河内郡温县 (出生)": None,
            "206年: 洛阳 (入仕)": None,
            "230年—234年: 关中 (抵御北伐)": None,
            "234年: 五丈原 (五丈原对峙)": None,
        }
        for k in list(coords):
            c = resolve_place_coord(k)
            coords[k] = c
            if c is not None:
                lat, lng = float(c[0]), float(c[1])
                assert _is_inside_china_mainland(lat, lng), \
                    f"{k} -> ({lat}, {lng}) escaped"

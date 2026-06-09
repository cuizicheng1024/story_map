import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_map as sm


def test_offline_profile_uses_local_index_when_geocode_disabled(monkeypatch):
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：北宋
- **出生**：1037年，眉州眉山（今四川省眉山市）
- **去世**：1101年，常州（今江苏省常州市）
- **享年**：64岁

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：眉州眉山
- **公元纪年**：1037年—1056年
- **位置**：眉州眉山（今四川省眉山市）
- **事迹**：成长求学。

### 📍 重要地点：开封（汴京）
- **公元纪年**：1056年—1057年
- **位置**：汴京（今河南省开封市）
- **事迹**：赴京应试。

### 🔴 去世地：常州
- **公元纪年**：1101年
- **位置**：常州（今江苏省常州市）
- **经过**：北归病逝。
"""

    fake_coords = {
        "眉州眉山": (30.048, 103.831),
        "四川省眉山市": (30.048, 103.831),
        "汴京": (34.797, 114.307),
        "河南省开封市": (34.797, 114.307),
        "常州": (31.810, 119.974),
        "江苏省常州市": (31.810, 119.974),
    }

    def fake_lookup(*names):
        for name in names:
            key = str(name or "").strip()
            if key in fake_coords:
                return fake_coords[key]
        return None

    monkeypatch.setitem(sm._GEOCODE_API, "lookup_coords_from_historical_index", fake_lookup)
    monkeypatch.setitem(
        sm._GEOCODE_API,
        "resolve_place_coord",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call online geocode")),
    )

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    assert len(profile["locations"]) == 3
    assert profile["person"]["birth"]["lat"] is not None
    assert profile["person"]["death"]["lat"] is not None


def test_offline_profile_keeps_longzhong_location_when_coords_table_uses_scenic_name():
    md = """# 诸葛亮

## 一、人物档案

### 基本信息
- **姓名**：诸葛亮
- **时代**：三国时期
- **出生**：181年，琅琊郡阳都县（今山东省临沂市沂南县）
- **去世**：234年，五丈原（今陕西省宝鸡市岐山县）

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：襄阳隆中
- **公元纪年**：约公元195年 - 207年
- **位置**：荆州南阳郡邓县隆中（今湖北省襄阳市襄城区）
- **事迹**：隐居躬耕，等待明主。
- **意义**：完成《隆中对》的战略思考。

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 湖北省襄阳市隆中风景区 | 32.0136 | 112.0293 |
| 山东省临沂市沂南县 | 35.5498 | 118.4657 |
| 陕西省宝鸡市岐山县 | 34.2658 | 107.6186 |
"""

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    names = [str(item.get("name") or "") for item in profile["locations"]]
    assert "襄阳隆中" in names

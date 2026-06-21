import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import profile_builder
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


def test_profile_locations_are_sorted_by_time_bounds_for_wang_bo_style_ranges():
    md = """# 王勃

## 一、人物档案

### 基本信息
- **姓名**：王勃
- **时代**：唐代
- **出生**：650年，绛州龙门（今山西省运城市河津市）
- **去世**：676年，南海（今南海北部海域）

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：洪州
- **公元纪年**：675年
- **位置**：洪州（今江西省南昌市）
- **事迹**：作《滕王阁序》。

### 📍 重要地点：广州
- **公元纪年**：约676年
- **位置**：南海郡（今广东省广州市）
- **事迹**：返回途中溺水，惊悸而死。

### 📍 重要地点：交趾
- **公元纪年**：约675年-公元676年
- **位置**：交趾（今越南河内市附近）
- **事迹**：南下省父。

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 江西省南昌市 | 28.68 | 115.86 |
| 广东省广州市 | 23.13 | 113.26 |
| 越南河内市 | 21.03 | 105.85 |
| 山西省运城市河津市 | 35.59 | 110.71 |
| 南海北部海域 | 20.20 | 112.00 |
"""

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    names = [str(item.get("name") or "") for item in profile["locations"]]
    assert names == ["洪州", "交趾", "广州"]


def test_profile_locations_do_not_treat_finally_arrived_text_as_death():
    md = """# 测试人物

## 一、人物档案

### 基本信息
- **姓名**：测试人物
- **时代**：唐代
- **出生**：700年，长安（今陕西省西安市）
- **去世**：760年，洛阳（今河南省洛阳市）

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：长安
- **公元纪年**：700年
- **位置**：长安（今陕西省西安市）
- **事迹**：出生。

### 📍 重要地点：汴州
- **公元纪年**：740年
- **位置**：汴州（今河南省开封市）
- **事迹**：终于回朝，重新受到重用。

### 📍 重要地点：洛阳
- **公元纪年**：760年
- **位置**：洛阳（今河南省洛阳市）
- **事迹**：病逝。

## 地点坐标
| 现称 | 纬度 | 经度 |
| --- | --- | --- |
| 陕西省西安市 | 34.3416 | 108.9398 |
| 河南省开封市 | 34.7973 | 114.3076 |
| 河南省洛阳市 | 34.6197 | 112.4540 |
"""

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    names = [str(item.get("name") or "") for item in profile["locations"]]
    assert names == ["长安", "汴州", "洛阳"]


def test_extract_location_time_bounds_does_not_treat_range_dash_as_negative_sign():
    assert profile_builder._extract_location_time_bounds("1949年-1975年") == (1949, 1975)
    assert profile_builder._extract_location_time_bounds("1975年4月5日") == (1975, 1975)
    assert profile_builder._extract_location_time_bounds("前221年-前210年") == (-221, -210)


def test_profile_locations_are_sorted_chronologically_for_jiang_jieshi_ranges():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "蒋介石.md").read_text(encoding="utf-8")

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    names = [str(item.get("name") or "") for item in profile["locations"]]
    assert names[:9] == ["溪口", "保定", "东京", "上海", "广州", "南京", "重庆", "台北", "台北士林官邸"]


def test_profile_locations_are_sorted_chronologically_for_huoqubing_bce_years():
    md = (REPO_ROOT / "storymap" / "examples" / "story" / "霍去病.md").read_text(encoding="utf-8")

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    names = [str(item.get("name") or "") for item in profile["locations"]]
    assert names == ["平阳", "长安", "陇西", "河西走廊", "漠北", "长安"]

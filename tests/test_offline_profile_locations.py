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

    monkeypatch.setattr(sm, "_lookup_coords_from_historical_index", fake_lookup)
    monkeypatch.setattr(
        sm,
        "resolve_place_coord",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call online geocode")),
    )

    profile = sm.load_profile_from_md(md, allow_geocode=False)

    assert profile is not None
    assert len(profile["locations"]) == 3
    assert profile["person"]["birth"]["lat"] is not None
    assert profile["person"]["death"]["lat"] is not None

import importlib.util
import sys

from tests_support import REPO_ROOT
TOOLS_DIR = REPO_ROOT / "tools"
# fix_story_markdown_corpus.py 已迁入 tools/oneshot/，本测试也跟随更新路径。
ONESHOT_DIR = TOOLS_DIR / "oneshot"

def _load_fix_module():
    module_path = ONESHOT_DIR / "fix_story_markdown_corpus.py"
    spec = importlib.util.spec_from_file_location("fix_story_markdown_corpus", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def test_upgrade_legacy_three_column_timeline_promotes_age_into_event():
    fixer = _load_fix_module()
    md = """# 苏轼

## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| :--- | :--- | :--- |
| 1037年 | 1岁 | 生于眉州眉山。 |
| 1057年 | 21岁 | 进士及第。 |
"""

    updated = fixer._upgrade_legacy_three_column_timeline(md)

    assert "| 年份 | 古称 | 现称 | 事件 |" in updated
    assert "| 1037年 |  |  | （年龄：1岁）生于眉州眉山。 |" in updated
    assert "| 1057年 |  |  | （年龄：21岁）进士及第。 |" in updated

def test_upgrade_legacy_three_column_timeline_promotes_stage_into_event():
    fixer = _load_fix_module()
    md = """# 陈独秀

## 四、生平时间线

| 年份 | 阶段 | 关键事件 |
| --- | --- | --- |
| 1897年 | 青年 | 入杭州求是书院学习。 |
"""

    updated = fixer._upgrade_legacy_three_column_timeline(md)

    assert "| 年份 | 古称 | 现称 | 事件 |" in updated
    assert "| 1897年 |  |  | （阶段：青年）入杭州求是书院学习。 |" in updated

def test_upgrade_single_column_timeline_keeps_event_text():
    fixer = _load_fix_module()
    md = """# 夸父

## 生平时间线
| 关键事件 |
| --- |
| 立下宏愿，从居住地出发，开始追逐太阳。 |
"""

    updated = fixer._upgrade_single_column_timeline(md)

    assert "| 年份 | 古称 | 现称 | 事件 |" in updated
    assert "|  |  |  | 立下宏愿，从居住地出发，开始追逐太阳。 |" in updated

def test_fill_timeline_locations_from_sections_uses_direct_place_matches():
    fixer = _load_fix_module()
    md = """# 苏轼

## 人生历程与重要地点（按时间顺序）

### 🟢 出生地：眉州眉山
- **公元纪年**：1037年
- **位置**：眉州眉山（今四川省眉山市）
- **事件**：出生。

### 📍 重要地点：密州
- **公元纪年**：1074年—1076年
- **位置**：密州（今山东省诸城市）
- **事迹**：移知密州。

### 🔴 去世地：常州
- **公元纪年**：1101年
- **位置**：常州（今江苏省常州市）
- **经过**：病逝。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 1037年 |  |  | 生于眉州眉山。 |
| 1074年 |  |  | 移知密州。 |
| 1101年 |  |  | 病逝于常州。 |
| 1065年 |  |  | 还朝任职。 |
"""

    updated = fixer._fill_timeline_locations_from_sections(md)

    assert "| 1037年 | 眉州眉山 | 四川省眉山市 | 生于眉州眉山。 |" in updated
    assert "| 1074年 | 密州 | 山东省诸城市 | 移知密州。 |" in updated
    assert "| 1101年 | 常州 | 江苏省常州市 | 病逝于常州。 |" in updated
    assert "| 1065年 |  |  | 还朝任职。 |" in updated

def test_fill_timeline_locations_from_sections_skips_ambiguous_matches():
    fixer = _load_fix_module()
    md = """# 人物甲

## 人生历程与重要地点（按时间顺序）

### 📍 重要地点：杭州
- **公元纪年**：1071年—1074年
- **位置**：杭州（今浙江省杭州市）
- **事迹**：地方任职。

### 📍 重要地点：密州
- **公元纪年**：1074年—1076年
- **位置**：密州（今山东省诸城市）
- **事迹**：地方任职。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 1074年 |  |  | 奉诏转任地方。 |
"""

    updated = fixer._fill_timeline_locations_from_sections(md)

    assert "| 1074年 |  |  | 奉诏转任地方。 |" in updated

def test_fill_timeline_locations_from_sections_uses_position_when_label_is_generic():
    fixer = _load_fix_module()
    md = """# 李白

## 人生历程与重要地点（按时间顺序）

### 🟢 出生地（存疑）
- **时间**：701年
- **地点**：说法不一，一说碎叶城（今吉尔吉斯斯坦托克马克市），一说蜀中（今四川省江油市）
- **事件**：李白出生于此。

### 📍 重要地点：浔阳（庐山）
- **时间**：756年
- **地点**：浔阳庐山（今江西省九江市）
- **事件**：隐居庐山。

## 生平时间线
| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 701年 |  |  | 出生于碎叶城（存疑）。 |
| 756年 |  |  | 隐居庐山。 |
"""

    updated = fixer._fill_timeline_locations_from_sections(md)

    assert "| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克市 | 出生于碎叶城（存疑）。 |" in updated
    assert "| 756年 | 浔阳（庐山） | 江西省九江市 | 隐居庐山。 |" in updated

def test_fill_timeline_locations_from_sections_replaces_placeholder_ancient_name():
    fixer = _load_fix_module()
    md = """# 李白

## 人生历程与重要地点（按时间顺序）

### 🟢 出生地（存疑）
- **时间**：701年
- **地点**：说法不一，一说碎叶城（今吉尔吉斯斯坦托克马克市），一说蜀中（今四川省江油市）
- **事件**：李白出生于此。

## 生平时间线
| 年份 | 古称 | 现称 | 事件 |
| --- | --- | --- | --- |
| 701年 | 出生地（存疑） | 吉尔吉斯斯坦托克马克市 | 出生于碎叶城（存疑）。 |
"""

    updated = fixer._fill_timeline_locations_from_sections(md)

    assert "| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克市 | 出生于碎叶城（存疑）。 |" in updated

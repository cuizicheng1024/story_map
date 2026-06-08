import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import parsers


def test_parse_story_document_collects_core_sections():
    md = """# 苏轼

## 一、人物档案

### 基本信息
- **姓名**：苏轼
- **时代**：北宋
- **出生**：1037年，眉州眉山（今四川省眉山市）
- **去世**：1101年，常州（今江苏省常州市）
- **享年**：64岁

### 生平概述
北宋文学家、书法家。

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：眉州眉山
- **公元纪年**：1037年
- **位置**：眉州眉山（今四川省眉山市）
- **事迹**：成长求学

### 📍 重要地点：黄州
- **公元纪年**：1080年
- **位置**：黄州（今湖北黄冈）
- **事迹**：谪居黄州
- **名句**：大江东去

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| 1037 | 眉州眉山 | 四川省眉山市 | 出生 |
| 1080 | 黄州 | 湖北黄冈 | 谪居黄州 |

## 地点坐标
| 现称 | 纬度 | 经度 |
| 四川省眉山市 | 30.048 | 103.831 |
| 湖北黄冈 | 30.45 | 114.87 |

## 人教版教材知识点
### 高中阶段
- 《念奴娇》

### 历史评价
- 旷达豪放
"""
    parsed = parsers.parse_story_document(md)

    assert parsed.basic_info.name == "苏轼"
    assert parsed.basic_info.dynasty == "北宋"
    assert parsed.overview == "北宋文学家、书法家。"
    assert len(parsed.timeline_rows) == 2
    assert len(parsed.location_sections) == 2
    assert parsed.coords_table["四川省眉山市"] == (30.048, 103.831)
    assert "《念奴娇》" in parsed.exam_points
    assert parsed.historical_reviews == ["旷达豪放"]


def test_normalize_markdown_tables_inserts_missing_separator():
    md = """## 四、生平时间线
| 年份 | 现称 | 事件 |
| 1037 | 四川省眉山市 | 出生 |
"""

    normalized = parsers._normalize_markdown_tables(md)
    lines = normalized.splitlines()

    assert lines[1] == "| 年份 | 现称 | 事件 |"
    assert lines[2] == "| --- | --- | --- |"

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
TOOLS_DIR = REPO_ROOT / "tools"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_validator_module():
    module_path = TOOLS_DIR / "validate_story_markdown.py"
    spec = importlib.util.spec_from_file_location("validate_story_markdown", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validator_accepts_unnumbered_required_sections(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物甲.md"
    file_path.write_text(
        """# 人物甲

## 人物档案

### 基本信息
- **姓名**：人物甲
- **时代**：近现代
- **出生**：1900年，北京（今北京市）
- **去世**：1980年，北京（今北京市）

## 人生历程与重要地点（按时间顺序）

### 🟢 出生地：北京
- **公元纪年**：1900年
- **位置**：北京（今北京市）
- **事迹**：出生。
- **意义**：起点。

### 🔴 去世地：北京
- **公元纪年**：1980年
- **位置**：北京（今北京市）
- **经过**：去世。
- **意义**：终点。

## 生平时间线

| 年份 | 年龄 | 关键事件 |
| :--- | :--- | :--- |
| 1900年 | 0岁 | 出生。 |
| 1980年 | 80岁 | 去世。 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert not any("缺少必需章节" in msg for msg in result.errors)


def test_validator_reports_low_offline_hit_rate(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物乙.md"
    file_path.write_text(
        """# 人物乙

## 一、人物档案

### 基本信息
- **姓名**：人物乙
- **时代**：北宋
- **出生**：1030年，甲地（今甲市）
- **去世**：1100年，乙地（今乙市）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：甲地
- **公元纪年**：1030年
- **位置**：甲地（今甲市）
- **事迹**：出生。
- **意义**：起点。

### 📍 重要地点：丙地
- **公元纪年**：1050年
- **位置**：丙地（今丙市）
- **事迹**：游历。
- **意义**：转折。

### 📍 重要地点：丁地
- **公元纪年**：1070年
- **位置**：丁地（今丁市）
- **事迹**：任官。
- **意义**：发展。

### 📍 重要地点：戊地
- **公元纪年**：1080年
- **位置**：戊地（今戊市）
- **事迹**：迁居。
- **意义**：变化。

### 🔴 去世地：乙地
- **公元纪年**：1100年
- **位置**：乙地（今乙市）
- **经过**：去世。
- **意义**：终点。

## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| :--- | :--- | :--- |
| 1030年 | 0岁 | 出生。 |
| 1100年 | 70岁 | 去世。 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert any("离线命中率过低" in msg for msg in result.errors)


def test_validator_allows_exactly_half_of_precise_locations_to_resolve(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物乙半数命中.md"
    file_path.write_text(
        """# 人物乙半数命中

## 一、人物档案

### 基本信息
- **姓名**：人物乙半数命中
- **时代**：近现代
- **出生**：1900年，甲地（今甲市）
- **去世**：1980年，乙地（今乙市）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：甲地
- **公元纪年**：1900年
- **位置**：甲地（今甲市）
- **事迹**：出生。
- **意义**：起点。

### 📍 重要地点：丙地
- **公元纪年**：1920年
- **位置**：丙地（今丙市）
- **事迹**：求学。
- **意义**：成长。

### 📍 重要地点：丁地
- **公元纪年**：1940年
- **位置**：丁地（今丁市）
- **事迹**：任职。
- **意义**：发展。

### 🔴 去世地：乙地
- **公元纪年**：1980年
- **位置**：乙地（今乙市）
- **经过**：去世。
- **意义**：终点。

## 四、生平时间线

| 年份 | 阶段 | 关键事件 |
| :--- | :--- | :--- |
| 1900年 | 出生 | 出生。 |
| 1980年 | 去世 | 去世。 |

## 地点坐标
| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 甲地 | 甲市 | 30.000000 | 120.000000 |
| 乙地 | 乙市 | 31.000000 | 121.000000 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert not any("离线命中率过低" in msg for msg in result.errors)
    assert any("地点解析存在落差" in msg for msg in result.warnings)


def test_validator_accepts_extended_timeline_header_used_by_story_examples(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物丙.md"
    file_path.write_text(
        """# 人物丙

## 一、人物档案

### 基本信息
- **姓名**：人物丙
- **朝代**：西汉
- **出生**：前52年，南郡秭归（今湖北秭归）
- **去世**：前15年，青冢（今内蒙古呼和浩特附近）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：南郡秭归
- **公元纪年**：前52年
- **位置**：南郡秭归（今湖北秭归）
- **事迹**：出生。
- **意义**：人生起点。

### 🔴 归葬地：青冢
- **公元纪年**：前15年
- **位置**：青冢（今内蒙古呼和浩特附近）
- **经过**：归葬。
- **意义**：历史象征。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| :--- | :--- | :--- | :--- |
| 前52年 | 南郡秭归 | 湖北秭归 | 出生 |
| 前15年 | 青冢 | 内蒙古呼和浩特附近 | 归葬 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert not any("生平时间线" in msg for msg in result.errors)


def test_validator_rejects_vague_locations(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物丁.md"
    file_path.write_text(
        """# 人物丁

## 一、人物档案

### 基本信息
- **姓名**：人物丁
- **时代**：北魏
- **出生**：466年，范阳涿州（今河北涿州）
- **去世**：527年，阴盘驿（今陕西临潼）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：范阳涿州
- **公元纪年**：466年
- **位置**：范阳涿州（今河北涿州）
- **事迹**：出生。
- **意义**：起点。

### 📍 重要地点：北魏境内
- **公元纪年**：495年
- **位置**：北魏境内
- **事迹**：任职。
- **意义**：仕途展开。

### 🔴 去世地：阴盘驿
- **公元纪年**：527年
- **位置**：阴盘驿（今陕西临潼）
- **经过**：去世。
- **意义**：终点。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| :--- | :--- | :--- | :--- |
| 466年 | 范阳涿州 | 河北涿州 | 出生 |
| 495年 | 北魏境内 | 北魏境内 | 任职 |
| 527年 | 阴盘驿 | 陕西临潼 | 去世 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert any("存在泛地名" in msg for msg in result.errors)


def test_validator_accepts_inline_coordinates_and_variant_coord_headers(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物戊.md"
    file_path.write_text(
        """# 人物戊

## 一、人物档案

### 基本信息
- **姓名**：人物戊
- **时代**：近现代
- **出生**：1900年，都柏林
- **去世**：1945年，都柏林

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：都柏林
- **公元纪年**：1900年
- **位置**：都柏林（今爱尔兰都柏林，坐标：53.3498, -6.2603）
- **事迹**：出生。
- **意义**：起点。

### 📍 重要地点：三一学院
- **公元纪年**：1918年
- **位置**：都柏林三一学院（今爱尔兰都柏林三一学院，坐标：53.3438, -6.2546）
- **事迹**：求学。
- **意义**：成长。

### 🔴 去世地：都柏林
- **公元纪年**：1945年
- **位置**：圣帕特里克大教堂（今爱尔兰都柏林圣帕特里克大教堂，坐标：53.3396, -6.2719）
- **经过**：去世。
- **意义**：终点。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| :--- | :--- | :--- | :--- |
| 1900年 | 都柏林 | 爱尔兰都柏林 | 出生 |
| 1918年 | 三一学院 | 爱尔兰都柏林三一学院 | 求学 |
| 1945年 | 圣帕特里克大教堂 | 爱尔兰都柏林圣帕特里克大教堂 | 去世 |

## 地点坐标

| 地点名称 | 现代行政区划 | 经纬度 |
| :--- | :--- | :--- |
| 都柏林 | 爱尔兰都柏林 | 53.3498°N, 6.2603°W |
| 三一学院 | 爱尔兰都柏林三一学院 | 53.3438°N, 6.2546°W |
| 圣帕特里克大教堂 | 爱尔兰都柏林圣帕特里克大教堂 | 53.3396°N, 6.2719°W |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert not any("离线命中率过低" in msg for msg in result.errors)
    assert not any("离线坐标未命中" in msg for msg in result.warnings)


def test_validator_allows_sparse_single_site_without_generic_count_warning(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物己.md"
    file_path.write_text(
        """# 人物己

## 一、人物档案

### 基本信息
- **姓名**：人物己
- **时代**：隋朝
- **出生**：600年，赵州（今河北赵县）
- **去世**：650年，赵州（今河北赵县）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 重要地点：赵州桥
- **公元纪年**：605年
- **位置**：赵州桥（今河北省石家庄市赵县赵州桥）
- **事迹**：主持修建。
- **意义**：代表作所在地。

## 四、生平时间线

| 年份 | 古称 | 现称 | 事件 |
| :--- | :--- | :--- | :--- |
| 605年 | 赵州桥 | 河北省石家庄市赵县赵州桥 | 主持修建 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert not any("仅解析出 1 个地点" in msg for msg in result.warnings)


def test_validator_skips_death_warning_for_living_people(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物庚.md"
    file_path.write_text(
        """# 人物庚

## 一、人物档案

### 基本信息
- **姓名**：人物庚
- **时代**：当代
- **出生**：1960年，甲地（今甲市）
- **去世**：健在（截至2026年）

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：甲地
- **公元纪年**：1960年
- **位置**：甲地（今甲市）
- **事迹**：出生。
- **意义**：起点。

### 📍 重要地点：乙地
- **公元纪年**：2000年
- **位置**：乙地（今乙市）
- **事迹**：工作。
- **意义**：发展。

### 🔴 现居地：乙地
- **公元纪年**：至今
- **位置**：乙地（今乙市）
- **经过**：仍在此生活。
- **意义**：当前生活中心。

## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| --- | --- | --- |
| 1960年 | 0岁 | 出生。 |
| 2000年 | 40岁 | 工作。 |
| 至今 | - | 仍在世。 |

## 地点坐标
| 现称 | 现代搜索地名 | 纬度 | 经度 |
| --- | --- | --- | --- |
| 甲地 | 甲市 | 30.000000 | 120.000000 |
| 乙地 | 乙市 | 31.000000 | 121.000000 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert "未解析出去世地" not in result.warnings


def test_validator_skips_placeholder_birth_death_and_count_gap(tmp_path):
    validator = _load_validator_module()
    file_path = tmp_path / "人物辛.md"
    file_path.write_text(
        """# 人物辛

## 一、人物档案

### 基本信息
- **姓名**：人物辛
- **时代**：存疑
- **出生**：存疑/说法不一/待考
- **去世**：存疑/说法不一/待考

## 三、人生历程与重要地点（按时间顺序）

### 🟢 出生地：存疑
- **公元纪年**：不详
- **位置**：存疑/说法不一/待考
- **事迹**：无考。
- **意义**：无考。

### 🔴 去世地：存疑
- **公元纪年**：不详
- **位置**：存疑/说法不一/待考
- **经过**：无考。
- **意义**：无考。

## 四、生平时间线

| 年份 | 年龄 | 关键事件 |
| --- | --- | --- |
| 不详 | 不详 | 生平失考。 |
""",
        encoding="utf-8",
    )

    result = validator.validate_markdown(file_path)

    assert "未解析出出生地" not in result.warnings
    assert "未解析出去世地" not in result.warnings
    assert not any("未解析出任何地点" in msg for msg in result.warnings)
    assert not any("地点解析存在落差" in msg for msg in result.warnings)

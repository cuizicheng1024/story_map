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

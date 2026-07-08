#!/usr/bin/env python3
"""修复知识性错误：章节编号、LLM 思考泄露、占位符等。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
HTML_DIR = ROOT / "artifacts" / "story_map"
INDEX_PATH = ROOT / "data" / "corpus" / "people_summary_index.json"
AUDIT_PATH = ROOT / "tools" / "debug" / "knowledge_audit_v2.json"

# ── LLM 思考过程模式 ──
THINK_PATTERNS = [
    (r"The user wants me to .*?into a structured JSON format\.\s*", ""),
    (r"Since there (?:are|is) no external material[s]? provided,.*?cautions\.\s*", ""),
    (r"Let me think about what I know about [^:]+:\s*", ""),
    (r"Let me organize what I know about [^:]+:\s*", ""),
    (r"Let me (?:think|organize|draft|refine|check|structure|finalize)[^.]*\.\s*", ""),
    (r"I need to .*?(?:\.\s*|\n)", ""),
    (r"Actually wait[^.]*\.\s*", ""),
    (r"Looking good[^.]*\.\s*", ""),
    (r"I'll .*? structure[^.]*\.\s*", ""),
    (r"I want to [^.]*\.\s*", ""),
    (r"Total roughly[^.]*\.\s*", ""),
    # Remove leftover bullet points from thinking process
    (r"(?:^|\n)- [^\n]+?(?:courtesy name|Dynasty|Era|Key identit|Key achievement)[^\n]*\n", "\n"),
    (r"(?:^|\n)- [^\n]*?(?:Born:|Died:|Classical period|Child prodigy|Major works:)[^\n]*\n", "\n"),
    # Clean up multiple consecutive newlines
    (r"\n{3,}", "\n\n"),
]


def parse_embedded_json(html: str) -> tuple[dict | None, str | None, str | None]:
    """从 HTML 中提取内嵌的 JSON 数据，返回 (data, pattern, match_text)。"""
    m = re.search(r"window\.__EXPORT_DATA__\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
    pattern = "window.__EXPORT_DATA__"
    if not m:
        m = re.search(r'const data = (\{.*?"person".*?\});\s*window\.__EXPORT_DATA__', html, re.DOTALL)
        pattern = "const data"
    if not m:
        return None, None, None
    try:
        return json.loads(m.group(1)), pattern, m.group(1)
    except json.JSONDecodeError:
        return None, None, None


def clean_think_text(text: str) -> tuple[str, bool]:
    """清除 LLM 思考过程，返回 (cleaned_text, changed)。"""
    changed = False
    cleaned = text
    for pattern, replacement in THINK_PATTERNS:
        new_text = re.sub(pattern, replacement, cleaned, flags=re.DOTALL | re.IGNORECASE)
        if new_text != cleaned:
            changed = True
            cleaned = new_text
    # Clean up extra whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned, changed


def fix_chapter_numbering(markdown: str) -> tuple[str, bool]:
    """修复章节编号：修正各种重复和缺失模式。"""
    changed = False
    md = markdown

    # ── Pattern 1: 二 repeated (地图说明 + 人生历程) ──
    # 二、人生足迹地图说明 → keep
    # 二、人生历程与重要地点 → 三
    # 三、生平时间线 → 四
    if "## 二、人生足迹地图说明" in md and "## 二、人生历程与重要地点（按时间顺序）" in md:
        md = md.replace("## 二、人生历程与重要地点（按时间顺序）",
                         "## 三、人生历程与重要地点（按时间顺序）")
        md = md.replace("## 三、生平时间线", "## 四、生平时间线")
        changed = True

    # ── Pattern 2: 四 repeated (生平时间线 + 补充说明) ──
    # 四、生平时间线 → keep
    # 四、补充说明 → 五
    if "## 四、生平时间线" in md and "## 四、补充说明" in md:
        md = md.replace("## 四、补充说明", "## 五、补充说明")
        changed = True

    # ── Pattern 3: 三 repeated (地点坐标 + 生平时间线, no map section) ──
    # 三、地点坐标 → keep
    # 三、生平时间线 → 四
    if "## 三、地点坐标" in md and "## 三、生平时间线" in md:
        md = md.replace("## 三、生平时间线", "## 四、生平时间线")
        changed = True

    # ── Pattern 4: 二 repeated (人生足迹概览 + 人生历程) — 聂鲁达 style ──
    if "## 二、人生足迹概览" in md and "## 二、人生历程与重要地点（按时间顺序）" in md:
        md = md.replace("## 二、人生历程与重要地点（按时间顺序）",
                         "## 三、人生历程与重要地点（按时间顺序）")
        md = md.replace("## 三、生平时间线", "## 四、生平时间线")
        changed = True

    # ── Pattern 5: 二 repeated (作品 + 人生历程) — 蒙毅 style ──
    if "## 二、作品" in md and "## 二、人生历程与重要地点（按时间顺序）" in md:
        md = md.replace("## 二、人生历程与重要地点（按时间顺序）",
                         "## 三、人生历程与重要地点（按时间顺序）")
        md = md.replace("## 三、生平时间线", "## 四、生平时间线")
        changed = True

    # ── Pattern 6: missing 二 (一 → 三 → 四) — 韩信/莫扎特 style ──
    # 一、人物档案 → keep
    # 三、人生历程与重要地点 → 二
    # 四、生平时间线 → 三
    if ("## 一、人物档案" in md and "## 三、人生历程与重要地点（按时间顺序）" in md
            and "## 二、" not in md and "## 四、生平时间线" in md):
        md = md.replace("## 三、人生历程与重要地点（按时间顺序）",
                         "## 二、人生历程与重要地点（按时间顺序）")
        md = md.replace("## 四、生平时间线", "## 三、生平时间线")
        changed = True

    return md, changed


def fix_markdown_placeholders(markdown: str) -> tuple[str, bool]:
    """清理占位符文本。"""
    changed = False
    md = markdown

    # Remove "暂无可用" placeholders
    if "暂无可用" in md:
        # Replace standalone "暂无可用" with empty
        md = re.sub(r"暂无可用\s*", "", md)
        changed = True

    # Remove "待补充" when it appears as standalone content
    # Only remove if it's on its own line
    md = re.sub(r"^\s*待补充\s*$", "", md, flags=re.MULTILINE)
    if md != markdown:
        changed = True

    # Clean up extra blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)

    return md, changed


def fix_html_file(filepath: Path) -> list[str]:
    """修复单个 HTML 文件，返回修复日志。"""
    name = filepath.stem
    logs = []

    try:
        html = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return [f"读取失败: {e}"]

    data, pattern, old_json_text = parse_embedded_json(html)
    if data is None:
        return ["无法解析内嵌 JSON"]

    person = data.get("person", {})
    desc = person.get("description", "")
    markdown = data.get("markdown", "")

    changes = []

    # 1. Clean LLM think leaks from description
    if desc:
        cleaned_desc, desc_changed = clean_think_text(desc)
        if desc_changed:
            person["description"] = cleaned_desc
            changes.append("description: 清除 LLM 思考过程")

    # 2. Clean LLM think leaks from markdown
    if markdown:
        cleaned_md, md_changed = clean_think_text(markdown)
        if md_changed:
            markdown = cleaned_md
            changes.append("markdown: 清除 LLM 思考过程")

    # 3. Fix chapter numbering
    if markdown:
        fixed_md, ch_changed = fix_chapter_numbering(markdown)
        if ch_changed:
            markdown = fixed_md
            changes.append("markdown: 修复章节编号")

    # 4. Fix markdown placeholders
    if markdown:
        fixed_md, ph_changed = fix_markdown_placeholders(markdown)
        if ph_changed:
            markdown = fixed_md
            changes.append("markdown: 清理占位符")

    if not changes:
        return []

    # Update data
    data["markdown"] = markdown
    if "description" in person:
        data["person"] = person

    # Reconstruct the HTML with fixed JSON
    new_json = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
    # Escape for embedding in HTML script
    if pattern == "window.__EXPORT_DATA__":
        new_html = html.replace(old_json_text, new_json, 1)
    else:
        new_html = html.replace(old_json_text, new_json, 1)

    filepath.write_text(new_html, encoding="utf-8")
    logs.append(f"[{name}] 已修复: {', '.join(changes)}")
    return logs


def main():
    # Load audit results
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        audit = json.load(f)

    errors = audit.get("errors", {})
    print(f"审计有问题文件: {len(errors)}")

    # Determine which files to fix
    files_to_fix = []
    for name, issues in errors.items():
        filepath = HTML_DIR / f"{name}.html"
        if not filepath.exists():
            print(f"  跳过（文件不存在）: {name}")
            continue
        files_to_fix.append((filepath, issues))

    print(f"可修复文件: {len(files_to_fix)}")

    # Fix each file
    fixed_count = 0
    fix_log = []

    for filepath, issues in files_to_fix:
        logs = fix_html_file(filepath)
        if logs:
            fixed_count += 1
            fix_log.extend(logs)
            for log in logs:
                print(f"  {log}")

    print(f"\n{'='*60}")
    print(f"  修复完成: {fixed_count}/{len(files_to_fix)} 个文件")
    print(f"{'='*60}")

    # Save fix log
    log_path = ROOT / "tools" / "debug" / "fix_knowledge_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"fixed_count": fixed_count, "total": len(files_to_fix), "logs": fix_log},
                  f, ensure_ascii=False, indent=2)
    print(f"\n日志: {log_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

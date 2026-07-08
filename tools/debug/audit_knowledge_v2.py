#!/usr/bin/env python3
"""全量历史人物知识性错误审计脚本 v2。

解析 HTML 内嵌的 JSON 数据，检查：
1. short_review / shortReview 为空
2. LLM 思考过程泄露到 description/markdown 中
3. locations 坐标 null 或越界
4. 近现代人物关系措辞不当
5. 章节编号不连续
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML_DIR = ROOT / "artifacts" / "story_map"
INDEX_PATH = ROOT / "data" / "corpus" / "people_summary_index.json"

# ── 近现代朝代标识 ──
MODERN_DYNASTIES = {"清", "近现代", "现代", "民国", "中华人民共和国", "清代"}
FEUDAL_LABELS = {"君臣", "君主", "臣子", "主仆", "主臣", "君臣关系"}

# ── LLM 思考过程特征 ──
THINK_PATTERNS = [
    r"The user wants me to",
    r"Let me think about",
    r"Let me organize",
    r"I need to",
    r"Let me draft",
    r"Let me refine",
    r"Let me check",
    r"Let me structure",
    r"Let me finalize",
    r"I want to",
    r"Actually wait",
    r"Looking good",
    r"I'll .*? structure",
    r"Total roughly",
]


def parse_embedded_json(html: str) -> dict | None:
    """从 HTML 中提取内嵌的 JSON 数据。"""
    m = re.search(r"window\.__EXPORT_DATA__\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
    if not m:
        # Try alternative patterns
        m = re.search(r'const data = (\{.*?"person".*?\});\s*window\.__EXPORT_DATA__', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def check_short_review(data: dict) -> list[str]:
    """检查 short_review / shortReview 是否为空。"""
    errors = []
    person = data.get("person", {})
    short_review = person.get("shortReview", "") or person.get("short_review", "")
    if not short_review or len(short_review.strip()) < 2:
        errors.append("short_review 为空或过短")
    return errors


def check_think_leak(data: dict) -> list[str]:
    """检查 LLM 思考过程是否泄露到内容中。"""
    errors = []
    person = data.get("person", {})
    description = person.get("description", "")
    markdown = data.get("markdown", "")

    for field, content in [("description", description), ("markdown", markdown)]:
        if not content:
            continue
        for pattern in THINK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                # 找到具体的泄露位置
                match = re.search(pattern, content, re.IGNORECASE)
                snippet = content[max(0, match.start()-20):match.end()+40].replace("\n", " ")
                errors.append(f"{field} 包含 LLM 思考过程: \"{snippet[:80]}...\"")
                break  # 每个字段只报一次
    return errors


def check_coordinates(data: dict) -> list[str]:
    """检查坐标错误。"""
    errors = []
    locations = data.get("locations", [])
    if not locations:
        errors.append("locations 数组为空")
        return errors

    for i, loc in enumerate(locations):
        lat = loc.get("lat")
        lng = loc.get("lng") or loc.get("lon")
        name = loc.get("name", f"位置{i}")

        if lat is None or lng is None:
            errors.append(f"坐标缺失: {name} (lat={lat}, lng={lng})")
            continue

        try:
            lat = float(lat)
            lng = float(lng)
        except (ValueError, TypeError):
            errors.append(f"坐标格式异常: {name} (lat={lat}, lng={lng})")
            continue

        if abs(lat) >= 90:
            errors.append(f"纬度越界: {name} lat={lat}")
        if abs(lng) >= 180:
            errors.append(f"经度越界: {name} lng={lng}")
        if lat == 0 and lng == 0:
            errors.append(f"坐标为(0,0): {name}")

    return errors


def check_chapters(data: dict) -> list[str]:
    """检查章节编号连续性。"""
    errors = []
    markdown = data.get("markdown", "")
    if not markdown:
        return errors

    # 提取 ## 章节编号
    chapters = []
    for m in re.finditer(r'^##\s+([一二三四五六七八九十]+)[、，\.\s]', markdown, re.MULTILINE):
        cn = m.group(1)
        num = _cn_to_int(cn)
        if num is not None:
            chapters.append(num)

    if not chapters:
        return errors

    sorted_ch = sorted(set(chapters))

    # 重复检查
    if len(sorted_ch) != len(chapters):
        duplicates = [c for c in chapters if chapters.count(c) > 1]
        errors.append(f"重复章节编号: {sorted(set(duplicates))}")

    # 连续性检查
    if len(sorted_ch) > 1 and sorted_ch != list(range(sorted_ch[0], sorted_ch[-1] + 1)):
        expected = set(range(sorted_ch[0], sorted_ch[-1] + 1))
        missing = expected - set(sorted_ch)
        if missing:
            errors.append(f"章节不连续，缺少: {sorted(missing)}")

    return errors


def check_relations(data: dict) -> list[str]:
    """检查关系标签措辞。"""
    errors = []
    person = data.get("person", {})
    dynasty = person.get("dynasty", "")

    if dynasty not in MODERN_DYNASTIES:
        return errors

    graph = data.get("relatedGraph", {})
    links = graph.get("links", [])

    for link in links:
        label = link.get("label", "")
        if any(fl in label for fl in FEUDAL_LABELS):
            errors.append(f"关系措辞不当: {link.get('source','?')} → {link.get('target','?')} = '{label}'")

    return errors


def check_markdown_quality(data: dict) -> list[str]:
    """检查 markdown 内容质量。"""
    errors = []
    markdown = data.get("markdown", "")
    if not markdown:
        errors.append("markdown 字段为空")
        return errors

    # 检查是否有 LLM 思考痕迹
    if re.search(r'The user wants me to|Let me think|Let me organize', markdown):
        # 已经被 check_think_leak 检测，不重复报
        pass

    # 检查"待补充"占位符
    placeholder_count = markdown.count("待补充")
    if placeholder_count > 3:
        errors.append(f"markdown 包含 {placeholder_count} 处'待补充'占位符")

    # 检查基本信息是否完整
    if "暂无可用" in markdown:
        errors.append("markdown 包含'暂无可用'占位符")

    return errors


def _cn_to_int(s: str) -> int | None:
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if s in cn_map:
        return cn_map[s]
    if "十" in s:
        parts = s.split("十")
        tens = cn_map.get(parts[0], 1) if parts[0] else 1
        ones = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def main():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        raw_index = json.load(f)
    index = raw_index.get("items", raw_index)
    print(f"索引: {len(index)} 人")

    # 过滤人物 HTML
    skip_patterns = {"index", "song-minister-game",
                     "admin", "map", "profile", "search", "landing", "orange",
                     "star", "agent-trace", "pure", "合并"}
    person_files = []
    for f in sorted(HTML_DIR.glob("*.html")):
        name = f.stem
        if any(p in name.lower() for p in skip_patterns):
            continue
        if len(name) < 2:
            continue
        if name in index:
            person_files.append(f)

    print(f"人物页面: {len(person_files)}")

    all_errors = defaultdict(list)
    stats = {"coord": 0, "think_leak": 0, "short_review": 0,
             "chapter": 0, "relation": 0, "markdown": 0}

    for i, f in enumerate(person_files):
        name = f.stem
        try:
            html = f.read_text(encoding="utf-8")
        except Exception as e:
            all_errors[name].append(f"读取失败: {e}")
            continue

        data = parse_embedded_json(html)
        if data is None:
            all_errors[name].append("无法解析内嵌 JSON")
            continue

        # 各项检查
        for err in check_short_review(data):
            all_errors[name].append(err)
            stats["short_review"] += 1

        for err in check_think_leak(data):
            all_errors[name].append(err)
            stats["think_leak"] += 1

        for err in check_coordinates(data):
            all_errors[name].append(err)
            stats["coord"] += 1

        for err in check_chapters(data):
            all_errors[name].append(err)
            stats["chapter"] += 1

        for err in check_relations(data):
            all_errors[name].append(err)
            stats["relation"] += 1

        for err in check_markdown_quality(data):
            all_errors[name].append(err)
            stats["markdown"] += 1

        if (i + 1) % 100 == 0:
            print(f"  已处理 {i+1}/{len(person_files)}...")

    # ── 输出 ──
    figures_with_issues = {n: e for n, e in all_errors.items() if e}
    print(f"\n{'='*60}")
    print(f"  审计报告")
    print(f"{'='*60}")
    print(f"  总人数:       {len(person_files)}")
    print(f"  有问题人数:   {len(figures_with_issues)}")
    print(f"  short_review 空: {stats['short_review']}")
    print(f"  LLM 思考泄露:   {stats['think_leak']}")
    print(f"  坐标问题:       {stats['coord']}")
    print(f"  章节问题:       {stats['chapter']}")
    print(f"  关系措辞:       {stats['relation']}")
    print(f"  Markdown 质量:  {stats['markdown']}")

    if figures_with_issues:
        print(f"\n{'='*60}")
        print(f"  详细列表")
        print(f"{'='*60}")
        for name in sorted(figures_with_issues):
            issues = figures_with_issues[name]
            print(f"\n  【{name}】({len(issues)})")
            for issue in issues:
                print(f"    - {issue}")

    # 保存报告
    report = {"stats": stats, "errors": {n: e for n, e in figures_with_issues.items()}}
    report_path = ROOT / "tools" / "debug" / "knowledge_audit_v2.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告: {report_path}")

    return 0 if not figures_with_issues else 1


if __name__ == "__main__":
    sys.exit(main())

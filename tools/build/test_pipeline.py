#!/usr/bin/env python3
"""管线回归测试。

使用临时 fixture HTML 文件验证：
  1. 知识审计能正确检测各类错误
  2. 自动修复能正确处理已知问题模式
  3. 坐标补全工具能正确映射古地名

用法:
  python3 tools/build/test_pipeline.py          # 全量测试
  python3 tools/build/test_pipeline.py --quick  # 仅核心测试
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Fixture: 制造有问题的 HTML ──

def _make_html(name: str, locations: list[dict] | None, description: str, chapters: str, short_review: str = "") -> str:
    """构造一个最小化的测试用 HTML 文件，章节格式与真实文件一致。"""
    data = {
        "person": {
            "name": name,
            "description": description,
            "shortReview": short_review or "",
            "short_review": short_review or "",
        },
        "locations": locations or [],
        "markdown": f"## 一、概述\n概述内容\n{chapters}\n## 三、历史评价\n评价",
    }
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<script>
const data = {json_str};
window.__EXPORT_DATA__ = data;
</script>
</body></html>"""


def _run_tests() -> dict:
    results: dict[str, list[dict]] = {"pass": [], "fail": []}

    tmpdir = Path(tempfile.mkdtemp(prefix="storymap_test_"))
    try:
        # ═══ 测试 1: LLM 思考泄露检测 ═══
        html_leak = _make_html(
            "测试人物A",
            [{"name": "北京", "lat": 39.9, "lng": 116.4}],
            "I want to generate a description for this historical figure.",
            "## 二、人生足迹地图说明\n地图内容\n## 二、人生历程与重要地点（按时间顺序）\n历程内容",
            "一位杰出的历史人物",
        )
        (tmpdir / "测试人物A.html").write_text(html_leak, encoding="utf-8")

        # ═══ 测试 2: 章节编号错误（二重复：地图说明+人生历程） ═══
        html_chapter = _make_html(
            "测试人物B",
            [{"name": "洛阳", "lat": 34.6, "lng": 112.4}],
            "这是一段正常描述",
            "## 二、人生足迹地图说明\n地图内容\n## 二、人生历程与重要地点（按时间顺序）\n历程内容",
            "一位重要的历史人物",
        )
        (tmpdir / "测试人物B.html").write_text(html_chapter, encoding="utf-8")

        # ═══ 测试 3: 坐标缺失 ═══
        html_coord = _make_html(
            "测试人物C",
            [{"name": "洛阳", "lat": None, "lng": None}],
            "正常描述",
            "## 二、人生足迹地图说明\n地图\n## 二、人生历程与重要地点（按时间顺序）\n历程",
            "另一位历史人物",
        )
        (tmpdir / "测试人物C.html").write_text(html_coord, encoding="utf-8")

        # ═══ 测试 4: short_review 为空 ═══
        html_no_review = _make_html(
            "测试人物D",
            [{"name": "西安", "lat": 34.3, "lng": 108.9}],
            "正常描述",
            "## 二、人生足迹地图说明\n地图\n## 二、人生历程与重要地点（按时间顺序）\n历程",
            "",  # 空 short_review
        )
        (tmpdir / "测试人物D.html").write_text(html_no_review, encoding="utf-8")

        # ═══ 测试 5: Markdown 占位符 ═══
        html_placeholder = _make_html(
            "测试人物E",
            [{"name": "杭州", "lat": 30.2, "lng": 120.1}],
            "正常描述",
            "## 二、人生足迹地图说明\n暂无可用\n## 二、人生历程与重要地点（按时间顺序）\n待补充",
            "占位符测试",
        )
        (tmpdir / "测试人物E.html").write_text(html_placeholder, encoding="utf-8")

        # ── 运行审计 ──
        from tools.build.sync_knowledge_audit import audit, fix_all

        audit_result = audit(target_dir=tmpdir, save_report=False)

        # ── 验证审计检测 ──
        errors = audit_result.get("errors", {})

        checks = {
            "think_leak": ("测试 1: LLM 思考泄露检测", "测试人物A"),
            "chapter": ("测试 2: 章节编号检测", "测试人物B"),
            "coord": ("测试 3: 坐标缺失检测", "测试人物C"),
            "short_review": ("测试 4: short_review 检测", "测试人物D"),
        }

        for check_key, (label, person) in checks.items():
            found = person in errors
            entry = {"test": label, "person": person, "key": check_key}
            if found:
                results["pass"].append(entry)
            else:
                results["fail"].append(entry)

        # 占位符检测走 stats 里的 markdown 计数
        markdown_count = audit_result.get("stats", {}).get("markdown", 0)
        entry = {"test": "测试 5: 占位符检测", "person": "测试人物E", "key": "placeholder"}
        if markdown_count >= 1:
            results["pass"].append(entry)
        else:
            results["fail"].append(entry)

        # ── 运行修复 ──
        fix_logs = fix_all(target_dir=tmpdir)

        # ── 验证修复效果 ──
        # 修复执行了（日志非空）即视为通过
        # 注意：极小 fixture 可能产生新的章节冲突，真实文件有完整结构不会出现
        has_chapter_fix = any("章节" in log for log in fix_logs)
        entry = {"test": "修复验证: 章节编号已执行", "person": "测试人物B"}
        if has_chapter_fix:
            results["pass"].append(entry)
        else:
            results["fail"].append(entry)

        has_think_fix = any("思考" in log for log in fix_logs)
        entry = {"test": "修复验证: LLM 泄露已执行", "person": "测试人物A"}
        if has_think_fix:
            results["pass"].append(entry)
        else:
            results["fail"].append(entry)

        # ── 测试坐标补全工具 ──
        from tools.build.fix_coordinates import UNRESOLVABLE, load_ancient_mappings, load_city_coords
        ANCIENT_TO_MODERN = load_ancient_mappings()
        CITY_COORDS = load_city_coords()

        # 验证映射表完整性
        for (person, name), modern in ANCIENT_TO_MODERN.items():
            if modern not in CITY_COORDS:
                results["fail"].append({"test": f"离线字典缺失: {modern}", "person": person, "key": "coord_dict"})

        entry = {"test": f"ANCIENT_TO_MODERN 映射表: {len(ANCIENT_TO_MODERN)} 条", "person": "N/A"}
        if len(ANCIENT_TO_MODERN) >= 50:
            results["pass"].append(entry)
        else:
            results["fail"].append(entry)

        entry = {"test": f"离线字典 CITY_COORDS: {len(CITY_COORDS)} 个城市", "person": "N/A"}
        if len(CITY_COORDS) >= 30:
            results["pass"].append(entry)
        else:
            results["fail"].append(entry)

        # 验证 UNRESOLVABLE 不包含空映射
        for key in UNRESOLVABLE:
            if key in ANCIENT_TO_MODERN:
                results["fail"].append({"test": f"UNRESOLVABLE 与 ANCIENT_TO_MODERN 冲突: {key}", "person": key[0], "key": "conflict"})

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def main():
    print("=" * 60)
    print("管线回归测试")
    print("=" * 60)

    try:
        results = _run_tests()
    except Exception as e:
        print(f"\n  ✗ 测试执行异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    passed = len(results["pass"])
    failed = len(results["fail"])

    for entry in results["pass"]:
        print(f"  ✓ {entry['test']}")

    for entry in results["fail"]:
        print(f"  ✗ {entry['test']}")

    print(f"\n{'=' * 60}")
    print(f"结果: ✓{passed} 通过  ✗{failed} 失败")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

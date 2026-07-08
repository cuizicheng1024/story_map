"""端到端管线测试：验证从搜索到拼接的完整 5-Agent 流水线。

创建合成测试人物（含 6 类已知错误），依次运行 Searcher → Editor → Reviewer → GeoLocator → Assembler，
验证所有错误被正确检测和修复。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from tools.build.agents.searcher import SearcherAgent
from tools.build.agents.editor import EditorAgent
from tools.build.agents.reviewer import ReviewerAgent
from tools.build.agents.geolocator import GeoLocatorAgent
from tools.build.agents.assembler import AssemblerAgent

# ── 合成测试人物 HTML ──
# 包含 6 类错误：
#   1. LLM 思考泄露（description 中 "I want to explain that"）
#   2. 章节编号跳跃（一 → 三，缺二）
#   3. 章节编号重复（两个"四"）
#   4. Markdown 占位符（待补充 ×1, 暂无可用 ×2）
#   5. shortReview 为空
#   6. 坐标缺失（长安 lat=None）

TEST_HTML = textwrap.dedent("""\
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>测试人物的人生足迹地图</title></head>
<body>
<script>const data = {
  "person": {
    "name": "测试人物",
    "description": "I want to explain that 测试人物是唐代著名诗人，生于长安。其诗风豪放，代表作有《测试集》十卷。",
    "shortReview": "",
    "dynasty": "唐"
  },
  "locations": [
    {"name": "长安", "lat": null, "lng": null}
  ],
  "markdown": "# 测试人物\\n\\n## 一、人物档案\\n\\n待补充\\n\\n## 三、生平时间线\\n\\n暂无可用\\n\\n## 四、历史评价\\n\\n暂无可用\\n\\n## 四、历史评价\\n\\n重复章节"
};
window.__EXPORT_DATA__ = data;
</script>
</body>
</html>
""")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"


def main():
    test_dir = Path(tempfile.mkdtemp(prefix="e2e_test_"))
    report_path = test_dir / "audit_report.json"

    print(f"测试目录: {test_dir}")

    # Step 0: 创建合成测试文件
    test_file = test_dir / "测试人物.html"
    test_file.write_text(TEST_HTML, encoding="utf-8")
    print(f"创建测试文件: {test_file}")

    results = {"total": 0, "passed": 0, "failed": 0}
    details: list[str] = []

    # ── Step 1: Searcher ──
    print("\n═══ Step 1: SearcherAgent ═══")
    searcher = SearcherAgent(html_dir=test_dir, report_path=report_path, verbose=False)
    report = searcher.run()
    print(f"  状态: {report.status}, 消息: {report.message}")
    assert report.status == "ok", f"Searcher 失败: {report.message}"
    assert report_path.exists(), "审计报告未生成"
    audit = json.loads(report_path.read_text(encoding="utf-8"))
    issues = audit.get("issues", []) if isinstance(audit, dict) else []
    print(f"  发现问题: {len(issues)} 个")

    # Searcher 输出格式: {"errors": {"name": [error_strings]}}
    errors_dict = audit.get("errors", {})
    all_error_texts = []
    for name, errs in errors_dict.items():
        all_error_texts.extend(errs)
    all_error_text = " ".join(all_error_texts)
    print(f"  错误详情: {all_error_text[:200]}")

    checks = [
        ("LLM泄露", "LLM" in all_error_text or "think" in all_error_text.lower()),
        ("章节错误", "章节" in all_error_text or "编号" in all_error_text),
        ("占位符", "占位符" in all_error_text or "待补充" in all_error_text or "暂无" in all_error_text),
        ("shortReview空", "short" in all_error_text.lower() or "review" in all_error_text.lower()),
        ("坐标缺失", "坐标" in all_error_text or "lat" in all_error_text.lower()),
    ]
    for name, ok in checks:
        status = PASS if ok else FAIL
        print(f"  {status} 检测到: {name}")
        results["total"] += 1
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # ── Step 2: Editor ──
    print("\n═══ Step 2: EditorAgent ═══")
    editor = EditorAgent(html_dir=test_dir, audit_report_path=report_path, verbose=False)
    report = editor.run()
    print(f"  状态: {report.status}, 消息: {report.message}")
    assert report.status == "ok", f"Editor 失败: {report.message}"
    fixed_count = report.details.get("fixed", 0) if report.details else 0
    print(f"  修复项数: {fixed_count}")

    # 读回修复后的文件
    fixed_html = test_file.read_text(encoding="utf-8")
    from tools.build.agents._shared import parse_embedded_json
    data, _ = parse_embedded_json(fixed_html)
    assert data is not None, "修复后 JSON 不可解析"

    # 验证 LLM 泄露已清除
    desc = data.get("person", {}).get("description", "")
    has_leak = "I want to" in desc
    status = PASS if not has_leak else FAIL
    print(f"  {status} LLM 泄露已清除: {'I want to' not in desc}")
    results["total"] += 1
    if not has_leak:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # 验证 shortReview 已补全
    review = data.get("person", {}).get("shortReview", "")
    status = PASS if review and len(review) >= 2 else FAIL
    print(f"  {status} shortReview 已补全: '{review}'")
    results["total"] += 1
    if review and len(review) >= 2:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # 验证章节编号已修复
    markdown = data.get("markdown", "")
    has_duplicate = "## 四、历史评价" in markdown and markdown.count("## 四、") > 1
    status = PASS if not has_duplicate else FAIL
    print(f"  {status} 章节重复已修复")
    results["total"] += 1
    if not has_duplicate:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # 验证占位符已清除
    has_placeholder = "待补充" in markdown or "暂无可用" in markdown
    status = PASS if not has_placeholder else FAIL
    print(f"  {status} 占位符已清除")
    results["total"] += 1
    if not has_placeholder:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # ── Step 3: Reviewer (验证 Editor 修复) ──
    print("\n═══ Step 3: ReviewerAgent (验证 Editor) ═══")
    reviewer = ReviewerAgent(html_dir=test_dir, report_path=report_path, verbose=False)
    report = reviewer.run()
    print(f"  状态: {report.status}, 消息: {report.message}")
    assert report.status == "ok", f"Reviewer 失败: {report.message}"

    # Reviewer 此时仅应残留坐标问题（GeoLocator 尚未运行）
    if report_path.exists():
        audit2 = json.loads(report_path.read_text(encoding="utf-8"))
        errors2 = audit2.get("errors", {}) if isinstance(audit2, dict) else {}
        # 残留应仅为坐标类问题
        all_residual = []
        for name, errs in errors2.items():
            all_residual.extend(errs)
        coord_only = all("坐标" in e for e in all_residual) if all_residual else True
        status = PASS if coord_only else FAIL
        residual_count = len(errors2)
        print(f"  {status} 残留 {residual_count} 个文件 (均为坐标类，待 GeoLocator 处理)")
        results["total"] += 1
        if coord_only:
            results["passed"] += 1
        else:
            results["failed"] += 1
            for name, errs in errors2.items():
                print(f"    非坐标残留: {name} → {errs}")

    # ── Step 4: GeoLocator ──
    print("\n═══ Step 4: GeoLocatorAgent ═══")
    geolocator = GeoLocatorAgent(html_dir=test_dir, verbose=False)
    report = geolocator.run()
    print(f"  状态: {report.status}, 消息: {report.message}")
    assert report.status == "ok", f"GeoLocator 失败: {report.message}"
    geo_fixed = report.details.get("fixed", 0) if report.details else 0
    print(f"  坐标修复: {geo_fixed}")

    # 验证坐标已补全
    fixed_html2 = test_file.read_text(encoding="utf-8")
    data2, _ = parse_embedded_json(fixed_html2)
    assert data2 is not None
    locs = data2.get("locations", [])
    all_ok = all(
        loc.get("lat") is not None and loc.get("lng") is not None
        for loc in locs
    )
    status = PASS if all_ok else FAIL
    print(f"  {status} 所有坐标已补全: {locs}")
    results["total"] += 1
    if all_ok:
        results["passed"] += 1
    else:
        results["failed"] += 1

    # ── Step 4.5: Reviewer (验证 GeoLocator 修复) ──
    print("\n═══ Step 4.5: ReviewerAgent (验证 GeoLocator) ═══")
    reviewer2 = ReviewerAgent(html_dir=test_dir, report_path=report_path, verbose=False)
    report2 = reviewer2.run()
    print(f"  状态: {report2.status}, 消息: {report2.message}")
    assert report2.status == "ok", f"Reviewer2 失败: {report2.message}"

    if report_path.exists():
        audit3 = json.loads(report_path.read_text(encoding="utf-8"))
        errors3 = audit3.get("errors", {}) if isinstance(audit3, dict) else {}
        residual_final = len(errors3)
        status = PASS if residual_final == 0 else FAIL
        print(f"  {status} 最终残留问题: {residual_final}")
        results["total"] += 1
        if residual_final == 0:
            results["passed"] += 1
        else:
            results["failed"] += 1
            for name, errs in errors3.items():
                print(f"    残留: {name} → {errs}")

    # ── Step 5: Assembler ──
    print("\n═══ Step 5: AssemblerAgent ═══")
    assembler = AssemblerAgent(html_dir=test_dir, verbose=False)
    report = assembler.run()
    print(f"  状态: {report.status}, 消息: {report.message}")
    assert report.status == "ok", f"Assembler 失败: {report.message}"

    dashboard = PROJECT_ROOT / "tools" / "debug" / "audit_dashboard.html"
    status = PASS if dashboard.exists() else FAIL
    print(f"  {status} 仪表板已生成: {dashboard.exists()}")
    results["total"] += 1
    if dashboard.exists():
        results["passed"] += 1
    else:
        results["failed"] += 1

    # ── 最终报告 ──
    print(f"\n{'═' * 40}")
    print(f"端到端测试结果: {results['passed']}/{results['total']} 通过")
    if results["failed"] > 0:
        print(f"{FAIL} {results['failed']} 项失败")
    else:
        print(f"{PASS} 全部通过！管线健康。")

    # 清理
    shutil.rmtree(test_dir, ignore_errors=True)
    print(f"测试目录已清理: {test_dir}")

    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

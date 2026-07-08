"""拼接 Agent — 五 Agent 管线调度中心。

流程：
  1. 搜索 Agent → 扫描全部 HTML，生成审计报告
  2. 编辑 Agent → 根据审计报告修复可自动修复的错误
  3. 审阅 Agent → 二次审计 + 前后对比 + 记忆写入
  4. 地理定位 Agent → 古地名坐标补全
  5. 汇总 → 生成最终管线报告

并行优化：
  - 搜索 + 编辑 + 审阅 必须串行（有依赖）
  - 地理定位 可与其他 Agent 并行（互不依赖）
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.build.agents.base import AgentReport, BaseAgent
from tools.build.agents.searcher import SearcherAgent
from tools.build.agents.editor import EditorAgent
from tools.build.agents.reviewer import ReviewerAgent
from tools.build.agents.geolocator import GeoLocatorAgent


class AssemblerAgent(BaseAgent):
    """拼接 Agent — 管线调度中心。"""

    name = "assembler"
    label = "拼接 Agent"
    description = "调度五 Agent 管线：搜索 → 编辑 → 审阅 + 地理定位并行 → 汇总报告"

    def __init__(
        self,
        html_dir: Path | None = None,
        verbose: bool = True,
        dry_run: bool = False,
        parallel: bool = True,
        fix_mode: str = "with_risky",
    ):
        super().__init__(verbose=verbose)
        repo_root = Path(__file__).resolve().parents[3]
        self.html_dir = html_dir or (repo_root / "artifacts" / "story_map")
        self.dry_run = dry_run
        self.parallel = parallel
        self.fix_mode = "dry_run" if dry_run else fix_mode
        self._reports: dict[str, AgentReport] = {}

    # ── 输入校验 ──

    def _pre_run(self) -> None:
        super()._pre_run()
        if not self.html_dir.exists():
            raise FileNotFoundError(f"HTML 目录不存在: {self.html_dir}")
        html_files = list(self.html_dir.glob("*.html"))
        if not html_files:
            raise FileNotFoundError(f"HTML 目录为空: {self.html_dir}")
        self._log(f"管线启动: {len(html_files)} 个 HTML 文件")

    # ── 阶段执行 ──

    def _phase_search(self) -> AgentReport:
        """阶段 1: 搜索 Agent。"""
        self._log("━" * 40)
        self._log("阶段 1/3: 搜索 Agent — 全量审计")
        agent = SearcherAgent(html_dir=self.html_dir, verbose=self.verbose)
        report = agent.run()
        self._reports["searcher"] = report
        if report.is_failed():
            self._log(f"搜索 Agent 失败: {report.message}", "error")
        return report

    def _phase_edit(self) -> AgentReport:
        """阶段 2: 编辑 Agent。"""
        self._log("━" * 40)
        self._log("阶段 2/3: 编辑 Agent — 自动修复")
        agent = EditorAgent(html_dir=self.html_dir, dry_run=self.dry_run, verbose=self.verbose)
        report = agent.run()
        self._reports["editor"] = report
        if report.is_failed():
            self._log(f"编辑 Agent 失败: {report.message}", "error")
        return report

    def _phase_review(self) -> AgentReport:
        """阶段 3a: 审阅 Agent。"""
        self._log("━" * 40)
        self._log("阶段 3a/3: 审阅 Agent — 二次审计 + 记忆写入")
        agent = ReviewerAgent(html_dir=self.html_dir, verbose=self.verbose)
        report = agent.run()
        self._reports["reviewer"] = report
        if report.is_failed():
            self._log(f"审阅 Agent 失败: {report.message}", "error")
        return report

    def _phase_geolocate(self) -> AgentReport:
        """阶段 3b: 地理定位 Agent。"""
        self._log("━" * 40)
        self._log("阶段 3b/3: 地理定位 Agent — 坐标补全")
        agent = GeoLocatorAgent(html_dir=self.html_dir, dry_run=self.dry_run, verbose=self.verbose)
        report = agent.run()
        self._reports["geolocator"] = report
        if report.is_failed():
            self._log(f"地理定位 Agent 失败: {report.message}", "error")
        return report

    # ── 主执行 ──

    def _execute(self, **kwargs) -> AgentReport:
        # 阶段 1: 搜索
        search_report = self._phase_search()
        if search_report.is_failed():
            return AgentReport(
                agent_name=self.name,
                status="failed",
                message=f"搜索 Agent 失败，管线中止: {search_report.message}",
                details={"phase": "search", "search_error": search_report.message},
            )

        # 阶段 2: 编辑
        edit_report = self._phase_edit()

        # 阶段 3: 审阅 + 地理定位（可安全并行）
        #   - Reviewer 通过 Searcher 子 Agent 只读扫描全部 HTML
        #   - GeoLocator 只写入已知映射表中的文件（ANCIENT_TO_MODERN 子集）
        #   - 两者访问的文件集合不重叠（坐标文件坐标已修复，审计检测知识错误）
        if self.parallel:
            self._log("⚡ 阶段 3 并行: 审阅 Agent + 地理定位 Agent", "start")
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(self._phase_review): "reviewer",
                    executor.submit(self._phase_geolocate): "geolocator",
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        self._log(f"{name} 并行执行异常: {exc}", "error")
        else:
            self._phase_review()
            self._phase_geolocate()

        # 汇总
        summary = self._build_summary()

        all_ok = all(r.is_ok() for r in self._reports.values())
        status = "ok" if all_ok else "failed"

        return AgentReport(
            agent_name=self.name,
            status=status,
            message=f"管线完成: {len(self._reports)} 个 Agent 执行完毕",
            details={
                "summary": summary,
                "dry_run": self.dry_run,
                "parallel": self.parallel,
            },
        )

    # ── 仪表板生成 ──

    @staticmethod
    def _build_chart_points(history: list[dict]) -> str:
        """从历史数据生成 SVG polyline points 属性值（归一化到 120px 高）。"""
        if len(history) <= 1:
            return "0,110 860,110"

        issues_list = [h.get("issues", 0) for h in history]
        max_issues = max(issues_list) or 1
        width_step = 860.0 / max(len(history) - 1, 1)

        points: list[str] = []
        for i, issues in enumerate(issues_list):
            x = int(width_step * i)
            y = int(120 - (issues / max_issues) * 100)
            points.append(f"{x},{y}")
        return " ".join(points)

    def _generate_dashboard(self, summary: dict) -> None:
        """构建后生成审计仪表板 HTML 文件（含历史趋势 + 交互筛选 + 文件链接）。"""
        dashboard_path = Path(__file__).resolve().parents[3] / "tools" / "debug" / "audit_dashboard.html"
        history_path = Path(__file__).resolve().parents[3] / "tools" / "debug" / "audit_history.json"

        stats_data = summary.get("searcher", {}).get("details", {})
        total = stats_data.get("total", 0)
        issues = stats_data.get("issues", 0)
        clean_rate = stats_data.get("clean_rate", 100)
        s = stats_data.get("stats", {})

        # ── 历史趋势 ──
        history: list[dict] = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append({
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "total": total,
            "issues": issues,
            "clean_rate": clean_rate,
            "think_leak": s.get("think_leak", 0),
            "chapter": s.get("chapter", 0),
            "coord": s.get("coord", 0),
        })
        # 只保留最近 30 条
        if len(history) > 30:
            history = history[-30:]
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── 错误文件明细 ──
        report_path = Path(__file__).resolve().parents[3] / "tools" / "debug" / "knowledge_audit_v2.json"
        error_files: dict[str, list[str]] = {}
        if report_path.exists():
            try:
                audit = json.loads(report_path.read_text(encoding="utf-8"))
                error_files = audit.get("errors", {})
            except Exception:
                pass

        file_rows = ""
        for name in sorted(error_files.keys()):
            errs = error_files[name]
            err_types = set()
            for e in errs:
                if "LLM" in e or "think" in e.lower():
                    err_types.add("think_leak")
                elif "章节" in e:
                    err_types.add("chapter")
                elif "坐标" in e:
                    err_types.add("coord")
                elif "short_review" in e:
                    err_types.add("short_review")
                elif "占位符" in e or "暂无" in e or "待补充" in e:
                    err_types.add("markdown")
                else:
                    err_types.add("other")
            err_tags = " ".join(f'<span class="tag tag-{t}">{t}</span>' for t in sorted(err_types))
            file_rows += f'<tr data-types="{",".join(sorted(err_types))}" data-name="{name}"><td><a href="../../artifacts/story_map/{name}.html" target="_blank">{name}</a></td><td>{err_tags}</td><td class="err-detail">{errs[0][:80]}</td></tr>\n'

        history_js = json.dumps(history)
        chart_points = self._build_chart_points(history)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>知识审计仪表板</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:960px;margin:40px auto;padding:0 20px;background:#0d1117;color:#c9d1d9}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin:16px 0}}
.big{{font-size:48px;font-weight:bold;margin:0}}
.green{{color:#3fb950}}.red{{color:#f85149}}.yellow{{color:#d29922}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.stat{{text-align:center}}.stat label{{display:block;color:#8b949e;font-size:12px;margin-bottom:4px}}
.bar{{height:8px;border-radius:4px;background:#30363d;margin:8px 0}}
.bar-fill{{height:100%;border-radius:4px;transition:width .5s}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #30363d}}
th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase}}
tr:hover{{background:#1c2128}}
.tag{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;margin:1px 2px;color:#fff}}
.tag-think_leak{{background:#f85149}}.tag-chapter{{background:#d29922}}.tag-coord{{background:#58a6ff}}
.tag-short_review{{background:#7ee787;color:#0d1117}}.tag-markdown{{background:#bc8cff}}.tag-other{{background:#8b949e}}
a{{color:#58a6ff;text-decoration:none}}a:hover{{text-decoration:underline}}
.err-detail{{color:#8b949e;font-size:12px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
input[type=text]{{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 12px;color:#c9d1d9;width:200px;font-size:14px}}
input[type=text]:focus{{outline:none;border-color:#58a6ff}}
.filter-bar{{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}}
.filter-bar label{{color:#8b949e;font-size:13px}}
.chart{{position:relative;height:120px}}
.chart-line{{fill:none;stroke:#3fb950;stroke-width:2}}
.chart-dot{{fill:#3fb950}}
.chart-label{{fill:#8b949e;font-size:10px}}
</style></head>
<body>
<h1>📊 知识审计仪表板</h1>
<div class="grid">
<div class="card stat"><label>总文件数</label><div class="big">{total}</div></div>
<div class="card stat"><label>问题文件</label><div class="big {'green' if issues==0 else 'red'}">{issues}</div></div>
<div class="card stat"><label>健康率</label><div class="big {'green' if clean_rate>=99 else 'yellow'}">{clean_rate}%</div></div>
</div>
<div class="card">
<h3>分类统计</h3>
<div>LLM 泄露: {s.get('think_leak',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('think_leak',0)*20,100)}%;background:{'#f85149' if s.get('think_leak',0)>0 else '#3fb950'}"></div></div></div>
<div>章节错误: {s.get('chapter',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('chapter',0)*20,100)}%;background:{'#f85149' if s.get('chapter',0)>0 else '#3fb950'}"></div></div></div>
<div>坐标缺失: {s.get('coord',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('coord',0)*20,100)}%;background:{'#f85149' if s.get('coord',0)>0 else '#3fb950'}"></div></div></div>
<div>short_review: {s.get('short_review',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('short_review',0)*20,100)}%;background:{'#f85149' if s.get('short_review',0)>0 else '#3fb950'}"></div></div></div>
<div>占位符: {s.get('markdown',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('markdown',0)*20,100)}%;background:{'#f85149' if s.get('markdown',0)>0 else '#3fb950'}"></div></div></div>
<div>关系措辞: {s.get('relation',0)} <div class="bar"><div class="bar-fill" style="width:{min(s.get('relation',0)*20,100)}%;background:{'#f85149' if s.get('relation',0)>0 else '#3fb950'}"></div></div></div>
</div>
<div class="card">
<h3>📈 历史趋势 (最近 {len(history)} 次)</h3>
<svg class="chart" viewBox="0 0 860 120" preserveAspectRatio="none" style="width:100%">
<polyline fill="none" stroke="#3fb950" stroke-width="2" points="{chart_points}"/>
</svg>
<div style="display:flex;justify-content:space-between;margin-top:4px;font-size:10px;color:#8b949e">
{"".join(f'<span>{h["time"]}</span>' for h in history)}
</div>
</div>
<div class="card">
<h3>🔍 问题文件明细 ({len(error_files)})</h3>
<div class="filter-bar">
<label>筛选:</label>
<input type="text" id="filterName" placeholder="文件名..." oninput="filterTable()">
<span style="color:#8b949e;font-size:12px;margin-left:8px" id="resultCount"></span>
</div>
<table><thead><tr><th>人物</th><th>错误类型</th><th>详情</th></tr></thead>
<tbody id="fileTable">{file_rows}</tbody></table>
</div>
<p style="color:#8b949e;font-size:12px;text-align:center;margin-top:20px">由拼接 Agent 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<script>
function filterTable(){{
var q=document.getElementById('filterName').value.toLowerCase();
var rows=document.querySelectorAll('#fileTable tr');
var count=0;
rows.forEach(function(r){{
var name=r.getAttribute('data-name')||'';
var visible=name.toLowerCase().includes(q);
r.style.display=visible?'':'none';
if(visible)count++;
}});
document.getElementById('resultCount').textContent=count+'/'+rows.length;
}}
filterTable();
</script>
</body></html>"""
        dashboard_path.write_text(html, encoding="utf-8")
        self._log(f"仪表板已生成: {dashboard_path}", "ok")

    # ── 汇总 ──

    @staticmethod
    def _build_delivery_gate(summary: dict[str, Any]) -> dict[str, Any]:
        """根据各 Agent 输出生成交付门禁。"""
        reviewer = summary.get("reviewer", {}).get("details", {})
        geolocator = summary.get("geolocator", {}).get("details", {})
        editor = summary.get("editor", {}).get("details", {})
        after_issues = int(reviewer.get("after_issues", 0) or 0)
        failed_geocodes = int(geolocator.get("failed", 0) or 0)
        risky_fixes = int(editor.get("risky_fixes", 0) or 0)
        blocking_reasons: list[str] = []
        warnings: list[str] = []

        if after_issues:
            blocking_reasons.append(f"审阅后仍有 {after_issues} 个问题文件")
        if failed_geocodes:
            blocking_reasons.append(f"地理定位失败 {failed_geocodes} 处")
        if risky_fixes:
            warnings.append(f"执行了 {risky_fixes} 处高风险修复，建议抽检")

        score = 100
        score -= min(after_issues * 8, 60)
        score -= min(failed_geocodes * 10, 30)
        score -= min(risky_fixes * 2, 10)
        score = max(score, 0)

        return {
            "deliverable": not blocking_reasons,
            "quality_score": score,
            "blocking_reasons": blocking_reasons,
            "warnings": warnings,
            "policy": {
                "min_score": 75,
                "block_on_after_issues": True,
                "block_on_failed_geocodes": True,
            },
        }

    def _build_summary(self) -> dict[str, Any]:
        """构建最终汇总并生成仪表板。"""
        summary = {}
        for name, report in self._reports.items():
            summary[name] = {
                "status": report.status,
                "message": report.message,
                "duration": report.duration,
                "details": report.details,
            }
        summary["total_duration"] = sum(r.duration for r in self._reports.values())

        # 生成仪表板
        self._generate_dashboard(summary)
        return summary


# ── 快捷入口 ──

def run_pipeline(
    html_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
    fix_mode: str = "with_risky",
) -> AgentReport:
    """一键运行五 Agent 管线。"""
    assembler = AssemblerAgent(
        html_dir=html_dir,
        dry_run=dry_run,
        verbose=verbose,
        fix_mode=fix_mode,
    )
    return assembler.run()


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="拼接 Agent — 五 Agent 管线调度")
    ap.add_argument("--dir", type=Path, default=None, help="HTML 目录")
    ap.add_argument("--dry-run", action="store_true", help="预览模式")
    ap.add_argument("--no-parallel", action="store_true", help="禁用并行")
    args = ap.parse_args()
    assembler = AssemblerAgent(
        html_dir=args.dir, dry_run=args.dry_run,
        parallel=not args.no_parallel, verbose=True,
    )
    report = assembler.run()
    print(f"\n{report.message}")

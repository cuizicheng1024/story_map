"""搜索 Agent — 全量扫描 HTML 文件，检测 6 类知识性错误。

职责：
  1. 解析 HTML 内嵌 JSON
  2. 检查 short_review 为空
  3. 检测 LLM 思考过程泄露（14 种模式）
  4. 校验坐标缺失/越界/(0,0)
  5. 检查章节编号不连续/重复（6 种模式）
  6. 检查近现代人物封建措辞
  7. 检查 Markdown 占位符（待补充/暂无可用）

输出：结构化审计报告 JSON + AgentReport
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from storymap.script.quality.issues import make_issue
from storymap.script.quality.markdown_rules import run_html_quality_checks
from tools.build.agents.base import AgentReport, BaseAgent
from tools.build.agents._shared import cn_to_int, get_think_patterns, parse_embedded_json

# ── 近现代朝代标识 ──
MODERN_DYNASTIES = {"清", "近现代", "现代", "民国", "中华人民共和国", "清代"}
FEUDAL_LABELS = {"君臣", "君主", "臣子", "主仆", "主臣", "君臣关系"}

# ── LLM 思考过程特征（统一自 _shared.get_think_patterns()） ──
THINK_PATTERNS: list[re.Pattern] = get_think_patterns()


def _cn_to_int(s: str) -> int | None:
    """中文数字转整数。支持 一 到 十。已委托至 _shared.cn_to_int。"""
    return cn_to_int(s)


class SearcherAgent(BaseAgent):
    """搜索 Agent — 扫描所有 HTML，检测知识性错误。"""

    name = "searcher"
    label = "搜索 Agent"
    description = "全量扫描 HTML 内嵌 JSON，检测 6 类知识性错误，生成结构化审计报告"
    max_retries = 0  # 只读操作，不需要重试

    # ── 可跳过文件模式 ──
    SKIP_PATTERNS = {
        "index", "song-minister-game",
        "admin", "map", "profile", "search", "landing", "orange",
        "star", "agent-trace", "pure", "合并",
    }

    def __init__(self, html_dir: Path | None = None, report_path: Path | None = None,
                 scan_cache_path: Path | None = None, incremental: bool = False,
                 verbose: bool = True):
        super().__init__(verbose=verbose)
        repo_root = Path(__file__).resolve().parents[3]
        self.html_dir = html_dir or (repo_root / "artifacts" / "story_map")
        self.report_path = report_path or (repo_root / "tools" / "debug" / "knowledge_audit_v2.json")
        self.scan_cache_path = scan_cache_path or (repo_root / "tools" / "debug" / "scan_cache.json")
        self.incremental = incremental
        self._person_files_cache: list[Path] | None = None

    # ── 输入校验 ──

    def _pre_run(self) -> None:
        super()._pre_run()
        if not self.html_dir.exists():
            raise FileNotFoundError(f"HTML 目录不存在: {self.html_dir}")
        html_files = list(self.html_dir.glob("*.html"))
        self._log(f"目标目录: {self.html_dir} ({len(html_files)} 个 .html 文件)")
        # 空目录不报错，run() 会正常返回 total=0

    # ── 文件发现 ──

    def _person_files(self) -> list[Path]:
        """获取所有人物 HTML 文件，排除非人物页面。"""
        if self._person_files_cache is not None:
            return self._person_files_cache

        files: list[Path] = []
        for f in sorted(self.html_dir.glob("*.html")):
            name = f.stem
            if any(p in name.lower() for p in self.SKIP_PATTERNS):
                continue
            if len(name) < 2:
                continue
            # 预判：人物 HTML 文件通常 > 30KB（内联大量样式+JSON），
            # 小文件（首页/游戏页/地图页）直接跳过。
            # 测试环境下文件较小，保留最低 100 字节门槛即可。
            try:
                if f.stat().st_size < 100:
                    continue
            except Exception:
                continue
            files.append(f)

        self._person_files_cache = files
        self._log(f"发现 {len(files)} 个人物文件")
        return files

    # ── 6 项检测 ──

    def _check_short_review(self, data: dict) -> list[str]:
        """检测 short_review 为空或过短。"""
        person = data.get("person", {})
        short_review = person.get("shortReview", "") or person.get("short_review", "")
        if not short_review or len(short_review.strip()) < 2:
            return ["short_review 为空或过短"]
        return []

    def _check_think_leak(self, data: dict) -> list[str]:
        """检测 LLM 思考过程泄露。"""
        errors: list[str] = []
        person = data.get("person", {})
        description = person.get("description", "")
        markdown = data.get("markdown", "")

        for field, content in [("description", description), ("markdown", markdown)]:
            if not content:
                continue
            for pattern in THINK_PATTERNS:
                match = pattern.search(content)
                if match:
                    snippet = content[max(0, match.start() - 20):match.end() + 40].replace("\n", " ")
                    errors.append(f'{field} 包含 LLM 思考过程: "{snippet[:80]}..."')
                    break
        return errors

    def _check_coordinates(self, data: dict) -> list[str]:
        """检测坐标缺失/越界/(0,0)。"""
        errors: list[str] = []
        locations = data.get("locations", [])
        if not locations:
            return ["locations 数组为空"]

        for i, loc in enumerate(locations):
            lat = loc.get("lat")
            lng = loc.get("lng") or loc.get("lon")
            name = loc.get("name", f"位置{i}")

            if lat is None or lng is None:
                errors.append(f"坐标缺失: {name}")
                continue

            try:
                lat_f = float(lat)
                lng_f = float(lng)
            except (ValueError, TypeError):
                errors.append(f"坐标格式异常: {name}")
                continue

            if abs(lat_f) >= 90:
                errors.append(f"纬度越界: {name} lat={lat_f}")
            if abs(lng_f) >= 180:
                errors.append(f"经度越界: {name} lng={lng_f}")
            if lat_f == 0.0 and lng_f == 0.0:
                errors.append(f"坐标为(0,0): {name}")

        return errors

    def _check_chapters(self, data: dict) -> list[str]:
        """检测章节编号不连续或重复。"""
        errors: list[str] = []
        markdown = data.get("markdown", "")
        if not markdown:
            return errors

        chapters: list[int] = []
        for m in re.finditer(r'^##\s+([一二三四五六七八九十]+)[、，\.\s]', markdown, re.MULTILINE):
            num = _cn_to_int(m.group(1))
            if num is not None:
                chapters.append(num)

        if not chapters:
            return errors

        sorted_ch = sorted(set(chapters))

        if len(sorted_ch) != len(chapters):
            duplicates = sorted(set(c for c in chapters if chapters.count(c) > 1))
            errors.append(f"重复章节编号: {duplicates}")

        if len(sorted_ch) > 1 and sorted_ch != list(range(sorted_ch[0], sorted_ch[-1] + 1)):
            expected = set(range(sorted_ch[0], sorted_ch[-1] + 1))
            missing = expected - set(sorted_ch)
            if missing:
                errors.append(f"章节不连续，缺少: {sorted(missing)}")

        return errors

    def _check_relations(self, data: dict) -> list[str]:
        """检测近现代人物使用封建措辞。"""
        errors: list[str] = []
        person = data.get("person", {})
        dynasty = person.get("dynasty", "")

        if dynasty not in MODERN_DYNASTIES:
            return errors

        graph = data.get("relatedGraph", {})
        links = graph.get("links", [])
        for link in links:
            label = link.get("label", "")
            if any(fl in label for fl in FEUDAL_LABELS):
                errors.append(
                    f"关系措辞不当: {link.get('source', '?')} → {link.get('target', '?')} = '{label}'"
                )
        return errors

    def _check_markdown_quality(self, data: dict) -> list[str]:
        """检测 Markdown 占位符。"""
        errors: list[str] = []
        markdown = data.get("markdown", "")
        if not markdown:
            return ["markdown 字段为空"]

        placeholder_count = markdown.count("待补充")
        if placeholder_count > 3:
            errors.append(f"markdown 包含 {placeholder_count} 处'待补充'占位符")

        if "暂无可用" in markdown:
            errors.append("markdown 包含'暂无可用'占位符")

        return errors

    # ── 增量扫描缓存 ──

    def _load_scan_cache(self) -> dict[str, float]:
        """加载扫描缓存：{文件名: mtime}。"""
        if not self.scan_cache_path.exists():
            return {}
        try:
            data = json.loads(self.scan_cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: float(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save_scan_cache(self, cache: dict[str, float]) -> None:
        """保存扫描缓存。"""
        self.scan_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.scan_cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _filter_incremental(self, files: list[Path]) -> tuple[list[Path], list[Path]]:
        """分离需要重新扫描和可复用缓存的文件。

        Returns:
            (to_scan, from_cache) — 需扫描的文件列表 + 可复用缓存的文件列表
        """
        cache = self._load_scan_cache()
        to_scan: list[Path] = []
        from_cache: list[Path] = []

        for f in files:
            cached_mtime = cache.get(f.stem)
            current_mtime = f.stat().st_mtime
            if cached_mtime is not None and abs(current_mtime - cached_mtime) < 0.01:
                from_cache.append(f)
            else:
                to_scan.append(f)

        skipped = len(from_cache)
        if skipped > 0:
            self._log(f"增量模式: {skipped}/{len(files)} 文件未变更，跳过扫描")

        return to_scan, from_cache

    # ── 主执行 ──

    def _scan_one(self, f: Path) -> tuple[str, list[str], dict[str, int], list[dict]]:
        """扫描单个文件，返回 (name, errors, stat_delta, structured_issues)。"""
        name = f.stem
        try:
            html = f.read_text(encoding="utf-8")
        except Exception as e:
            issue = make_issue("FILE_READ_FAILED", "parse", "error", f"读取失败: {e}", field="file", source="searcher")
            return (name, [issue["message"]], {}, [issue])

        data, _ = parse_embedded_json(html)
        if data is None:
            issue = make_issue("EMBEDDED_JSON_PARSE_FAILED", "parse", "error", "无法解析内嵌 JSON", field="html", source="searcher")
            return (name, [issue["message"]], {}, [issue])

        issues = run_html_quality_checks(data)
        errors = [issue.get("message", "") for issue in issues]
        stats: dict[str, int] = {}
        for issue in issues:
            key = issue.get("type", "other")
            stats[key] = stats.get(key, 0) + 1

        return (name, errors, stats, issues)

    def _execute(self, **kwargs) -> AgentReport:
        person_files = self._person_files()

        # 增量模式：仅扫描变更文件
        if self.incremental:
            to_scan, from_cache = self._filter_incremental(person_files)
        else:
            to_scan = person_files
            from_cache = []

        all_errors: dict[str, list[str]] = defaultdict(list)
        all_issues: dict[str, list[dict]] = defaultdict(list)
        stats: dict[str, int] = defaultdict(int)
        parse_failures = 0
        new_cache: dict[str, float] = {}

        # 并行扫描变更文件
        max_workers = kwargs.get("max_workers", min(8, len(to_scan) or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._scan_one, f): f for f in to_scan}
            for future in as_completed(futures):
                name, errors, file_stats, issues = future.result()
                if errors:
                    all_errors[name] = errors
                    all_issues[name] = issues
                    for k, v in file_stats.items():
                        stats[k] += v
                if any(issue.get("type") == "parse" for issue in issues):
                    parse_failures += 1

        # 更新缓存：记录每个被扫描文件的 mtime
        for f in to_scan:
            try:
                new_cache[f.stem] = f.stat().st_mtime
            except Exception:
                pass

        # 保留未变更文件的缓存条目
        for f in from_cache:
            try:
                new_cache[f.stem] = f.stat().st_mtime
            except Exception:
                pass

        if self.incremental:
            self._save_scan_cache(new_cache)

        figures_with_issues = {n: e for n, e in all_errors.items() if e}
        structured_issues = {n: i for n, i in all_issues.items() if i}

        report_data = {
            "stats": dict(stats),
            "errors": figures_with_issues,
            "issues": structured_issues,
            "issue_schema_version": 1,
            "total_files": len(person_files),
            "files_with_issues": len(figures_with_issues),
            "parse_failures": parse_failures,
        }

        # 保存报告
        self._safe_write_json(self.report_path, report_data)
        self._log(f"报告已保存: {self.report_path}")

        total = len(person_files)
        issues = len(figures_with_issues)
        clean_rate = round((total - issues) / total * 100, 1) if total > 0 else 100.0

        return AgentReport(
            agent_name=self.name,
            status="ok",
            message=f"{total} 文件, {issues} 有问题, 健康率 {clean_rate}%",
            details={
                "total": total,
                "issues": issues,
                "clean_rate": clean_rate,
                "parse_failures": parse_failures,
                "stats": dict(stats),
                "report_path": str(self.report_path),
            },
            warnings=[f"{k}: {v}" for k, v in stats.items() if v > 0],
        )


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="搜索 Agent — 全量知识审计")
    ap.add_argument("--dir", type=Path, default=None, help="HTML 目录")
    ap.add_argument("--workers", type=int, default=8, help="并行线程数")
    ap.add_argument("--incremental", action="store_true", help="增量模式：仅扫描 mtime 变更的文件")
    args = ap.parse_args()
    agent = SearcherAgent(html_dir=args.dir, incremental=args.incremental, verbose=True)
    report = agent.run(max_workers=args.workers)
    print(f"\n{report.message}")
    if report.errors:
        for e in report.errors:
            print(f"  错误: {e}")

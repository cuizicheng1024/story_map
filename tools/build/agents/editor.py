"""编辑 Agent — 自动修复 HTML 中的知识性错误。

修复能力：
  1. LLM 思考过程清理（14 种正则模式）
  2. 章节编号修复（6 种已知错误模式）
  3. Markdown 占位符清理（待补充/暂无可用）
  4. short_review 空值补充

输入：搜索 Agent 的审计报告（JSON），或直接指定目录
输出：修复日志 + 修复计数
"""

from __future__ import annotations

import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from tools.build.agents.base import AgentReport, BaseAgent
from tools.build.agents._shared import cn_to_int, get_think_replacements, parse_embedded_json

# ── 修复用正则（统一自 _shared.get_think_replacements()） ──
THINK_PATTERNS: list[tuple[str, str]] = get_think_replacements()

# ── short_review 回退值 ──
SHORT_REVIEW_FALLBACKS: dict[str, str] = {
    "乐松生": "和平赎买",
    "亚历山大二世": "解放者沙皇",
    "哥伦布": "为上帝和国王陛下效力",
    "唐僖宗": "幸蜀",
    "威廉二世": "德意志帝国末代皇帝",
    "瓦特": "改良蒸汽机，推动工业革命",
    "郑成功": "开辟荆榛逐荷夷",
    "韩信": "兵仙神帅，汉初三杰",
}


class EditorAgent(BaseAgent):
    """编辑 Agent — 自动修复 HTML 知识性错误。"""

    name = "editor"
    label = "编辑 Agent"
    description = "修复 LLM 泄露/章节编号/占位符/short_review 四类可自动修复的知识性错误"
    max_retries = 1

    def __init__(
        self,
        html_dir: Path | None = None,
        audit_report_path: Path | None = None,
        verbose: bool = True,
        dry_run: bool = False,
        fix_mode: str = "with_risky",
    ):
        super().__init__(verbose=verbose)
        repo_root = Path(__file__).resolve().parents[3]
        self.html_dir = html_dir or (repo_root / "artifacts" / "story_map")
        self.audit_report_path = audit_report_path or (repo_root / "tools" / "debug" / "knowledge_audit_v2.json")
        self.dry_run = dry_run
        if fix_mode not in {"dry_run", "safe_only", "with_risky"}:
            raise ValueError(f"未知修复模式: {fix_mode}")
        self.fix_mode = "dry_run" if dry_run else fix_mode

    # ── 单项修复 ──

    @staticmethod
    def _clean_think_text(text: str) -> tuple[str, bool]:
        """清理 LLM 思考过程文本。返回 (清理后文本, 是否变更)。"""
        changed = False
        cleaned = text
        for pattern, replacement in THINK_PATTERNS:
            new_text = re.sub(pattern, replacement, cleaned, flags=re.DOTALL | re.IGNORECASE)
            if new_text != cleaned:
                changed = True
                cleaned = new_text
        # 合并多余空行
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()
        return cleaned, changed

    @staticmethod
    def _fix_chapter_numbering(markdown: str) -> tuple[str, bool]:
        """修复章节编号错误。先匹配已知模式，再通用重编号去重/填隙。"""
        changed = False
        md = markdown

        # ── 已知模式修复（针对项目标准章节标题） ──
        fixes = [
            # Pattern 1: 二 repeated (地图说明 + 人生历程)
            ("## 二、人生足迹地图说明", "## 二、人生历程与重要地点（按时间顺序）",
             "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
            # Pattern 2: 四 repeated (生平时间线 + 补充说明)
            ("## 四、生平时间线", "## 四、补充说明",
             "## 四、补充说明", None, "## 五、补充说明"),
            # Pattern 3: 三 repeated (地点坐标 + 生平时间线)
            ("## 三、地点坐标", "## 三、生平时间线",
             "## 三、生平时间线", None, "## 四、生平时间线"),
            # Pattern 4: 二 repeated (人生足迹概览 + 人生历程)
            ("## 二、人生足迹概览", "## 二、人生历程与重要地点（按时间顺序）",
             "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
            # Pattern 5: 二 repeated (作品 + 人生历程)
            ("## 二、作品", "## 二、人生历程与重要地点（按时间顺序）",
             "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
        ]

        for check_a, check_b, replace_b, check_c, replace_c in fixes:
            if check_a in md and check_b in md:
                md = md.replace(check_b, replace_b)
                changed = True
                if check_c and check_c in md:
                    md = md.replace(check_c, replace_c)

        # Pattern 6: missing 二 (一 → 三 → 四)
        if ("## 一、人物档案" in md and "## 三、人生历程与重要地点（按时间顺序）" in md
                and "## 二、" not in md and "## 四、生平时间线" in md):
            md = md.replace("## 三、人生历程与重要地点（按时间顺序）",
                             "## 二、人生历程与重要地点（按时间顺序）")
            md = md.replace("## 四、生平时间线", "## 三、生平时间线")
            changed = True

        # ── 通用重编号：处理任意章节标题的重复和跳跃 ──
        CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        chapter_re = re.compile(r'^(##\s+)([一二三四五六七八九十]+)([、，\.\s].*)$', re.MULTILINE)
        matches = list(chapter_re.finditer(md))

        if len(matches) >= 2:
            nums = []
            has_gap_or_dup = False
            seen = set()
            for m in matches:
                n = cn_to_int(m.group(2))
                if n is not None:
                    nums.append(n)
                    if n in seen:
                        has_gap_or_dup = True
                    seen.add(n)
            if not has_gap_or_dup and nums:
                # 检查跳跃：一→三（缺二）
                expected = list(range(1, len(nums) + 1))
                if nums != expected:
                    has_gap_or_dup = True

            if has_gap_or_dup:
                # 按出现顺序从"一"开始重新编号
                new_md = md
                for i, m in enumerate(matches):
                    new_num = CN_NUMS[i] if i < len(CN_NUMS) else str(i + 1)
                    old_heading = m.group(0)
                    new_heading = f"{m.group(1)}{new_num}{m.group(3)}"
                    new_md = new_md.replace(old_heading, new_heading, 1)
                if new_md != md:
                    md = new_md
                    changed = True

        return md, changed

    @staticmethod
    def _fix_markdown_placeholders(markdown: str) -> tuple[str, bool]:
        """清理 Markdown 占位符。"""
        changed = False
        md = markdown

        if "暂无可用" in md:
            md = re.sub(r"暂无可用\s*", "", md)
            changed = True

        if "待补充" in md:
            new_md = re.sub(r"^\s*待补充\s*$", "", md, flags=re.MULTILINE)
            if new_md != md:
                changed = True
                md = new_md

        md = re.sub(r"\n{3,}", "\n\n", md)
        return md, changed

    @staticmethod
    def _fix_short_review(data: dict, name: str) -> tuple[dict, bool]:
        """补充空的 short_review。"""
        person = data.get("person", {})
        old_review = person.get("shortReview", "") or person.get("short_review", "")

        if old_review and len(old_review.strip()) >= 2:
            return data, False

        # 优先查预定义回退表
        fallback = SHORT_REVIEW_FALLBACKS.get(name)
        if not fallback:
            # 从 description 提取简短描述（取第一句，去掉 LLM 泄露前缀）
            desc = (person.get("description", "") or "").strip()
            if desc:
                # 去掉常见 LLM 泄露前缀
                desc = re.sub(r'^[A-Z][a-z]+ [a-z]+ to [a-z]+ (?:that |about )?', '', desc)
                # 取前 20 字
                fallback = desc[:20].rstrip("，。.；;")
        if not fallback:
            return data, False

        person["shortReview"] = fallback
        if "short_review" in person:
            del person["short_review"]
        data["person"] = person
        return data, True

    # ── 单文件修复 ──

    def _fix_one(self, filepath: Path) -> dict[str, Any]:
        """修复单个文件，返回变更摘要。"""
        name = filepath.stem
        result = {"person": name, "changes": [], "safe_fixes": [], "risky_fixes": []}

        try:
            html = self._safe_read(filepath)
            if html is None:
                result["changes"].append("读取失败")
                return result
        except Exception as e:
            result["changes"].append(f"读取异常: {e}")
            return result

        data, old_json = parse_embedded_json(html)
        if data is None:
            return result

        person = data.get("person", {})
        desc = person.get("description", "")
        markdown = data.get("markdown", "")

        # 1. LLM think leaks
        if desc:
            cleaned_desc, changed = self._clean_think_text(desc)
            if changed:
                person["description"] = cleaned_desc
                result["changes"].append("description: 清除 LLM 思考过程")

        if markdown:
            cleaned_md, changed = self._clean_think_text(markdown)
            if changed:
                markdown = cleaned_md
                result["changes"].append("markdown: 清除 LLM 思考过程")
                result["safe_fixes"].append("markdown: 清除 LLM 思考过程")

        # 2. Chapter numbering
        if markdown:
            fixed_md, changed = self._fix_chapter_numbering(markdown)
            if changed:
                markdown = fixed_md
                result["changes"].append("markdown: 修复章节编号")

        # 3. Placeholders
        if markdown:
            fixed_md, changed = self._fix_markdown_placeholders(markdown)
            if changed:
                markdown = fixed_md
                result["changes"].append("markdown: 清理占位符")
                result["safe_fixes"].append("markdown: 清理占位符")

        # 4. short_review
        if self.fix_mode == "with_risky":
            data, changed = self._fix_short_review(data, name)
            if changed:
                result["changes"].append("short_review: 补充内容")
                result["risky_fixes"].append("short_review: 补充内容")
        elif self.fix_mode == "safe_only":
            person_review = person.get("shortReview", "") or person.get("short_review", "")
            if not person_review or len(str(person_review).strip()) < 2:
                result["skipped_risky_fixes"].append("short_review: 跳过高风险补充")

        if not result["changes"]:
            return result

        # 回写（person 已是 data["person"] 的引用，无需重复赋值）
        data["markdown"] = markdown

        if not self.dry_run:
            new_json = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
            new_html = html.replace(old_json, new_json, 1)
            # 事务安全：先写临时文件，再原子替换
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".html",
                dir=filepath.parent, delete=False,
            )
            try:
                tmp.write(new_html)
                tmp.close()
                Path(tmp.name).replace(filepath)
            except Exception:
                Path(tmp.name).unlink(missing_ok=True)
                raise
            self._log(f"{name}: {', '.join(result['changes'])}", "ok")

        return result

    # ── 输入校验 ──

    def _pre_run(self) -> None:
        super()._pre_run()
        if not self.html_dir.exists():
            raise FileNotFoundError(f"HTML 目录不存在: {self.html_dir}")

        # 加载审计报告，确定需要修复的文件
        report = self._safe_read_json(self.audit_report_path)
        if report and report.get("errors"):
            self._error_files = set(report["errors"].keys())
            self._log(f"从审计报告加载: {len(self._error_files)} 个问题文件")
        else:
            self._error_files = None
            self._log("未找到审计报告，将扫描全部文件", "warn")

    # ── 主执行 ──

    def _execute(self, **kwargs) -> AgentReport:
        # 确定文件列表
        if "names" in kwargs:
            target_names = set(kwargs["names"])
        elif self._error_files is not None:
            target_names = self._error_files
        else:
            target_names = {f.stem for f in self.html_dir.glob("*.html")}

        total_fixed = 0
        total_processed = 0
        total_safe_fixes = 0
        total_risky_fixes = 0
        total_skipped_risky_fixes = 0
        fix_logs: list[str] = []

        max_workers = kwargs.get("max_workers", min(8, max(len(target_names), 1)))

        def _process(name: str) -> dict:
            filepath = self.html_dir / f"{name}.html"
            if not filepath.exists():
                return {"changes": [], "name": name}
            return self._fix_one(filepath)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process, name): name for name in sorted(target_names)}
            for future in as_completed(futures):
                result = future.result()
                total_safe_fixes += len(result.get("safe_fixes", []))
                total_risky_fixes += len(result.get("risky_fixes", []))
                total_skipped_risky_fixes += len(result.get("skipped_risky_fixes", []))
                if result["changes"]:
                    total_fixed += 1
                    fix_logs.append(f"{result['person']}: {', '.join(result['changes'])}")
                total_processed += 1

        if self.dry_run:
            self._log("DRY-RUN 模式，未实际写入文件", "warn")

        return AgentReport(
            agent_name=self.name,
            status="ok",
            message=f"修复 {total_fixed} 个文件, 处理 {total_processed} 个",
            details={
                "fixed_files": total_fixed,
                "processed": total_processed,
                "safe_fixes": total_safe_fixes,
                "risky_fixes": total_risky_fixes,
                "skipped_risky_fixes": total_skipped_risky_fixes,
                "fix_mode": self.fix_mode,
                "fix_policy": {
                    "safe": ["think_leak", "chapter_numbering", "placeholder_cleanup"],
                    "risky": ["short_review_autofill"],
                    "modes": ["dry_run", "safe_only", "with_risky"],
                },
                "fix_logs": fix_logs[:100],
                "dry_run": self.dry_run,
            },
        )


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="编辑 Agent — 自动修复知识错误")
    ap.add_argument("--dir", type=Path, default=None, help="HTML 目录")
    ap.add_argument("--dry-run", action="store_true", help="预览模式")
    ap.add_argument("--fix-mode", choices=["dry_run", "safe_only", "with_risky"], default="with_risky", help="修复模式")
    args = ap.parse_args()
    agent = EditorAgent(html_dir=args.dir, dry_run=args.dry_run, fix_mode=args.fix_mode, verbose=True)
    report = agent.run()
    print(f"\n{report.message}")

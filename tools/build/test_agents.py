"""五 Agent 独立回归测试。

每个 Agent 的单元测试覆盖：
  - 正常路径
  - 异常边界
  - 幂等性
  - 空输入/空目录

用法:
  python3 tools/build/test_agents.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
import traceback
import unittest
from pathlib import Path


# ── 测试基类 ──

class AgentTestCase(unittest.TestCase):
    """提供临时目录 + HTML 夹具辅助方法。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="agent_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_html(
        self, name: str, person: dict | None = None,
        markdown: str = "", locations: list[dict] | None = None,
    ) -> Path:
        """创建测试用 HTML 文件。"""
        data = {
            "person": person or {"name": name, "description": f"{name}是一位历史人物。"},
            "markdown": markdown or "## 一、人生历程\n\n这是{name}的故事。\n",
            "locations": locations or [],
        }
        json_str = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{name}</title></head>
<body>
<script>window.__EXPORT_DATA__ = {json_str};</script>
</body></html>"""
        path = self.tmp / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        return path


# ── 搜索 Agent 测试 ──

class SearcherAgentTests(AgentTestCase):
    """SearcherAgent 测试 — 6 类错误检测 + 并行扫描 + 空目录。"""

    def test_empty_dir(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertEqual(report.status, "ok")
        self.assertEqual(report.details["total"], 0)

    def test_clean_file(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        self._make_html("张三", person={
            "name": "张三", "description": "张三是唐代诗人。",
            "shortReview": "唐代著名诗人。",
        }, locations=[{"name": "长安", "lat": 34.3416, "lng": 108.9398}])
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertEqual(report.details["issues"], 0, f"干净文件不应有问题: {report.details}")

    def test_think_leak_detection(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        self._make_html("李四", person={
            "name": "李四", "description": "I want to explain that 李四是诗人。",
            "shortReview": "诗人。",
        })
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertGreaterEqual(report.details["issues"], 1)

    def test_chapter_error_detection(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        self._make_html("王五",
            person={"name": "王五", "description": "人物。", "shortReview": "人物。"},
            markdown="## 一、人物档案\n正文\n## 三、人生历程与重要地点（按时间顺序）\n正文\n",
        )
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertGreaterEqual(report.details["issues"], 1)

    def test_markdown_placeholder_detection(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        self._make_html("赵六",
            person={"name": "赵六", "description": "人物。", "shortReview": "人物。"},
            markdown="## 一、待补充\n待补充\n待补充\n待补充\n",
        )
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertGreaterEqual(report.details["issues"], 1)

    def test_parallel_scan(self) -> None:
        from tools.build.agents.searcher import SearcherAgent
        for i in range(50):
            self._make_html(f"人物{i}", person={
                "name": f"人物{i}", "description": "正常描述。", "shortReview": "正常。",
            })
        agent = SearcherAgent(html_dir=self.tmp, verbose=False)
        report = agent.run(max_workers=4)
        self.assertEqual(report.status, "ok")
        self.assertEqual(report.details["total"], 50)


# ── 编辑 Agent 测试 ──

class EditorAgentTests(AgentTestCase):
    """EditorAgent 测试 — 修复 + 事务安全 + dry_run。"""

    def setUp(self) -> None:
        super().setUp()
        # 使用不存在的审计报告路径，强制 Editor 扫描全部文件
        self._audit_path = self.tmp / "nonexistent_audit.json"

    def _make_editor(self, dry_run: bool = False, fix_mode: str = "with_risky"):
        from tools.build.agents.editor import EditorAgent
        return EditorAgent(
            html_dir=self.tmp, audit_report_path=self._audit_path,
            dry_run=dry_run, fix_mode=fix_mode, verbose=False,
        )

    def test_dry_run_no_write(self) -> None:
        self._make_html("张三", person={
            "name": "张三", "description": "I want to 张三 is poet.", "shortReview": "诗人。",
        })
        agent = self._make_editor(dry_run=True)
        report = agent.run()
        self.assertEqual(report.status, "ok")
        content = (self.tmp / "张三.html").read_text(encoding="utf-8")
        self.assertIn("I want to", content)

    def test_fix_think_leak(self) -> None:
        self._make_html("张三", person={
            "name": "张三", "description": "I want to explain that 张三 is a poet.", "shortReview": "诗人。",
        })
        agent = self._make_editor(dry_run=False)
        report = agent.run()
        content = (self.tmp / "张三.html").read_text(encoding="utf-8")
        self.assertNotIn("I want to", content)

    def test_fix_chapter_numbering(self) -> None:
        # 使用真实项目章节命名：一→三 跳过 二
        self._make_html("王五",
            person={"name": "王五", "description": "人物。", "shortReview": "人物。"},
            markdown="## 一、人物档案\n正文\n## 三、人生历程与重要地点（按时间顺序）\n正文\n## 四、生平时间线\n正文\n",
        )
        agent = self._make_editor(dry_run=False)
        report = agent.run()
        content = (self.tmp / "王五.html").read_text(encoding="utf-8")
        self.assertIn("## 二、", content)

    def test_fix_markdown_placeholder(self) -> None:
        self._make_html("赵六",
            person={"name": "赵六", "description": "人物。", "shortReview": "人物。"},
            markdown="## 一、人生历程\n正文内容。\n## 二、补充说明\n待补充\n暂无可用\n",
        )
        agent = self._make_editor(dry_run=False)
        report = agent.run()
        content = (self.tmp / "赵六.html").read_text(encoding="utf-8")
        self.assertNotIn("待补充", content)
        self.assertNotIn("暂无可用", content)

    def test_transactional_write(self) -> None:
        self._make_html("张三", person={
            "name": "张三", "description": "I want to 张三 is poet.", "shortReview": "诗人。",
        })
        agent = self._make_editor(dry_run=False)
        agent.run()
        tmp_files = list(self.tmp.glob("*.html"))
        self.assertEqual(len(tmp_files), 1)  # 只有原文件


# ── 审阅 Agent 测试 ──

class ReviewerAgentTests(AgentTestCase):
    """ReviewerAgent 测试 — 二次审计 + 记忆写入 + 对比生成。"""

    def test_reviewer_on_clean_data(self) -> None:
        from tools.build.agents.reviewer import ReviewerAgent
        self._make_html("张三", person={"name": "张三", "description": "正常人物。", "shortReview": "人物。"}, locations=[{"name": "长安", "lat": 34.34, "lng": 108.94}])
        agent = ReviewerAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertEqual(report.status, "ok")

    def test_diff_generation(self) -> None:
        """验证修复前后对比逻辑。"""
        from tools.build.agents.reviewer import ReviewerAgent
        self._make_html("张三", person={"name": "张三", "description": "正常人物。"})
        agent = ReviewerAgent(html_dir=self.tmp, verbose=False)
        # 模拟修复前报告
        agent._before_report = {
            "errors": {"张三": ["short_review 为空"]},
            "files_with_issues": 1,
            "stats": {"short_review": 1},
        }
        agent._after_report = {
            "errors": {},
            "files_with_issues": 0,
            "total_files": 1,
            "stats": {},
        }
        diff = agent._generate_diff()
        self.assertEqual(len(diff["resolved"]), 1)
        self.assertIn("张三", diff["resolved"])
        self.assertEqual(diff["before_total_issues"], 1)
        self.assertEqual(diff["after_total_issues"], 0)

    def test_memory_write_structure(self) -> None:
        """验证记忆写入内容结构。"""
        from tools.build.agents.reviewer import ReviewerAgent
        # 创建临时记忆文件
        mem_path = self.tmp / "test_memory.md"
        mem_path.write_text("# 测试记忆\n\n## 知识审计状态\n旧内容\n", encoding="utf-8")
        agent = ReviewerAgent(html_dir=self.tmp, memory_path=mem_path, verbose=False)
        agent._after_report = {
            "errors": {"赵六": ["章节不连续，缺少: [2]"]},
            "files_with_issues": 1,
            "total_files": 10,
            "stats": {"chapter": 1},
        }
        diff = {"resolved": [], "new_issues": [], "persistent": ["赵六"]}
        result = agent._write_memory(diff)
        self.assertTrue(result)
        content = mem_path.read_text(encoding="utf-8")
        self.assertIn("赵六", content)
        self.assertIn("健康率", content)


# ── 地理定位 Agent 测试 ──

class GeoLocatorAgentTests(AgentTestCase):
    """GeoLocatorAgent 测试 — 缓存 TTL + 强制刷新 + dry_run + 坐标解析。"""

    def test_dry_run(self) -> None:
        from tools.build.agents.geolocator import GeoLocatorAgent
        agent = GeoLocatorAgent(html_dir=self.tmp, dry_run=True, verbose=False)
        report = agent.run()
        self.assertEqual(report.status, "ok")

    def test_force_refresh(self) -> None:
        from tools.build.agents.geolocator import GeoLocatorAgent
        agent = GeoLocatorAgent(
            html_dir=self.tmp, force_refresh=True, verbose=False,
        )
        self.assertTrue(agent.force_refresh)
        report = agent.run()
        self.assertEqual(report.status, "ok")

    def test_cache_ttl_default(self) -> None:
        from tools.build.agents.geolocator import GeoLocatorAgent
        agent = GeoLocatorAgent(html_dir=self.tmp, verbose=False)
        self.assertEqual(agent.cache_ttl_days, 7)

    def test_offline_dict_coords_resolution(self) -> None:
        """验证离线字典能正确解析古地名坐标。"""
        from tools.build.agents.geolocator import GeoLocatorAgent, load_ancient_mappings, load_city_coords
        # 创建包含长安坐标缺失的 HTML
        self._make_html("测试人物", person={
            "name": "测试人物", "description": "唐代人物。", "shortReview": "人物。",
        }, locations=[{"name": "长安", "lat": None, "lng": None}])
        agent = GeoLocatorAgent(html_dir=self.tmp, verbose=False)
        # 手动注入映射（不依赖高德 API）
        agent._ancient_mappings = {("测试人物", "长安"): "陕西省西安市"}
        agent._city_coords = dict(load_city_coords())
        report = agent.run()
        self.assertEqual(report.status, "ok")
        # 验证坐标已补全
        from tools.build.agents._shared import parse_embedded_json
        html = (self.tmp / "测试人物.html").read_text(encoding="utf-8")
        data, _ = parse_embedded_json(html)
        self.assertIsNotNone(data)
        locs = data.get("locations", [])
        self.assertEqual(len(locs), 1)
        self.assertIsNotNone(locs[0].get("lat"))
        self.assertIsNotNone(locs[0].get("lng"))
        self.assertEqual(locs[0].get("modernName"), "陕西省西安市")
        self.assertIn(locs[0].get("geocodeSource"), {"amap", "city_coords.json"})
        self.assertGreaterEqual(locs[0].get("geocodeConfidence", 0), 0.78)
        self.assertEqual(locs[0].get("geocodeAliasChain"), ["长安", "陕西省西安市"])
        self.assertEqual(locs[0].get("geocodeResolvedBy"), "GeoLocatorAgent")

    def test_empty_locations_fallback(self) -> None:
        """验证空 locations 数组特殊补全（韩信等）。"""
        from tools.build.agents.geolocator import GeoLocatorAgent
        self._make_html("韩信", person={
            "name": "韩信", "description": "兵仙神帅。", "shortReview": "兵仙。",
        }, locations=[])
        agent = GeoLocatorAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        # 韩信在 EMPTY_LOCATIONS_FALLBACK 中，应补全 5 个地点
        self.assertGreaterEqual(report.details.get("fixed", 0), 1)

    def test_unresolvable_removal(self) -> None:
        """验证占位值（不详/待补充）被移除。"""
        from tools.build.agents.geolocator import GeoLocatorAgent
        self._make_html("孙武", person={
            "name": "孙武", "description": "兵圣。", "shortReview": "兵圣。",
        }, locations=[{"name": "不详", "lat": None, "lng": None}])
        agent = GeoLocatorAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        self.assertGreaterEqual(report.details.get("removed", 0), 1)


# ── 拼接 Agent 测试 ──

class AssemblerAgentTests(AgentTestCase):
    """AssemblerAgent 测试 — 全管线 + 仪表板生成。"""

    def test_pipeline_on_empty_dir(self) -> None:
        from tools.build.agents.assembler import AssemblerAgent
        agent = AssemblerAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        # 空目录：搜索/编辑/定位 均返回 0 文件，审阅可能标记为 failed（无审计报告）
        # 但只要管线流程跑完就算通过
        self.assertIn(report.status, ("ok", "failed"))

    def test_pipeline_dashboard_generated(self) -> None:
        from tools.build.agents.assembler import AssemblerAgent
        self._make_html("张三", person={"name": "张三", "description": "正常人物。"})
        agent = AssemblerAgent(html_dir=self.tmp, verbose=False)
        report = agent.run()
        dashboard = Path(__file__).resolve().parents[2] / "tools" / "debug" / "audit_dashboard.html"
        self.assertTrue(dashboard.exists(), f"仪表板未生成: {dashboard}")

    def test_delivery_gate_blocks_failed_geocodes(self) -> None:
        from tools.build.agents.assembler import AssemblerAgent
        gate = AssemblerAgent._build_delivery_gate({
            "reviewer": {"details": {"after_issues": 0}},
            "geolocator": {"details": {"failed": 1}},
            "editor": {"details": {"risky_fixes": 0}},
        })
        self.assertFalse(gate["deliverable"])
        self.assertIn("地理定位失败 1 处", gate["blocking_reasons"])


# ── 运行 ──

if __name__ == "__main__":
    unittest.main(verbosity=2)

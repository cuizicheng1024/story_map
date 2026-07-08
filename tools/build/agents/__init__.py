"""StoryMap 知识质量 Agent 管线。

五 Agent 架构：
  searcher   — 搜索 Agent：全量扫描 HTML，检测 6 类知识错误
  editor     — 编辑 Agent：修复 LLM 泄露/章节编号/占位符/short_review
  reviewer   — 审阅 Agent：二次审计 + 前后对比 + 记忆写入
  geolocator — 地理定位 Agent：古地名坐标补全（高德 API + 离线字典）
  assembler  — 拼接 Agent：调度管线，并行执行，汇总报告

用法:
  from tools.build.agents.assembler import run_pipeline
  report = run_pipeline()                    # 全量管线
  report = run_pipeline(dry_run=True)        # 预览模式
"""

from tools.build.agents.base import AgentReport, BaseAgent
from tools.build.agents.searcher import SearcherAgent
from tools.build.agents.editor import EditorAgent
from tools.build.agents.reviewer import ReviewerAgent
from tools.build.agents.geolocator import GeoLocatorAgent
from tools.build.agents.assembler import AssemblerAgent, run_pipeline

__all__ = [
    "AgentReport",
    "BaseAgent",
    "SearcherAgent",
    "EditorAgent",
    "ReviewerAgent",
    "GeoLocatorAgent",
    "AssemblerAgent",
    "run_pipeline",
]

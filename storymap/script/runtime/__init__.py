"""storymap.script.runtime 子包：运行时服务与辅助实现。

包含：
- api：运行时 API 与任务服务入口
- helpers：运行时辅助函数
- support：运行时共享支持逻辑
- task_service：任务调度、持久化与快照服务
- task_debug：任务调试页面与 payload 构建
- task_schema：任务快照、状态和 runtime 聚合 schema
- local_history_qa：本地历史问答与人物档案检索
"""

from __future__ import annotations

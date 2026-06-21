"""storymap.script.core 子包：基础叶子模块集合。

包含：
- models：dataclass 数据模型
- parsers：故事 markdown 解析
- project_paths：项目路径与人名规范化入口
- env_utils：环境变量与 .env 加载
- person_registry：人物名规范化与别名映射
- artifacts：导出文件与首页构建产物辅助逻辑
- export_builders：GeoJSON / CSV 导出构建函数

为兼容历史调用，storymap/script/ 下的同名文件保留为转发层。
"""

from __future__ import annotations

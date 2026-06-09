# StoryMap 维护地图

这份文档只回答 3 个问题：

1. 从哪里启动项目
2. 某一类问题应该去改哪个模块
3. 哪些目录是主流程，哪些只是工具脚本

## 一眼看懂主流程

### 运行时入口

- `scripts/start_storymap.sh`
  - 本地开发首选入口
  - 自动选择 `.venv311` / `.venv` / `python3`
- `scripts/test_storymap.sh`
  - 本地回归测试入口
  - 默认执行 Ruff F 类检查 + 核心测试集
- `storymap/script/story_map.py`
  - Python 运行时总入口
  - 加载 `.env`
  - 做启动校验
  - 汇总对外兼容导出
- `storymap/script/story_runtime_api.py`
  - 运行时装配包装层
  - 负责 `_APP_RUNTIME`、`APP`、服务句柄和关闭钩子
- `storymap/script/story_runtime_helpers.py`
  - 运行时 helper 装配层
  - 负责 LLM client、local agent、vendor 资源、CORS 和输入校验包装
- `storymap/script/story_entrypoints.py`
  - CLI / serve 入口包装层
  - 负责 `main()` 和启动分发

### 运行时装配关系

- `storymap/script/app_factory.py`
  - 把 `TaskService`、`ProxyService`、`StaticService` 装到一个 runtime 里
- `storymap/script/api.py`
  - 对外暴露 HTTP 接口
  - 主要包括 `/generate`、`/task`、`/api/ai/proxy`、静态页访问

## 核心模块分工

### 1. 页面生成链路

- `storymap/script/task.py`
  - 任务提交
  - 人物识别
  - 生成进度记录
  - 单人物 / 多人物结果聚合
- `storymap/script/generation_service.py`
  - 单人物生成总流程
  - 生成人物 Markdown
  - 地点解析
  - 渲染人物页
- `storymap/script/story_generation_api.py`
  - 单人物生成装配层
  - 汇总 generation tools、状态对象和 `generate_for_person` 兼容导出
  - 当前已按 LangGraph 可迁移的 state 形状整理
- `storymap/script/profile_builder.py`
  - 把人物 Markdown 转成前端可消费的数据结构
  - 这里适合做“知识点、作品、时间线、引用”的结构化增强
- `storymap/script/story_geocode_api.py`
  - 地点解析包装层
  - 对外整理 `resolve_place_coord`、古今地名切分与坐标兜底能力
- `storymap/script/story_profile_api.py`
  - `profile_builder.py` 与 `generation_service.py` 的装配层
  - 对外提供 `load_profile_from_md`、`build_points`、`render_html` 等兼容导出
- `storymap/script/map_html_renderer.py`
  - 首页与多人物页的 HTML 生成
- `storymap/script/templates/profile_page.html`
  - 人物页模板
  - 这里承载大部分前端交互、知识点、地图、对话区逻辑

### 2. 地图与地理解析

- `storymap/script/geocode_service.py`
  - 历史地名与坐标解析
- `storymap/script/map_client.py`
  - 地理编码、坐标补全和地图相关辅助逻辑

### 3. 问答与代理

- `storymap/script/proxy.py`
  - `/api/ai/proxy` 的代理逻辑
  - 优先本地回答，失败后回退到 LLM / fallback
- `storymap/script/history_qa_agent.py`
  - 基于本地人物档案的问答代理
- `storymap/script/story_agents.py`
  - LLM 调用、人物识别、人物 Markdown 生成

### 4. Markdown 解析与数据模型

- `storymap/script/parsers.py`
  - 人物 Markdown 的解析器
- `storymap/script/models.py`
  - 解析后的数据模型

### 5. 静态资源与导出

- `storymap/script/static.py`
  - 静态资源响应
- `storymap/script/artifacts.py`
  - HTML / GeoJSON / CSV 等产物导出
- `storymap/script/export_builders.py`
  - 导出数据拼装

## 目录怎么理解

### 主流程目录

- `storymap/script/`
  - 主服务与核心逻辑
- `storymap/examples/story/`
  - 人物 Markdown 单一数据源
- `artifacts/story_map/`
  - 首页、人物页、导出文件产物

### 维护时高频使用目录

- `tools/`
  - 构建、校验、索引工具
  - 目录边界说明见 `tools/README.md`
- `tests/`
  - 回归测试
- `scripts/`
  - 本地便捷脚本，包括启动与测试入口
- `cli/`
  - 单次执行入口，目录边界说明见 `cli/README.md`

## 常见改动应该去哪里

- **改首页文案 / 交互**
  - `tools/build_stellar_homepage.py`
- **改人物页 UI / 知识点 / 对话区**
  - `storymap/script/templates/profile_page.html`
- **改人物 Markdown 解析逻辑**
  - `storymap/script/parsers.py`
  - `storymap/script/profile_builder.py`
- **改生成流程或任务进度**
  - `storymap/script/task.py`
  - `storymap/script/generation_service.py`
- **改对话回答逻辑**
  - `storymap/script/history_qa_agent.py`
  - `storymap/script/proxy.py`
- **改接口路由**
  - `storymap/script/api.py`

## 建议的维护原则

- 尽量把“运行时逻辑”放在 `storymap/script/`
- 尽量把“批处理脚本”放在 `tools/` 或 `cli/`
- 页面 UI 变更优先只改模板，不先动生成链路
- 结构化数据增强优先放到 `profile_builder.py`
- 改完后优先跑：

```bash
scripts/test_storymap.sh
```

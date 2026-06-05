# 核心文件索引

这个技能包除了 `SKILL.md` 之外，还附带了项目最核心的一组源码与说明文件，方便在脱离完整仓库时也能快速理解项目结构与主要逻辑。

## 文件清单

- `context/README.md`
  - 项目对外说明、使用方式、环境要求与展示内容

- `context/storymap/script/story_map.py`
  - 本地服务入口
  - 提供主页、人物页生成、任务接口、对话代理等能力

- `context/storymap/script/story_agents.py`
  - LLM 客户端与人物内容生成逻辑
  - 负责模型调用、消息整理与人物资料生成

- `context/storymap/script/map_html_renderer.py`
  - 人物页 HTML 模板渲染器
  - 决定人物介绍卡、地图、时间轴、对话区等页面结构

- `context/cli/auto_generate.py`
  - 单个人物的一键生成入口
  - 从人物姓名生成 Markdown 与 HTML 页面

- `context/tools/build_stellar_homepage.py`
  - 首页构建脚本
  - 负责生成“人类群星闪耀时”主页相关结构与默认配置

## 使用建议

- 如果要理解整个项目的运行链路，建议按以下顺序阅读：
  1. `context/README.md`
  2. `context/storymap/script/story_map.py`
  3. `context/storymap/script/map_html_renderer.py`
  4. `context/storymap/script/story_agents.py`
  5. `context/cli/auto_generate.py`

- 如果要修改首页，优先看：
  - `context/tools/build_stellar_homepage.py`

- 如果要修改人物页样式或信息组织，优先看：
  - `context/storymap/script/map_html_renderer.py`

- 如果要排查大模型、人物对话或自动生成人物，优先看：
  - `context/storymap/script/story_agents.py`
  - `context/storymap/script/story_map.py`

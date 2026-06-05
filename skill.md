---
name: "storymap-repo"
description: "用于 StoryMap 项目的运行、调试、内容生成与部署。处理人物足迹地图、主页、LLM 配置、人物页生成或发布任务时调用。"
---

# StoryMap 技能说明

## 程序是做什么的

`mapsotryforstudents` 是一个面向历史、语文与地理跨学科教学的“人物足迹故事地图”项目。
它可以根据历史人物或文学人物的信息，生成包含时间线、地点轨迹、事件说明、教材知识点和对话功能的交互式网页。

这个技能文件用于指导 Agent 在这个仓库中工作，帮助其他人快速理解：
- 这个程序的目标和用途
- 如何启动和使用它
- 适合在哪些场景下使用
- 处理这个仓库时应优先关注哪些文件

## 适用场景

在以下场景应调用此技能：
- 课堂教学展示：把人物生平、迁徙路线、时代背景做成可交互地图
- 教师备课：快速生成带时间线、地图和教材知识点的人物页
- 学生探究学习：通过地图、时间和事件联动理解人物经历
- 项目开发维护：调试主页、人物页、地图渲染、对话接口和部署配置
- 内容生产：从 Markdown 或人物名称批量生成故事地图页面

## 其他人如何使用

### 1. 本地运行

启动本地服务：

```bash
python3 storymap/script/story_map.py --serve --port 8765
```

浏览器打开：

```text
http://localhost:8765/
```

### 2. 生成人物页

使用一键生成脚本：

```bash
python3 cli/auto_generate.py --name "苏轼"
```

生成结果通常位于：
- Markdown：`storymap/examples/story/`
- HTML：`storymap/examples/story_map/`

### 3. 配置大模型接口

如果要启用人物对话、自动生成人物内容等功能，需要在 `.env` 中配置 LLM 信息，例如：
- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_ID`

当前仓库主要围绕 MiniMax 接口做兼容与调试。

## Agent 应关注的重点文件

- 本地服务入口：`storymap/script/story_map.py`
- LLM 客户端：`storymap/script/story_agents.py`
- HTML 模板渲染器：`storymap/script/map_html_renderer.py`
- 一键生成脚本：`cli/auto_generate.py`
- 演示主页：`storymap/examples/story_map/index.html`
- 环境配置：`.env`

## Agent 工作建议

1. 先检查仓库状态，确认当前任务是页面问题、后端问题、内容生成问题还是部署问题。
2. 修改前优先阅读 `story_map.py`、`story_agents.py`、`map_html_renderer.py`。
3. 如果问题出在人物页或首页，优先修模板和生成逻辑，而不是直接手改生成后的 HTML。
4. 如果问题涉及对话功能，要同时检查：
   - `.env` 中的 LLM 配置
   - `/api/ai/proxy` 是否可用
   - 页面前端的请求 fallback 逻辑
5. 如果问题涉及上线，要先区分：
   - 静态站点发布，例如 GitHub Pages
   - 完整服务部署，例如 Railway / Render / Zeabur

## 常用命令

启动本地服务：

```bash
python3 storymap/script/story_map.py --serve --port 8765
```

本地打开主页：

```text
http://localhost:8765/
```

生成单个人物页：

```bash
python3 cli/auto_generate.py --name "苏轼"
```

## 注意事项

- 不要在前端代码或公开提交中暴露私有 API Key。
- 优先修改生成器或模板代码，再重新生成目标 HTML 页面。
- 如果 Git 操作涉及与当前任务无关的本地改动，推送前要先确认提交范围。
- 如果用户要求“技能文件”，应保持这种 frontmatter + Markdown 正文的结构，确保 Agent 可以直接读取和理解。

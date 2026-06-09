<h1 align="center">🗺️ 故事地图StoryMap</h1>

<p align="center">
  <strong>从时空视角重构历史人物的生命轨迹</strong>
</p>

<p align="center">
  面向语文、历史、地理跨学科教学的历史人物时空分析助手
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/cuizicheng1024/storymap?style=flat-square" alt="GitHub stars" />
  <img src="https://img.shields.io/github/last-commit/cuizicheng1024/storymap?style=flat-square" alt="Last commit" />
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/License-Apache%202.0-F4C430?style=flat-square" alt="License Apache 2.0" />
  <img src="https://img.shields.io/badge/Map-AMap-0ea5e9?style=flat-square" alt="AMap" />
  <img src="https://img.shields.io/badge/LLM-MiniMax-7c3aed?style=flat-square" alt="MiniMax" />
</p>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1aLoCBnEiN">故事地图视频演示</a> ·
  <a href="#快速开始与项目结构">快速开始与项目结构</a> ·
  <a href="./install.md">安装与本地部署</a> ·
  <a href="#演示与在线静态版">演示与在线静态版</a>
</p>

## 目录
- [项目概况](#项目概况)
- [适用场景](#适用场景)
- [演示与在线静态版](#演示与在线静态版)
- [安装与本地部署](./install.md)
- [快速开始与项目结构](#快速开始与项目结构)
- [作者信息](#作者信息)

## 项目概况
**故事地图（StoryMap）** 面向文史爱好者，遵循 **“人物—时空—事件”** 的叙事主线，提供一个可理解任务、调用工具、输出证据的历史人物时空分析入口。输入一个人物、一个问题，或一个比较任务，就能生成可交互的足迹地图、结构化人物档案与追问式回答。

🧭 **项目目标：**借助地图，我们可以把文学与历史研究中偏感性、经验性的“人物分析”，转成可回放、可检索的**时空轨迹**，关注行走与迁徙的轨迹，而不仅仅某个时间切片的个人经历。

**从时空视角重构历史人物生命轨迹，解决文史学习中“文本碎片化、时空理解弱、检索成本高”的痛点。**

🛠️ **技术方案：**
- **1. 理解任务，识别人名**：支持输入姓名、短问题或多人物文本，先识别任务对象，再决定进入生成、检索或问答流程。
- **2. 组织证据，生成档案**：通过 LLM 检索与整理资料生成结构化内容，重点抽取 **时间 - 地点 - 事件 / 作品 - 意义**。
- **3. 调用地图工具，完成落图**：集成 **高德地图** 进行古今地名对照与地理编码，实现位置信息的精准可视化。
- **4. 输出结果，支持追问**：基于人物足迹、时间轴和事件节点生成联动页面，并通过对话窗口继续解释“为什么”“依据是什么”“和谁相似”。

### Agent 化工作流
- **任务理解**：接收人物名、提问句或多人物比较请求
- **对象识别**：识别人名并优先命中本地人物档案
- **证据组织**：生成结构化人物信息与时间线
- **地点解析**：补全古今地名映射与坐标
- **时空呈现**：生成可交互地图、时间轴和人物页
- **追问回答**：优先基于本地档案回答，再结合模型补全表达



## 🎯 适用场景
面向中学教学与文史学习场景，适合把人物、地点、事件和作品在同一时空框架中理解。

- **语文人物专题课**：围绕李白、苏轼、辛弃疾等人物，将作品、行旅和人生转折放在地图与时间轴中联动讲解。
- **历史人物时空复盘**：从迁徙、贬谪、出使、征战、治学等轨迹切入，帮助学生理解人物处境与时代背景。
- **跨学科研学展示**：适合语文、历史、地理融合展示，也适合校本课程、研学汇报与文化展陈场景。

🌍 从更宏观的视角重看历史人物：沿着他的足迹，我们能更容易洞悉成长变化，也能看到他与其他人物在时空上的关联。

- **💡 辅助高效备课**：自动抓取人物生平，省去翻阅史料、查找古地名的繁琐过程。
- **📍 直观展现轨迹**：将文字叙述转化为地图足迹，人物生平一目了然。
- **📚 跨学科教学**：契合「大语文」、「大历史」学科融合理念，在地图中讲诗词，在地理中读历史。
- **✨ 吸引学生注意力**：可交互网页支持时间轴联动和事件弹窗，让课堂更有参与感。

## 📸 演示与在线静态版
#### [故事地图操作展示](https://www.bilibili.com/video/BV1aLoCBnEiN)

演示内容包括：
- 人物页：人物要点 + 地图轨迹
- 主页：人类群星闪耀时 + 时间轴联动
- 人物页：地点连线与节点信息

<img src="storymap/docs/assets/moler_post_01.png" alt="人物页：人物要点 + 地图轨迹" width="600" />
<img src="storymap/docs/assets/moler_post_03.png" alt="主页：人类群星闪耀时 + 时间轴联动" width="600" />
<img src="storymap/docs/assets/moler_post_05.png" alt="人物页：地点连线与节点信息" width="600" />

主页默认展示：
- 输入框：输入人物姓名、问题或任务，即可发起分析/跳转到人物页
- 时间轴：「人类群星闪耀时」关系图，查看闪耀的人物群星
- 地图视角：从空间视角观察中国历史文化名人分布
- 支持拖动筛选，起止年份可自定义，并查看任务执行进度

人物页默认展示：
- 人物简介与证据摘要
- 足迹地图与时间轴
- 智能分析对话窗口
- 考点信息与延伸提问

### 在线静态版

#### [故事地图在线体验版](https://cuizicheng1024.github.io/storymap/)

- 可直接体验：首页浏览、已收录人物检索、已生成人物页查看
- 地图功能：配置 `AMAP_KEY` 后可加载底图并查看轨迹联动
- 当前不支持：`FastAPI`、`/generate`、`/task`、`/api/ai/proxy`
- 人物对话和未收录人物实时生成仍依赖后端 LLM，无法在静态版本体验

## 🚀 快速开始与项目结构

安装、环境变量配置和本地启动方式已经拆到独立文档：

- [安装与本地部署](file:///Users/bytedance/Desktop/Trae/mapsotryforstudents/install.md)

如果你只想快速体验本地服务，可直接执行：

```bash
scripts/start_storymap.sh
```

### 示例人物
- 苏轼
- 李白
- 辛弃疾

### 项目结构

```text
artifacts/
├── story_map/               # 构建产物目录：首页数据、首页产物、已生成人物 HTML/GeoJSON/CSV
storymap/
├── script/                 # 主服务与核心运行时：API、任务队列、渲染、解析、问答代理
├── examples/
│   └── story/              # 人物 Markdown 原始资料（单一数据源）
├── docs/                   # 规范文档、素材和维护说明
│   ├── assets/             # README 展示图片
│   ├── person_markdown_spec.md
│   └── maintenance_map.md  # 仓库维护地图
cli/                        # 面向人物/HTML 生成的命令行入口
scripts/                    # 本地启动等便捷脚本
tools/                      # 数据构建、校验、索引生成工具
data/                       # 人物主索引、坐标缓存、教材人物聚合结果
.env                        # 地图与 LLM 的本地配置
```

### 维护入口

如果你准备长期维护这个仓库，优先记住下面几个入口：

- `scripts/start_storymap.sh`
  - 本地启动入口，优先使用当前已激活环境，其次尝试仓库内 `.venv311` / `.venv`，再回退到系统 `python3`
- `storymap/script/story_map.py`
  - 运行时总入口，负责组装 `FastAPI`、任务服务、静态资源和问答代理
- `storymap/script/app_factory.py`
  - 运行时装配层，适合看清服务之间的依赖关系
- `storymap/script/task.py`
  - 生成人物页、多人物合并页、任务状态轮询的主流程
- `storymap/script/profile_builder.py`
  - Markdown -> 人物页结构化数据的主入口
- `storymap/script/templates/profile_page.html`
  - 人物页模板与大部分前端交互逻辑
- `tools/build_all.py`
  - 数据与首页构建入口
- `tools/run_storymap_checks.py`
  - 本地统一自检入口
- `scripts/test_storymap.sh`
  - 默认测试入口，本地修改后优先执行

## 开发自检

每次修改 `storymap/script`、`tests` 或 `tools` 后，建议先跑统一自检入口：

```bash
scripts/test_storymap.sh
```

说明：

- 默认会先跑一轮 `ruff check --select F`，只拦截会影响运行的导入/名称类问题
- 然后执行一组核心回归测试，覆盖环境变量兼容、静态目录选择、任务流、模板和 Markdown 校验
- `scripts/test_storymap.sh` 的解释器选择顺序与启动脚本一致：当前激活环境 -> 仓库内 `.venv311` / `.venv` -> 系统 `python3`
- 若要跑完整测试集，可执行：

```bash
scripts/test_storymap.sh --all-tests
```

## 数据重建与重渲染

当前仓库的数据单源为：

- `storymap/examples/story/*.md`

推荐使用统一构建入口：

```bash
python3 tools/build_all.py --concurrency 8
```

这个脚本会统一重建：

- `data/people_master.json`
- `data/people_master_pep.json`
- `artifacts/story_map/stellar_home_data.json`
- `artifacts/story_map/index.html`

如果你只想重渲染全部人物页 HTML：

```bash
MAP_STORY_RENDER_CONCURRENCY=8 python3 cli/generate_pure_story_map.py --render-all --all-mode nogeocode
```

说明：

- `build_all.py` 默认是幂等的，适合在你更新了 `story/*.md` 后重新同步首页数据与人物索引。
- `build_all.py` 默认会先对当前 git 变更中的 Markdown 跑一次冒烟校验；若结构性错误会直接中止，避免把坏数据继续发布。
- `--all-mode nogeocode` 适合快速重渲染已有人物页，不额外触发新的地理编码请求。
- 本地服务会直接放行 `artifacts/story_map/` 下的 `HTML / GeoJSON / CSV` 导出文件，便于浏览器直接查看或下载。
- 人物页和首页依赖的 `vendor/*.js` 会优先从本地静态目录读取；只有本地不存在时才会回退远程抓取。
- 若你已经配置 geocode key，想尽量补全地点坐标，可执行：

```bash
MAP_STORY_RENDER_CONCURRENCY=2 python3 cli/generate_pure_story_map.py --render-all --all-mode pure
```

- 如果只是本地体验现有仓库内容，通常只需要启动 `story_map.py --serve`，不必每次都重建。
- 每次 `build_all.py` 完成后，还会刷新：
  - `data/markdown_smoke_report.json`
  - `data/low_coverage_story_report.json`
  - `data/low_coverage_story_report.md`

## 人物 Markdown 规范
推荐每个人物文件都遵循统一规范，完整说明已单独存放在：

- `storymap/docs/person_markdown_spec.md`
- `storymap/docs/maintenance_map.md`

校验命令：

```bash
python3 tools/validate_story_markdown.py
```

只校验当前改动文件：

```bash
python3 tools/build_all.py --markdown-smoke-check changed
```

说明：
- 校验器会检查必需章节、关键字段、时间线表头
- 校验器会调用解析器做一次离线解析，提示“地点为空”或“出生/去世地缺失”等高风险问题
- 当前默认只把结构性问题视为错误；地点过少等问题先作为 warning，方便逐步清理历史数据
- GitHub Pages workflow 会只校验本次 push 中改动过的 `storymap/examples/story/*.md`，用于拦截新增坏数据，不会被历史遗留文件阻塞

## ✅ 无奖测试
猜猜这些名句是谁写的？
1. 峨眉山月半轮秋，影入平羌江水流
<img src="storymap/docs/assets/moler_post_06.png" alt="人物页：事件卡片与地图联动" width="600" />

2. 问余平生事业，黄州惠州儋州
<img src="storymap/docs/assets/moler_post_02.png" alt="人物页：左侧时间轴 + 轨迹连线" width="600" />

3. 关东有义士，兴兵讨群凶
<img src="storymap/docs/assets/moler_post_04.png" alt="人物页：时间轴驱动的地点/事件弹窗" width="600" />


## 作者信息

作者：崔成 `cuichengzi@foxmail.com`

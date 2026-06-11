# 安装、本地部署与项目结构

这份文档专门整理 `故事地图` 的环境要求、依赖安装、`.env` 配置、本地启动方式和主要项目结构。

## 环境要求

- `Python 3.11+`
- `Node.js` 当前主流程非必需
- 建议使用虚拟环境，但不强制要求目录名必须是 `.venv`

## 安装依赖

如果你本地还没有安装依赖，优先执行：

```bash
pip install -r requirements.txt
```

如果你希望自行创建虚拟环境，可参考：

```bash
python3 -m venv .venv311
source .venv311/bin/activate
pip install -r requirements.txt
```

说明：

- `scripts/start_storymap.sh` 和 `scripts/test_storymap.sh` 会优先使用当前已激活的虚拟环境
- 如果你没有激活虚拟环境，脚本才会继续尝试仓库内的 `.venv311`、`.venv`，最后优先回退到系统里的 `python3`，再回退到 `python`
- 因此不要求你一定创建名为 `.venv` 的目录，关键是当前解释器里已经安装项目依赖

## 环境变量配置

人物对话、未收录人物实时生成，以及高德地图底图都依赖 `.env` 配置。

至少建议在项目根目录创建 `.env`，并写入：

```env
AMAP_KEY=你的高德 JS Key
AMAP_SECURITY=你的高德安全密钥
MAP_STORY_API_BASE=http://127.0.0.1:8765
AMAP_WEBSERVICE_KEY=你的高德 WebService Key

LLM_PROVIDER=minimax
LLM_API_KEY=你的大模型 Key
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_MODEL_ID=MiniMax-M3
```

说明：

- `AMAP_KEY`：用于主页和人物页加载高德地图 JS
- `AMAP_SECURITY`：高德安全密钥，配合前端地图加载
- `AMAP_WEBSERVICE_KEY`：用于在线地理编码补点
- `MAP_STORY_API_BASE`：静态站接回外部 FastAPI 时使用；本地开发通常写 `http://127.0.0.1:8765`
- `LLM_PROVIDER`：当前推荐使用 `minimax`
- `LLM_API_KEY`：用于人物对话与新人物实时生成
- `LLM_BASE_URL`：默认推荐使用 OpenAI 兼容地址 `https://api.minimaxi.com/v1`
- `LLM_MODEL_ID`：默认推荐 `MiniMax-M3`

## 本地启动

推荐直接使用仓库内的启动脚本：

```bash
scripts/start_storymap.sh
```

如需自定义端口：

```bash
scripts/start_storymap.sh 8766
```

启动后可访问：

- 首页：`http://localhost:8765/`
- 接口文档：`http://localhost:8765/docs`
- 已生成的人物页导出文件：
  - `http://localhost:8765/<人物名>.html`
  - `http://localhost:8765/<人物名>.geojson`
  - `http://localhost:8765/<人物名>.csv`

打开任意人物页后，也可以直接分享带地点状态的链接，例如：

- `http://localhost:8765/苏轼.html#loc=3`

其中 `#loc=N` 表示人物页左侧时间轴中第 `N` 个地点节点，从 `0` 开始计数。

## 快速开始

如果你已经装好依赖并配置好 `.env`，最短路径就是：

```bash
scripts/start_storymap.sh
```

常见体验入口：

- 首页：`http://localhost:8765/`
- 接口文档：`http://localhost:8765/docs`
- 示例人物：`苏轼`、`李白`、`辛弃疾`

## 项目结构

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

## 维护入口

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

## 未收录人物

如果主页输入的人物不在当前库中，服务端会自动进入以下流程：

- 识别人物
- 生成档案
- 解析地点
- 渲染页面

生成期间主页会显示任务排队与分析进度，建议保持页面打开并等待完成。

补充：

- 首页和人物页依赖的 `vendor/*.js` 资源会优先从本地静态目录读取，只有本地不存在时才会回退到远程 CDN。
- 因此即使外网受限，只要 `artifacts/story_map/vendor/` 中已有这些文件，本地页面仍可正常加载。

## 常用命令

启动服务：

```bash
scripts/start_storymap.sh
```

运行默认自检：

```bash
scripts/test_storymap.sh
```

运行完整测试集：

```bash
scripts/test_storymap.sh --all-tests
```

重建首页数据：

```bash
python tools/build_all.py --concurrency 8
```

重渲染全部人物页：

```bash
MAP_STORY_RENDER_CONCURRENCY=8 python cli/generate_pure_story_map.py --render-all --all-mode nogeocode
```

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
python tools/build_all.py --concurrency 8
```

这个脚本会统一重建：

- `data/people_master.json`
- `data/people_master_pep.json`
- `artifacts/story_map/stellar_home_data.json`
- `artifacts/story_map/index.html`

如果你只想重渲染全部人物页 HTML：

```bash
MAP_STORY_RENDER_CONCURRENCY=8 python cli/generate_pure_story_map.py --render-all --all-mode nogeocode
```

说明：

- `build_all.py` 默认是幂等的，适合在你更新了 `story/*.md` 后重新同步首页数据与人物索引。
- `build_all.py` 默认会先对当前 git 变更中的 Markdown 跑一次冒烟校验；若结构性错误会直接中止，避免把坏数据继续发布。
- `--all-mode nogeocode` 适合快速重渲染已有人物页，不额外触发新的地理编码请求。
- 本地服务会直接放行 `artifacts/story_map/` 下的 `HTML / GeoJSON / CSV` 导出文件，便于浏览器直接查看或下载。
- 人物页和首页依赖的 `vendor/*.js` 会优先从本地静态目录读取；只有本地不存在时才会回退远程抓取。
- 若你已经配置 geocode key，想尽量补全地点坐标，可执行：

```bash
MAP_STORY_RENDER_CONCURRENCY=2 python cli/generate_pure_story_map.py --render-all --all-mode pure
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
python tools/validate_story_markdown.py
```

只校验当前改动文件：

```bash
python tools/build_all.py --markdown-smoke-check changed
```

说明：

- 校验器会检查必需章节、关键字段、时间线表头
- 校验器会调用解析器做一次离线解析，提示“地点为空”或“出生/去世地缺失”等高风险问题
- 当前默认只把结构性问题视为错误；地点过少等问题先作为 warning，方便逐步清理历史数据
- GitHub Pages workflow 会只校验本次 push 中改动过的 `storymap/examples/story/*.md`，用于拦截新增坏数据，不会被历史遗留文件阻塞

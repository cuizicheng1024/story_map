# 安装、本地部署与项目结构

这份文档专门整理 `故事地图` 的环境要求、依赖安装、`.env` 配置、本地启动方式和主要项目结构。

## 部署方式总览

当前项目有两条并行保留的线上部署路径，后续维护时都应视为正式方案：

- `火山云 ECS 部署`
  - 适合继续使用现有云服务器、SSH 私钥和脚本化发布流程
  - 主要入口：`scripts/deploy_storymap_release.sh`
  - 适用场景：需要完全控制服务器、systemd 服务、回滚目录和远端文件继承
- `OpenDeploy 部署`
  - 适合托管到 OpenDeploy 平台，并绑定到当前 OpenDeploy 账号下统一管理
  - 当前线上地址：`https://storymap.opendeploy.site`
  - 主要文档：`docs/opendeploy_deployment_notes.md`
  - 适用场景：希望更快完成托管发布、平台管理和线上访问

后续如果文档、脚本或发布说明里提到“部署”，默认都需要先明确是哪一条：

- `部署到火山云 ECS`
- `部署到 OpenDeploy`

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

补充：

- 人物页中的地图现在默认按需加载，正文和时间轴会优先渲染；滚动到地图区域后再初始化底图与轨迹。
- 首页数据也已经拆成 `core + detail` 两个 JSON，首页会先加载轻量首包，再在浏览器空闲时补载详情。

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
tools/                      # 构建/校验/调试工具；旧顶层入口多为兼容 shim
data/                       # 已分层为 corpus/reports/runtime；旧根路径软链暂保留兼容
.env                        # 地图与 LLM 的本地配置
```

其中首页相关的关键构建产物现在包括：

- `artifacts/story_map/index.html`
- `artifacts/story_map/stellar_home_data.json`
- `artifacts/story_map/stellar_home_data_detail.json`
- `data/reports/performance_baseline.json`

## 维护入口

如果你准备长期维护这个仓库，优先记住下面几个入口：

- `scripts/start_storymap.sh`
  - 本地启动入口，优先使用当前已激活环境，其次尝试仓库内 `.venv311` / `.venv`，再回退到系统 `python3`
- `storymap/script/story_map.py`
  - 运行时总入口，负责组装 `FastAPI`、任务服务、静态资源和问答代理
- `storymap/script/api/runtime_factory.py`
  - 运行时装配层，适合看清服务之间的依赖关系
- `storymap/script/task.py`
  - 生成人物页、多人物合并页、任务状态轮询的主流程
- `storymap/script/profile/builder.py`
  - Markdown -> 人物页结构化数据的主入口
  - 旧入口 `storymap/script/profile_builder.py` 仍保留兼容转发
- `storymap/script/profile/templates/profile_page.html`
  - 人物页模板与大部分前端交互逻辑
- `tools/build/build_all.py`
  - 数据与首页统一构建入口
  - 旧命令 `python3 tools/build_all.py` 仍可继续使用
  - 完整跑完后会额外生成 `data/reports/performance_baseline.json`
- `tools/build/build_stellar_homepage.py`
  - 首页定向构建入口
  - 旧命令 `python3 tools/build_stellar_homepage.py` 仍可继续使用
  - 适合只验证首页拆包或前端产物时单独执行
- `tools/reports/run_storymap_checks.py`
  - 本地统一自检入口
  - 旧命令 `python3 tools/run_storymap_checks.py` 仍可继续使用
- `scripts/test_storymap.sh`
  - 默认测试入口，本地修改后优先执行

- `data/`
  - 新写入路径优先使用 `data/corpus/`、`data/reports/`、`data/runtime/`
  - 旧根路径如 `data/people_master.json`、`data/markdown_smoke_report.json`、`data/hard_place_review_queue.json` 仍作为兼容入口保留

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

发布到火山云线上服务器：

```bash
scripts/deploy_storymap_release.sh --host <host> --user <user> --identity <pem>
```

部署到 OpenDeploy：

```bash
opendeploy deploy . --project <project-id> --service <service-id>
```

只先打包上传，不切换线上版本：

```bash
scripts/deploy_storymap_release.sh --skip-remote
```

发布前先跑本地自检：

```bash
scripts/deploy_storymap_release.sh --run-checks
```

发布完成后补跑公网验收：

```bash
scripts/deploy_storymap_release.sh --host <host> --user <user> --identity <pem> --verify-public
```

回滚到最近一版备份：

```bash
scripts/rollback_storymap_release.sh
```

运行默认自检：

```bash
scripts/test_storymap.sh
```

运行完整测试集：

```bash
scripts/test_storymap.sh --all-tests
```

## 火山云发布流

当前仓库已经内置一套“本地打包 -> 上传火山云 -> 远端解压切换 -> 重启服务 -> 健康检查”的发布脚本。

为避免误把本地改动直接发布到脚本内置的生产默认目标，`scripts/deploy_storymap_release.sh` 现在要求显式传入 `--host/--user`（或对应环境变量）。只有在你明确知道自己要复用内置默认生产目标时，才使用 `--allow-default-target`。

本地入口：

```bash
scripts/deploy_storymap_release.sh
```

远端执行脚本：

```text
scripts/remote_deploy_storymap.sh
```

默认约定如下：

- 服务器：`root@124.174.16.20`
- 私钥：仓库根目录 `storymap-key.pem`
- 线上目录：`/opt/storymap`
- 线上压缩包：`/opt/storymap-deploy.tar.gz`
- 线上部署脚本：`/opt/storymap-remote-deploy.sh`
- 服务名：`storymap.service`
- 健康检查：`http://127.0.0.1:8765/health`

脚本会自动做这些事：

1. 在本地生成干净的发布压缩包，默认排除 `.git`、`.env`、`.venv311`、缓存目录和私钥。
2. 把压缩包与远端部署脚本上传到火山云服务器。
3. 在远端新建 release 目录并解压压缩包。
4. 从当前线上版本继承 `.env`、`.venv311`、`artifacts/runtime`、`cache` 和 `.cache`。
5. 停止 `storymap.service`，把原目录备份为 `storymap.bak.<时间戳>`，再切换到新版本。
6. 执行 `pip install -r requirements.txt`，启动服务并做健康检查。
7. 默认只保留最近 `3` 份备份目录。

常见参数：

```bash
scripts/deploy_storymap_release.sh --run-checks
scripts/deploy_storymap_release.sh --verify-public
scripts/deploy_storymap_release.sh --skip-upload
scripts/deploy_storymap_release.sh --skip-verify
scripts/deploy_storymap_release.sh --public-base-url http://124.174.16.20
scripts/deploy_storymap_release.sh --host <host> --user <user> --identity <pem>
scripts/deploy_storymap_release.sh --app-dir /opt/storymap --service storymap.service
```

也可以通过环境变量覆盖默认值：

```bash
STORYMAP_DEPLOY_HOST=1.2.3.4 \
STORYMAP_DEPLOY_USER=root \
STORYMAP_DEPLOY_KEY=/path/to/key.pem \
scripts/deploy_storymap_release.sh
```

说明：

- `--run-checks` 会先执行 `scripts/test_storymap.sh`
- `--verify-public` 会在部署完成后，用公网入口校验首页、查理曼页和李白页的关键内容
- `--skip-upload` 适合你已经把压缩包和远端脚本传上去，只想重跑一次远端切换
- `--skip-remote` 适合先把包传上去，稍后再手动触发切换
- `--skip-verify` 会跳过部署后的健康检查
- 如果线上有新的持久化目录需要保留，可以继续在 `scripts/remote_deploy_storymap.sh` 里扩展继承逻辑

## OpenDeploy 发布流

当前项目也支持通过 OpenDeploy 托管部署，并且已经验证可以正常发布。

当前已知信息：

- `project_id`: `7a4a2787-4bdb-462c-9fd7-f66589f6aa36`
- `service_id`: `f27278c7-ee02-4b57-a2a2-92e2fa6696dc`
- 当前线上地址：`https://storymap.opendeploy.site`

推荐流程：

```bash
opendeploy auth whoami --json
opendeploy context resolve --json
opendeploy upload update-source 7a4a2787-4bdb-462c-9fd7-f66589f6aa36 . \
  --project-name mapsotryforstudents \
  --region-id b717f9dc-6149-4c86-adea-c7252bd1123c \
  --json
opendeploy deployments create --project 7a4a2787-4bdb-462c-9fd7-f66589f6aa36 \
  --service f27278c7-ee02-4b57-a2a2-92e2fa6696dc \
  --json
opendeploy deploy progress <deployment-id> --json
```

补充：

- 首次在新终端中使用 OpenDeploy 时，先确认当前已登录到目标账号
- 如果要把当前工作区与项目重新绑定，可执行：

```bash
opendeploy context save \
  --project 7a4a2787-4bdb-462c-9fd7-f66589f6aa36 \
  --service f27278c7-ee02-4b57-a2a2-92e2fa6696dc \
  --json
```

- OpenDeploy 的完整排障与踩坑记录见：
  - `docs/opendeploy_deployment_notes.md`

## 回滚与验收

公网验收脚本：

```bash
scripts/verify_storymap_public.sh
```

默认会校验：

- `http://124.174.16.20/health`
- 首页是否包含 `人类群星闪耀时`、`李白聊天`
- `查理曼.html` 是否包含 `帝国治理`、`权力来源`、`splitStreamDeltaForDisplay`
- `李白.html` 是否包含 `床前明月光`、`举头望明月`、`黄河之水天上来`

回滚脚本：

```bash
scripts/rollback_storymap_release.sh
```

说明：

- 不带参数时，默认回滚到最近一版 `storymap.bak.*`
- 也可以显式指定某个备份目录：

```bash
scripts/rollback_storymap_release.sh /opt/storymap.bak.20260619234714
```

- 回滚完成后同样会重启 `storymap.service` 并执行健康检查

重建首页数据：

```bash
python tools/build_all.py --concurrency 8
```

只重建首页与首页数据拆包产物：

```bash
python tools/build_stellar_homepage.py \
  --story-map-dir artifacts/story_map \
  --story-md-dir storymap/examples/story
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

- `data/corpus/people_master.json`
- `data/corpus/people_master_pep.json`
- `artifacts/story_map/stellar_home_data.json`
- `artifacts/story_map/stellar_home_data_detail.json`
- `artifacts/story_map/index.html`
- `data/reports/performance_baseline.json`

如果你只想验证首页性能与数据体积，而不想等待整套人物页重渲染，优先执行：

```bash
python tools/build_stellar_homepage.py \
  --story-map-dir artifacts/story_map \
  --story-md-dir storymap/examples/story
```

如果你只想重渲染全部人物页 HTML：

```bash
MAP_STORY_RENDER_CONCURRENCY=8 python cli/generate_pure_story_map.py --render-all --all-mode nogeocode
```

说明：

- `build_all.py` 默认是幂等的，适合在你更新了 `story/*.md` 后重新同步首页数据与人物索引。
- `build_all.py` 默认会先对当前 git 变更中的 Markdown 跑一次冒烟校验；若结构性错误会直接中止，避免把坏数据继续发布。
- 批量人物页重渲染现在默认走 `nogeocode`，适合模板或前端改动后的快速重建；只有专门补地点坐标时再显式传 `pure`。
- geocode 失败结果现在也会写入本地负缓存文件，短时间内重复构建不会反复对同一批难命中地名重试超时。
- 首页 JSON 现在已拆成 `stellar_home_data.json` 首包和 `stellar_home_data_detail.json` 详情包，首包优先服务首页首屏与搜索。
- `data/reports/performance_baseline.json` 会记录首页 HTML、首页 core/detail 数据包以及典型人物页体积，便于构建后直接对比性能变化。
- `--all-mode nogeocode` 适合快速重渲染已有人物页，不额外触发新的地理编码请求。
- `tools/review_hard_places.py` 可把低覆盖地点和 geocode 失败地点汇总成待审核队列，并可选调用 MiniMax 生成古今地名候选与建议写回位置。
- 本地服务会直接放行 `artifacts/story_map/` 下的 `HTML / GeoJSON / CSV` 导出文件，便于浏览器直接查看或下载。
- 人物页和首页依赖的 `vendor/*.js` 会优先从本地静态目录读取；只有本地不存在时才会回退远程抓取。

生成疑难地点审核队列：

```bash
python3 tools/review_hard_places.py --limit 20 --llm-mode auto
```

人工确认 `data/runtime/hard_place_review_queue.json` 中的 `human_decision` / `approved_*` 字段后，自动写回：

```bash
python3 tools/review_hard_places.py \
  --apply-confirmed \
  --queue-json data/runtime/hard_place_review_queue.json
```
- 若你已经配置 geocode key，想尽量补全地点坐标，可执行：

```bash
MAP_STORY_RENDER_CONCURRENCY=2 python cli/generate_pure_story_map.py --render-all --all-mode pure
```

- 如果只是本地体验现有仓库内容，通常只需要启动 `story_map.py --serve`，不必每次都重建。
- 每次 `build_all.py` 完成后，还会刷新：
  - `data/reports/markdown_smoke_report.json`
  - `data/reports/low_coverage_story_report.json`
  - `data/reports/low_coverage_story_report.md`

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

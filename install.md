# 安装与本地部署

这份文档专门整理 `故事地图` 的环境要求、依赖安装、`.env` 配置和本地启动方式。

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
- 如果你没有激活虚拟环境，脚本才会继续尝试仓库内的 `.venv311`、`.venv`，最后回退到系统里的 `python` / `python3`
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
LLM_BASE_URL=https://api.minimaxi.com/anthropic
LLM_MODEL_ID=MiniMax-M3
```

说明：

- `AMAP_KEY`：用于主页和人物页加载高德地图 JS
- `AMAP_SECURITY`：高德安全密钥，配合前端地图加载
- `AMAP_WEBSERVICE_KEY`：用于在线地理编码补点
- `MAP_STORY_API_BASE`：静态站接回外部 FastAPI 时使用；本地开发通常写 `http://127.0.0.1:8765`
- `LLM_PROVIDER`：当前推荐使用 `minimax`
- `LLM_API_KEY`：用于人物对话与新人物实时生成
- `LLM_BASE_URL`：MiniMax Token Plan 推荐为 `https://api.minimaxi.com/anthropic`
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

打开任意人物页后，也可以直接分享带地点状态的链接，例如：

- `http://localhost:8765/苏轼.html#loc=3`

其中 `#loc=N` 表示人物页左侧时间轴中第 `N` 个地点节点，从 `0` 开始计数。

## 未收录人物

如果主页输入的人物不在当前库中，服务端会自动进入以下流程：

- 识别人物
- 生成档案
- 解析地点
- 渲染页面

生成期间主页会显示任务排队与分析进度，建议保持页面打开并等待完成。

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
python3 tools/build_all.py --concurrency 8
```

重渲染全部人物页：

```bash
MAP_STORY_RENDER_CONCURRENCY=8 python3 cli/generate_pure_story_map.py --render-all --all-mode nogeocode
```

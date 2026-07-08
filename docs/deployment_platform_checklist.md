# OpenDeploy / 火山云部署配置清单

这份文档给 `mapsotryforstudents` 当前仓库提供一套可直接复用的部署配置，目标是避免再次手工回忆：

- 用哪个端口
- 健康检查打哪里
- 平台上要填哪些环境变量
- 没有正式域名时先怎么配

## 当前部署基线

- 服务端口：`8765`
- 健康检查：`/health`
- 就绪检查：`/health/ready`
- 启动命令：`python3 -m storymap.script.cli.story_map --serve --port ${PORT:-8765}`
- Docker 入口：仓库根目录 `Dockerfile`

说明：

- 现在没有正式域名时，OpenDeploy 先使用平台分配域名，例如 `https://storymap.opendeploy.site`
- 火山云 ECS 先使用公网 IP 或临时绑定域名
- 真正有正式域名后，只需要同步更新：
  - `MAP_STORY_API_BASE`
  - `STORY_MAP_ALLOWED_ORIGINS`

## 推荐环境变量

生产环境模板见：

- `/.env.production.example`

本项目部署时最少要配置这些变量：

```env
MAP_STORY_API_BASE=https://storymap.opendeploy.site
STORY_MAP_ALLOWED_ORIGINS=https://storymap.opendeploy.site

AMAP_KEY=...
AMAP_SECURITY=...
AMAP_WEBSERVICE_KEY=...

LLM_PROVIDER=minimax
LLM_API_KEY=...
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_MODEL_ID=MiniMax-M3

MAP_STORY_GA_MEASUREMENT_ID=G-XXXXXXXXXX
MAP_STORY_VOLCENGINE_APM_AID=1002542
MAP_STORY_VOLCENGINE_APM_TOKEN=...
MAP_STORY_VOLCENGINE_APM_ENV=prod

STORY_MAP_STRICT_STARTUP=1
MAP_STORY_STATIC_SITE=0
MAP_STORY_GRAPH_BACKEND=file
MAP_STORY_NEO4J_SYNC=0
```

说明：

- `MAP_STORY_API_BASE`：前端人物页和首页回连服务端时使用
- `STORY_MAP_ALLOWED_ORIGINS`：跨域白名单，生产环境不要保留 `*`
- `MAP_STORY_STATIC_SITE=0`：当前部署方式是同服务提供首页、人物页和 API
- `STORY_MAP_STRICT_STARTUP=1`：线上缺关键配置时直接失败，避免假启动

## OpenDeploy 配置

### 1. 使用现有 Dockerfile

根目录 `Dockerfile` 已经满足当前项目部署需要：

- 基础镜像：`python:3.11-slim`
- 暴露端口：`8765`
- 默认命令：读取平台注入的 `PORT`，启动 StoryMap 服务

### 2. 建议的 Service 配置

OpenDeploy 的 service 建议至少保持如下值：

```json
{
  "port": 8765,
  "health_check_path": "/health",
  "build_command": "pip install -r requirements.txt",
  "start_command": "sh -c \"PYTHONPATH=/app:${PYTHONPATH:-} python3 -m storymap.script.story_map --serve --port ${PORT:-8765}\""
}
```

### 3. 建议命令

```bash
opendeploy context resolve --json
opendeploy services env patch <project-id> <service-id> \
  --set MAP_STORY_API_BASE=https://storymap.opendeploy.site \
  --set STORY_MAP_ALLOWED_ORIGINS=https://storymap.opendeploy.site \
  --set AMAP_KEY=... \
  --set AMAP_SECURITY=... \
  --set AMAP_WEBSERVICE_KEY=... \
  --set LLM_PROVIDER=minimax \
  --set LLM_API_KEY=... \
  --set LLM_BASE_URL=https://api.minimaxi.com/v1 \
  --set LLM_MODEL_ID=MiniMax-M3 \
  --set MAP_STORY_VOLCENGINE_APM_AID=1002542 \
  --set MAP_STORY_VOLCENGINE_APM_TOKEN=... \
  --set MAP_STORY_VOLCENGINE_APM_ENV=prod \
  --set STORY_MAP_STRICT_STARTUP=1 \
  --set MAP_STORY_STATIC_SITE=0 \
  --confirm-env-upload \
  --json
```

如果需要显式修正服务配置：

```bash
opendeploy services config patch <service-id> --data '{
  "port": 8765,
  "health_check_path": "/health",
  "build_command": "pip install -r requirements.txt",
  "start_command": "sh -c \"PYTHONPATH=/app:${PYTHONPATH:-} python3 -m storymap.script.story_map --serve --port ${PORT:-8765}\""
}' --json
```

### 4. 没有正式域名时怎么填

如果当前只拿到 OpenDeploy 平台域名，直接先填平台域名：

```env
MAP_STORY_API_BASE=https://storymap.opendeploy.site
STORY_MAP_ALLOWED_ORIGINS=https://storymap.opendeploy.site
```

等以后切到正式域名，再把这两项替换成新域名，并重新部署一次即可。

## 火山云 ECS 配置

### 1. 远端部署入口

当前仓库已经提供脚本：

- `scripts/deploy_storymap_release.sh`
- `scripts/remote_deploy_storymap.sh`
- `scripts/verify_storymap_public.sh`

### 2. 推荐方式

如果先用公网 IP 访问，至少保持：

```env
MAP_STORY_API_BASE=http://<公网IP>
STORY_MAP_ALLOWED_ORIGINS=http://<公网IP>
```

如果后续改成 HTTPS 域名，记得两项一起切。

### 3. 示例发布命令

```bash
scripts/deploy_storymap_release.sh \
  --host <ecs-ip> \
  --user root \
  --identity <your-key.pem> \
  --verify-public
```

### 4. systemd / 进程验收

发布后至少确认：

- 服务监听在 `8765`
- `http://127.0.0.1:8765/health` 返回 `200`
- `http://127.0.0.1:8765/health/ready` 返回 `200`
- 公网首页 `/` 返回 `200`

## 发布后验收

不管是 OpenDeploy 还是火山云，至少验收下面这些路径：

- `/health`
- `/health/ready`
- `/`
- `/李白.html`
- `/苏轼.html`
- `/api/ai/proxy`

人物对话验收建议：

```bash
curl -X POST https://<your-base-url>/api/ai/proxy \
  -H 'Content-Type: application/json' \
  -d '{
    "messages": [
      {"role": "user", "content": "请你用第一人称介绍一下苏轼。"}
    ]
  }'
```

预期：

- 返回 `200`
- 响应正文不是 fallback 错误提示

## 最后上线前要改的两处

如果现在还是临时地址，正式上线前只需要优先检查这两处：

1. `MAP_STORY_API_BASE`
2. `STORY_MAP_ALLOWED_ORIGINS`

它们必须与最终外部访问地址一致，否则容易再次出现“页面打开了，但人物对话被跨域拦截”的问题。

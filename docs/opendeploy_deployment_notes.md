# OpenDeploy 部署经验记录

本文记录 `mapsotryforstudents` 在 OpenDeploy 上从首次失败到最终成功上线的真实排障过程，方便后续重复部署时直接复用。

## 最终结果

- 项目已成功部署到 OpenDeploy。
- 当前外网地址：`https://f27278c7.opendeploy.site`
- 健康检查地址：`https://f27278c7.opendeploy.site/health`
- 成功 deployment：
  - `0b9283a9-c9ee-4c51-a9ea-6f960bc0bad4`

## 本次最终可用配置

### 1. Dockerfile

仓库根目录新增：

- `Dockerfile`
- `.dockerignore`

最关键点：

- 使用 `python:3.11-slim`
- 先 `COPY requirements.txt` 并安装依赖
- 再 `COPY . .`
- `EXPOSE 8765`
- 使用 `CMD` 以 shell 包装启动命令，并允许平台注入 `PORT`

当前 `Dockerfile` 的目的不是复杂优化，而是：

- 让 OpenDeploy 明确识别这是一个可部署服务
- 避免平台自动推断 Python/FastAPI 运行方式
- 固定 HTTP 监听端口和镜像启动行为

### 2. Service 配置

OpenDeploy service 最终使用的关键配置：

- `port = 8765`
- `health_check_path = /health`
- `build_command = pip install -r requirements.txt`
- `start_command = sh -c "PYTHONPATH=/app:${PYTHONPATH:-} python3 -m storymap.script.story_map --serve --port ${PORT:-8765}"`

### 3. 运行时环境变量

本项目线上启动依赖 `.env` 中的关键变量。

本次实际同步到 OpenDeploy service 的变量包括：

- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_ID`
- `AMAP_KEY`
- `AMAP_SECURITY`
- `AMAP_WEBSERVICE_KEY`
- `GeoVisKey`
- `MAP_STORY_GA_MEASUREMENT_ID`
- `MONID_API_KEY`
- `STORY_MAP_STRICT_STARTUP=0`

说明：

- OpenDeploy 上传源码时会默认排除 `.env`
- 如果不单独把这些变量 patch 到 service，服务无法按本地环境启动

## 真实踩坑记录

### 坑 1：没有 Dockerfile，平台识别不到可部署服务

首次 `opendeploy analyze . --json` 的结果里，提示：

- `No package.json scripts or Dockerfile found at source root.`
- `No deployable service was detected.`

这意味着平台缺少明确的部署入口，只能走弱推断。

解决方式：

- 在仓库根目录补 `Dockerfile`
- 让平台明确识别端口、运行时和构建入口

### 坑 2：只上传源码，不同步 env，服务会直接起不来

本项目启动时会做运行时检查，而 OpenDeploy 默认不会把本地 `.env` 一起上传。

所以首次部署即使源码上传成功，容器内仍可能因为缺少：

- LLM 配置
- 地理编码配置
- 地图配置

而在启动阶段退出。

解决方式：

- 使用 `opendeploy services env patch <project-id> <service-id> ... --confirm-env-upload`
- 显式把需要的运行时变量同步到 service

### 坑 3：`start_command` 里用了 `${PORT}`，但没有 shell 包装

OpenDeploy 的 `start_command` 默认按原始 argv 执行，不会自动展开 shell 表达式。

因此像下面这种写法是错误的：

```bash
python3 storymap/script/story_map.py --serve --port ${PORT:-8765}
```

平台会直接报：

- `start_command contains shell operators ... but is not wrapped in a shell`

解决方式：

- 改成：

```bash
sh -c "..."
```

### 坑 4：按文件路径直接启动，容器里会出现 `ModuleNotFoundError`

这是这次最关键的真实根因。

错误日志核心内容：

```text
ModuleNotFoundError: No module named 'storymap'
```

错误启动方式：

```bash
python3 storymap/script/story_map.py --serve --port ${PORT:-8765}
```

原因：

- 这样启动时，Python 会把脚本目录当作导入起点
- 顶层包 `storymap` 反而不可见

解决方式：

- 改为包方式启动：

```bash
PYTHONPATH=/app:${PYTHONPATH:-} python3 -m storymap.script.story_map --serve --port ${PORT:-8765}
```

这一步修完之后，部署才真正通过。

### 坑 5：`opendeploy deploy . ...` 需要显式 `region-id`

尝试重新上传当前目录源码时，CLI 报错：

- `upload update-source requires --region-id`

解决方式：

- 先执行：

```bash
opendeploy regions list --json
```

- 再带上目标 region 执行上传

## 推荐部署流程

后续如果重新部署，建议按下面顺序执行。

### 1. 认证

```bash
opendeploy auth guest --json
```

### 2. 分析项目

```bash
opendeploy analyze . --json
```

预期应能识别出：

- `dockerfile = true`
- `framework = fastapi`
- `port = 8765`

### 3. 确认 project / service 上下文

```bash
opendeploy context resolve --json
```

### 4. 同步运行时变量

推荐使用：

```bash
opendeploy services env patch <project-id> <service-id> --set KEY=value ... --confirm-env-upload --json
```

至少要保证关键 env 已存在。

### 5. 必要时修正 service 配置

```bash
opendeploy services config patch <service-id> --data '{
  "port": 8765,
  "health_check_path": "/health",
  "build_command": "pip install -r requirements.txt",
  "start_command": "sh -c \"PYTHONPATH=/app:${PYTHONPATH:-} python3 -m storymap.script.story_map --serve --port ${PORT:-8765}\""
}' --json
```

### 6. 重新上传源码

```bash
opendeploy regions list --json
opendeploy upload update-source <project-id> . --project-name mapsotryforstudents --region-id <region-id> --json
```

### 7. 创建 deployment

```bash
opendeploy deployments create --project <project-id> --service <service-id> --json
```

### 8. 跟踪状态

```bash
opendeploy deploy progress <deployment-id> --json
```

## 冒烟测试清单

部署成功后，至少验证以下路径：

- `/health`
- `/`
- `/李白.html`
- `/苏轼.html`
- `/关羽.html`
- `/贞德.html`
- `/vendor/babel.min.js`

本次实测结果：

- `/health` 返回 `200` 且 body 正常
- 首页 `/` 返回 `200`
- `李白 / 苏轼 / 关羽 / 贞德` 人物页均返回 `200` 且页面正文正常
- `vendor/babel.min.js` 返回 `200`

## 当前已知状态

- OpenDeploy 当前已可稳定跑通本项目
- 外网健康检查可用
- 首页与代表性人物页可访问
- 静态资源可访问

后续若再次部署失败，优先排查顺序建议为：

1. `services env patch` 是否遗漏关键变量
2. `start_command` 是否仍为包方式启动
3. 新源码是否真的重新上传，而不是沿用旧 zip
4. `deploy progress` 与 `upload update-source` 的 source package 是否一致

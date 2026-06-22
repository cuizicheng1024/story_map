# StoryMap 监控接入说明

本文整理 StoryMap 当前 `/metrics` 暴露的指标、服务内置的 readiness 告警语义，以及一套可直接接入 Prometheus / Alertmanager 的参考配置。

适用目标：

- 接入 Prometheus 定时抓取 StoryMap 运行指标
- 基于 `/metrics` 和 `/health/ready` 判断服务是否可接流
- 把关键异常推送到 Alertmanager
- 为后续 Grafana 看板保留统一指标口径

## 1. 监控入口

当前建议关注 3 个 HTTP 入口：

- `/health`
  - 最基础的活性检查
  - 适合容器平台或负载均衡做轻量健康探针
- `/health/ready`
  - 返回 `serve_ready` / `generate_ready` / `alerts`
  - 已把静态产物、任务运行态、LLM、地理编码依赖都纳入 readiness
- `/metrics`
  - Prometheus 文本格式
  - 暴露 readiness、任务队列、任务计数器、依赖健康、代理熔断和当前激活告警

建议：

- 平台 `livenessProbe` 继续使用 `/health`
- 平台 `readinessProbe` 改用 `/health/ready`
- Prometheus 抓取 `/metrics`

## 2. 指标总览

### 2.1 Readiness 指标

这组指标用于区分“能不能提供静态浏览”和“能不能接生成请求”。

| 指标名 | 类型 | 含义 |
| --- | --- | --- |
| `storymap_readiness` | gauge | 总体 readiness，等价于 `generate_ready` |
| `storymap_serve_readiness` | gauge | 静态服务 readiness |
| `storymap_generate_readiness` | gauge | 生成链路 readiness |
| `storymap_static_ready` | gauge | 静态产物是否完整可用 |

说明：

- `storymap_serve_readiness=1` 表示首页/人物页/静态资源可以正常对外
- `storymap_generate_readiness=1` 才表示 `/generate` 会正常接流
- 当 `storymap_generate_readiness=0` 时，`POST /generate` 会直接返回 `503`

### 2.2 任务队列指标

这组指标来自任务系统 runtime snapshot，会随任务运行态实时变化。

| 指标名 | 类型 | 含义 |
| --- | --- | --- |
| `storymap_task_queue_pending` | gauge | 当前待执行任务数 |
| `storymap_task_queue_active` | gauge | 当前运行中的任务数 |
| `storymap_task_queue_limit` | gauge | 并发上限 |
| `storymap_task_queue_queued_count` | gauge | 状态为 `queued` 的任务数 |
| `storymap_task_queue_running_count` | gauge | 状态为 `running` 的任务数 |
| `storymap_task_queue_oldest_queued_age_seconds` | gauge | 最老排队任务年龄 |
| `storymap_task_queue_oldest_running_age_seconds` | gauge | 最老运行中任务年龄 |

### 2.3 任务计数器

这组指标来自 `TaskService.runtime_metrics_snapshot()`。

| 指标名 | 类型 | 含义 |
| --- | --- | --- |
| `storymap_task_submitted` | counter | 总提交任务数 |
| `storymap_task_deduped` | counter | 被去重命中的次数 |
| `storymap_task_retried` | counter | 手动或自动重试次数 |
| `storymap_task_interrupted` | counter | 因重启恢复标记为 `interrupted` 的次数 |
| `storymap_task_auto_retried` | counter | 自动补偿触发次数 |
| `storymap_task_cancel_requested` | counter | 收到取消请求次数 |
| `storymap_task_cancelled` | counter | 最终取消成功次数 |
| `storymap_task_timed_out` | counter | 任务超时次数 |
| `storymap_task_completed` | counter | 完成次数 |
| `storymap_task_failed` | counter | 失败次数 |
| `storymap_task_partial_failed` | counter | 部分失败次数 |
| `storymap_task_crashed` | counter | 执行崩溃次数 |
| `storymap_task_queue_wait_seconds_total` | counter | 累计排队耗时 |
| `storymap_task_duration_seconds_total` | counter | 累计任务执行耗时 |

建议优先关注：

- `storymap_task_timed_out`
- `storymap_task_failed`
- `storymap_task_crashed`
- `storymap_task_interrupted`
- `storymap_task_auto_retried`

### 2.4 依赖健康指标

这组指标按 `component` 标签区分依赖，目前至少包含：

- `component="llm"`
- `component="geocode"`

| 指标名 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `storymap_dependency_ready` | gauge | `component` | 依赖是否可用 |
| `storymap_dependency_requests` | gauge | `component` | 最近请求数或调用数 |
| `storymap_dependency_timeouts` | gauge | `component` | 最近超时数 |
| `storymap_dependency_success_rate` | gauge | `component` | 最近成功率 |
| `storymap_dependency_timeout_rate` | gauge | `component` | 最近超时率 |

注意：

- 这组指标是 readiness 判定的直接输入
- 当前服务内置规则中，当最近请求数达到阈值且成功率持续为 0，或超时率高于阈值时，会把 `generate_ready` 拉低

### 2.5 代理与熔断指标

这组指标来自 `ProxyService.metrics_snapshot()`。

| 指标名 | 类型 | 含义 |
| --- | --- | --- |
| `storymap_proxy_proxy_requests` | counter | 非流式代理请求数 |
| `storymap_proxy_proxy_stream_requests` | counter | 流式代理请求数 |
| `storymap_proxy_proxy_timeouts` | counter | 非流式代理超时次数 |
| `storymap_proxy_proxy_stream_timeouts` | counter | 流式代理超时次数 |
| `storymap_proxy_proxy_circuit_opened` | counter | 熔断器打开次数 |
| `storymap_proxy_proxy_circuit_short_circuits` | counter | 熔断打开期间被短路的次数 |
| `storymap_proxy_proxy_fallbacks` | counter | 降级到本地代理/历史回退的次数 |
| `storymap_proxy_proxy_stream_disconnects` | counter | 流式连接中途断开次数 |
| `storymap_proxy_breaker_open` | gauge | 熔断器当前是否处于打开状态 |
| `storymap_proxy_breaker_open_until` | gauge | 熔断器冷却结束时间戳 |
| `storymap_proxy_consecutive_failures` | gauge | 当前连续失败次数 |
| `storymap_proxy_breaker_failure_threshold` | gauge | 熔断阈值 |
| `storymap_proxy_breaker_cooldown_seconds` | gauge | 熔断冷却秒数 |
| `storymap_proxy_timeout_seconds` | gauge | 非流式超时阈值 |
| `storymap_proxy_stream_idle_timeout_seconds` | gauge | 流式空闲超时阈值 |
| `storymap_proxy_stream_total_timeout_seconds` | gauge | 流式总超时阈值 |

建议优先关注：

- `storymap_proxy_breaker_open`
- `storymap_proxy_proxy_stream_timeouts`
- `storymap_proxy_proxy_circuit_short_circuits`
- `storymap_proxy_proxy_fallbacks`

### 2.6 告警元信息指标

服务会把内置 alert rules 以指标形式暴露出来，方便 Prometheus 直接消费。

| 指标名 | 类型 | 标签 | 含义 |
| --- | --- | --- | --- |
| `storymap_alert_rule_info` | gauge | `code`, `level`, `threshold` | 告警规则字典，本身始终为 `1` |
| `storymap_alert_active` | gauge | `code`, `level` | 某条内置告警当前是否激活 |

当前代码内置的 alert rules 包括：

- `static_artifacts_missing`
- `queue_backlog_high`
- `running_task_stale`
- `llm_unavailable`
- `geocode_unavailable`

补充说明：

- `llm_success_rate_zero`
- `llm_timeout_rate_high`
- `geocode_success_rate_zero`
- `geocode_timeout_rate_high`

这些异常目前会出现在 `/health/ready` 的 `alerts` 里，并影响 `generate_ready`，但没有作为固定 `alert_rules` 字典项输出到 `storymap_alert_active`。因此更推荐直接基于 `storymap_dependency_*` 指标写 Prometheus 表达式告警。

## 3. 推荐抓取配置

下面是一份可直接使用的 Prometheus `scrape_configs` 示例。

```yaml
scrape_configs:
  - job_name: storymap
    metrics_path: /metrics
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets:
          - storymap.example.com
        labels:
          service: storymap
          env: prod
```

如果 StoryMap 部署在容器编排环境，也可以改成服务发现方式，只要保证最终抓取的是 `/metrics` 即可。

## 4. 推荐告警规则

下面把“直接接服务内置状态”和“在 Prometheus 侧派生计算”分两层给出。

### 4.1 直接消费内置告警状态

```yaml
groups:
  - name: storymap-readiness
    rules:
      - alert: StoryMapGenerateNotReady
        expr: storymap_generate_readiness == 0
        for: 2m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 生成链路不可用"
          description: "generate readiness 持续为 0，/generate 会返回 503。"

      - alert: StoryMapServeNotReady
        expr: storymap_serve_readiness == 0
        for: 2m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 静态服务不可用"
          description: "首页或静态产物未就绪，服务无法稳定对外。"

      - alert: StoryMapStaticArtifactsMissing
        expr: storymap_alert_active{code="static_artifacts_missing"} == 1
        for: 1m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 静态产物缺失"
          description: "index.html 或静态目录不可用。"

      - alert: StoryMapQueueBacklogHigh
        expr: storymap_alert_active{code="queue_backlog_high"} == 1
        for: 5m
        labels:
          severity: warning
          service: storymap
        annotations:
          summary: "StoryMap 排队积压过高"
          description: "待执行任务持续超过 readiness 阈值。"

      - alert: StoryMapRunningTaskStale
        expr: storymap_alert_active{code="running_task_stale"} == 1
        for: 5m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 存在长时间未结束任务"
          description: "最老运行中任务年龄持续超过阈值。"

      - alert: StoryMapLlmUnavailable
        expr: storymap_alert_active{code="llm_unavailable"} == 1
        for: 2m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap LLM 依赖不可用"
          description: "LLM client 初始化失败或 readiness 判定为 unavailable。"

      - alert: StoryMapGeocodeUnavailable
        expr: storymap_alert_active{code="geocode_unavailable"} == 1
        for: 2m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 地理编码依赖不可用"
          description: "geocode 依赖初始化失败或 readiness 判定为 unavailable。"
```

### 4.2 基于指标表达式补充派生告警

```yaml
groups:
  - name: storymap-runtime-derived
    rules:
      - alert: StoryMapLlmSuccessRateZero
        expr: storymap_dependency_requests{component="llm"} >= 3 and storymap_dependency_success_rate{component="llm"} <= 0
        for: 3m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap LLM 成功率为 0"
          description: "最近 LLM 调用已达到最小观测样本，但成功率持续为 0。"

      - alert: StoryMapGeocodeTimeoutRateHigh
        expr: storymap_dependency_requests{component="geocode"} >= 3 and storymap_dependency_timeout_rate{component="geocode"} >= 0.9
        for: 3m
        labels:
          severity: warning
          service: storymap
        annotations:
          summary: "StoryMap geocode 超时率过高"
          description: "最近 geocode 超时率持续高于 90%。"

      - alert: StoryMapProxyCircuitOpen
        expr: storymap_proxy_breaker_open == 1
        for: 1m
        labels:
          severity: critical
          service: storymap
        annotations:
          summary: "StoryMap 代理熔断已打开"
          description: "LLM 代理已进入熔断冷却期，部分请求将直接短路回退。"

      - alert: StoryMapProxyFallbackSpike
        expr: increase(storymap_proxy_proxy_fallbacks[10m]) >= 10
        for: 0m
        labels:
          severity: warning
          service: storymap
        annotations:
          summary: "StoryMap 代理回退次数激增"
          description: "最近 10 分钟 fallback 次数快速上升，建议检查上游 LLM 与网络。"

      - alert: StoryMapTaskFailuresHigh
        expr: increase(storymap_task_failed[15m]) >= 5 or increase(storymap_task_crashed[15m]) >= 1
        for: 0m
        labels:
          severity: warning
          service: storymap
        annotations:
          summary: "StoryMap 任务失败率升高"
          description: "最近 15 分钟任务失败或崩溃次数异常。"

      - alert: StoryMapInterruptedRecoveryTriggered
        expr: increase(storymap_task_interrupted[15m]) >= 1
        for: 0m
        labels:
          severity: warning
          service: storymap
        annotations:
          summary: "StoryMap 发生重启恢复"
          description: "最近 15 分钟出现 interrupted 任务，说明实例曾在执行中断。"
```

## 5. Alertmanager 路由示例

如果你已经有一个共享的 Alertmanager，可以直接把 StoryMap 告警按 `service=storymap` 路由到独立接收器。

```yaml
route:
  receiver: default
  group_by: ["alertname", "service", "env"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 2h
  routes:
    - matchers:
        - service="storymap"
        - severity="critical"
      receiver: storymap-critical
    - matchers:
        - service="storymap"
      receiver: storymap-warning

receivers:
  - name: default

  - name: storymap-critical
    webhook_configs:
      - url: http://alert-router.internal/storymap/critical
        send_resolved: true

  - name: storymap-warning
    webhook_configs:
      - url: http://alert-router.internal/storymap/warning
        send_resolved: true
```

如果你用的是企业微信、钉钉、飞书或 PagerDuty，可以把 `webhook_configs` 替换成对应集成方式。

## 6. 上线前检查清单

接入完监控后，建议至少做下面几项验证：

1. 打开 `https://<host>/metrics`，确认能看到 `storymap_generate_readiness`
2. 打开 `https://<host>/health/ready`，确认 `generate_ready` 与 `dependency_status` 字段正常
3. Prometheus 页面查询 `up{job="storymap"}`，确认抓取成功
4. 手动制造一个依赖异常，确认 `storymap_generate_readiness` 会降到 `0`
5. 人工触发一次测试告警，确认 Alertmanager 路由到正确接收器

## 7. 还建议继续补的工作

为了进一步提升可靠性、稳定性和可用性，建议把后续工作拆成下面几类。

### 7.1 可靠性

- 把任务状态、配额、熔断状态进一步外置到 Redis / PostgreSQL，避免单机实例重启造成状态割裂
- 给 `/generate` 增加幂等键和更明确的重试语义，减少前端重复提交导致的放大效应
- 为 LLM / geocode 增加分级降级策略，例如 geocode 失败时返回局部结果而不是整任务失败

### 7.2 稳定性

- 增加周期性长稳压测，持续验证队列积压、超时、自动补偿和熔断恢复是否稳定
- 把 `proxy_fallbacks`、`task_failed`、`generate_ready` 等核心指标接到 Grafana 看板，形成值班面板
- 为启动过程增加更严格的配置校验和依赖预热，减少首次请求才暴露问题

### 7.3 可用性

- 为 `/task` 和 `/generate` 增加更清晰的错误码与用户提示，区分“依赖故障”“排队中”“可稍后重试”
- 在前端显式展示“当前只读可用 / 生成不可用”的状态，和 `serve_ready` / `generate_ready` 对齐
- 增加发布后自动验收与监控联动，在 readiness 不达标时阻止流量切换

### 7.4 可运维性

- 给结构化日志接入统一日志平台，并按 `event`、`task_id`、`fallback_reason`、`component` 建索引
- 为告警增加 runbook，明确“看到哪条告警先查什么指标、看哪段日志、怎么止损”
- 把本文件中的 Prometheus / Alertmanager 示例沉淀到部署模板，避免每次手工复制

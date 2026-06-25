# [OPEN] Debug Session: online-chat-403

## Background
- Symptom: 线上 `POST /api/ai/proxy` 直测返回 `403 Forbidden`
- Expected: 线上人物对话接口返回 `200`，且 `used_fallback=false`
- Scope: `OpenDeploy` 与 `火山云` 公网环境

## Hypotheses
1. 线上接口存在额外的 `Origin` / `Host` / `Referer` 校验，导致直测请求被网关或应用层拦截。
2. 线上反向代理或 WAF 对 `POST /api/ai/proxy` 做了访问控制，但页面同源请求可通过。
3. 应用启动的实际代码版本与本地最新修复不一致，`Origin: null` 放行逻辑没有真正在线上生效。
4. 403 不是来自应用业务层，而是来自上游平台或网关，需从响应头/响应体判定来源。
5. 线上仅允许特定请求形态，例如必须带浏览器常见头或 SSE/JSON 某一种模式。

## Evidence Plan
- 先读取线上 `403` 的响应头与响应体，区分是应用层、平台层还是 CDN/WAF。
- 再静态核对当前代码里 `Origin` 校验与 `/api/ai/proxy` 入口位置，确认应观测点。
- 如需进一步定位，再只加插桩日志，不直接改业务逻辑。

## Status
- Current phase: hypothesis
- Business logic modified: no

## Evidence
- `curl POST https://storymap.opendeploy.site/api/ai/proxy` with `Origin: null` returned `200`, `source=llm`, `used_fallback=false`.
- `curl POST http://124.174.16.20/api/ai/proxy` with `Origin: null` returned `200`, `source=llm`, `used_fallback=false`.
- Response bodies contain first-person persona text for `蔡文姬`, so persona injection is active online.
- Static code check confirms `_enforce_origin()` maps `Origin: null` to empty string before allowlist validation.

## Hypothesis Review
1. 线上接口存在额外 `Origin` 校验并拦截 `Origin: null` -> Rejected by live `curl` evidence.
2. 线上网关/WAF 拦截 `POST /api/ai/proxy` -> Rejected by live `curl` evidence.
3. 线上未部署到包含放行修复的版本 -> Rejected by live behavior and persona output.
4. 403 来自平台层而非应用层 -> Not observed in latest reproduction.
5. 仅特定请求形态触发 403 -> Weakly possible, but latest browser-like and `curl` request shapes both pass.

## Interim Conclusion
- No production bug reproduced at this time.
- Most likely cause of the earlier `403` observation is a malformed local verification command / shell quoting issue during acceptance, not a real online outage.
- No business logic change is justified by current evidence.

[OPEN] search-taiping-failure

# 背景
- 症状：搜索“太平公主”失败。
- 目标：完成搜索链路全流程验证，基于运行时证据定位并修复问题。

# 当前假设
1. 搜索索引未收录“太平公主”。
2. 别名或规范名映射错误，导致搜索词未命中目标人物。
3. 搜索结果存在，但目标页面或重定向损坏。
4. 前端搜索归一化逻辑对该人物名处理异常。
5. 本地部署产物落后于源码生成结果。

# 计划
1. 检查人物源 Markdown、人物注册表、首页搜索数据与部署产物。
2. 给搜索链路添加最小化埋点，收集运行时证据。
3. 复现问题并比对日志，确认根因。
4. 做最小修复并进行前后对比验证。

# 证据
- `artifacts/story_map/index.html` 修复前在 `ensurePersonGenerated()` 中调用 `fetchWithTimeout(apiUrl("generate?person=" + encodeURIComponent(person)), 12000)`，即默认 `GET /generate`。
- `storymap/script/api.py` 的 `GET /generate` 明确返回 `405 {"ok": false, "error": "use POST /generate"}`。
- 运行时日志（pre-fix）：
  - `api.py:117`：`backend generate GET rejected`，`person=太平公主`，`method=GET`
  - `api.py:132`：`backend generate POST received`，`value=太平公主`，`method=POST`
- 直接复现结果：
  - `GET /generate?person=太平公主` -> `HTTP 405`
  - `POST /generate` with `{"person":"太平公主"}` -> `{"ok":true,"task_id":"..."}`

# 结论
- 假设 1：否。问题不在搜索索引缺少“太平公主”本身，而在未命中本地人物时的兜底生成链路。
- 假设 2：否。当前根因不是别名映射。
- 假设 3：否。失败发生在生成任务创建之前，不是跳转目标页缺失。
- 假设 4：部分否。前端搜索 UI 的问题表象成立，但真正触发失败的是错误的 HTTP 方法。
- 假设 5：是。首页产物和后端协议不一致，前端仍使用旧的 `GET /generate`。

# 修复
- 将首页兜底生成请求改为 `POST /generate`，提交 JSON body：`{"person": person}`。
- 扩展 `fetchWithTimeout()` 支持透传 `init` 参数，避免只能发默认 `GET`。
- 新增回归测试，约束首页模板继续使用 `POST /generate`。

# 验证
- `python3 tools/build_stellar_homepage.py`
- `python3 -m pytest tests/test_build_stellar_homepage.py tests/test_fastapi_app.py -q`
- post-fix 日志：
  - `api.py:132`：`backend generate POST received`，`value=太平公主`，`method=POST`

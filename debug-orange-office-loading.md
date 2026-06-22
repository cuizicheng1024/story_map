# Debug Session: orange-office-loading [OPEN]

## Symptom
- 火山云线上 `orange-office.html` 显示加载完成，但加载结束后页面没有进入可交互状态。

## Expected
- 加载完成后应进入像素办公室主界面，并可响应交互。

## Hypotheses
1. Phaser 已完成资源加载，但 `create()` 阶段抛错，导致遮罩消失后页面没有继续初始化。
2. 首屏遮罩隐藏了，但核心 canvas 或主场景没有成功挂载到 `#game-container`。
3. 某个运行时请求在 `create()` 后进入异常分支，导致页面停在“看起来加载完了但无响应”的半初始化状态。
4. 线上浏览器环境与本地不同，某个资源可访问但解码失败，导致场景对象未创建。
5. 初始化逻辑执行完成，但交互层被全屏遮罩或透明层覆盖，表现为“没有反应”。

## Plan
1. 给首屏加载、Phaser boot、scene create、遮罩隐藏、关键 DOM 状态加运行时日志。
2. 本地复现并抓取日志，确认卡点发生在 preload / create / post-create 哪一段。
3. 根据证据做最小修复。
4. 修复后再次对比 pre-fix / post-fix 日志并重新部署验证。

## Progress
- 已在 `.tmp_star_office_ui/frontend/index.html` 增加运行时埋点，并重新同步到 `artifacts/story_map/orange-office.html`。
- 已重新部署到火山云，线上页面确认包含 `orange-office-loading` 调试标识。
- 用户反馈：强制刷新后页面“已经正常了”。
- 当前缺口：调试服务器尚未收到 `trae-debug-log-orange-office-loading.ndjson`，因此还没有足够证据确认是网络缓存、首屏阻塞还是一次性慢启动。

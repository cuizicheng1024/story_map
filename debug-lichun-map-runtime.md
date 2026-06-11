[OPEN]

# Debug Session: lichun-map-runtime

## Symptoms
- `李春.html#loc=0` 首屏 2D 只显示一段线，且用户反馈缩放后点线关系异常。
- 点位在首屏与缩放过程中出现“乱飘”观感。
- `terrain-3d` 仍未正常接管，用户看到 3D 不加载。
- `《中国石拱桥》` 悬浮卡未稳定展示课文中的句子。
- 用户要求确认 GeoVis 文档链路，并评估切换为高德后是否更稳定。

## Hypotheses
1. `MapLibre` 当前把“渲染展开坐标”和“真实坐标”混用，导致线、点、镜头三套坐标不一致，所以只剩一段线或缩放时关系错乱。
2. `李春` 的多个事件共享同址/近同址坐标，当前 overlay 叠压策略在 `#loc=0` 下仍会让 endpoint / point / label 互相遮挡，造成“点乱飘”的视觉错觉。
3. `terrain-3d` 没有稳定加载，不是单一渲染问题，而是 GeoVis 资源请求、底图模式切换、Cesium 接管三者中有一条运行时链路失败。
4. `《中国石拱桥》` 的悬浮内容数据源仍优先拿到了说明性文案，而不是课文摘句，导致 UI 展示和预期不一致。

## Evidence Plan
- 启动独立 Debug Server，记录 `loc=0` 首屏、缩放、切换 `terrain-3d`、GeoVis 请求与 fallback 状态。
- 在 `profile_page.html` 继续补最小化打点：真实坐标、渲染坐标、首段线状态、3D 模式切换状态、作品 tooltip 命中来源。
- 使用 Playwright 固定复现 `localhost:8765/李春.html#loc=0`，抓日志、请求、状态和截图。
- 对照 GeoVis 文档核对 `vec / imagery / terrain / terrain-3d` 的接法与资源请求是否一致。

## Status
- Waiting for instrumentation and runtime evidence.

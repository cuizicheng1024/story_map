# [OPEN] Debug Session: wanganshi-marker-flicker

## Summary
- Symptom: `王安石` 人物页顶部地图点仍然闪烁。
- Expected: 激活点应稳定高亮，只在切换时有一次正常过渡，不应持续或周期性闪烁。

## Scope
- Page: `artifacts/story_map/王安石.html`
- Primary template: `storymap/script/profile/templates/profile_page.html`

## Hypotheses
1. `activeIndex` 在运行时被重复写回，导致同一个点反复进入激活态。
2. 稳定视角补偿之外，仍有别的 effect 或地图控制器在重复调用 `setActive()` / `focusIndex()`。
3. 不是状态重复，而是 `is-active` 本身的 CSS 无限 pulse 在王安石页视觉上被感知为“闪烁”。
4. 多地图引擎分支之一在初始化后重复挂载同一套 marker，造成重叠点交替显隐。
5. 某个 hover / autoplay / fallback overlay 链路在页面空闲时也会驱动 active 状态刷新。

## Plan
1. 启动调试服务器并接入前端运行时日志。
2. 仅添加插桩，记录 `setActive` / `focusIndex` / `applySelectionToMap` / autoplay / hover 链路。
3. 复现 `王安石` 页面闪烁并读取日志，判断真实触发链。
4. 基于证据实施最小修复。
5. 重放验证并保留调试环境，等待确认。

## Evidence Update
- 已完成第一次运行时复现。
- 当前证据：
  - `profile_page.html:7921` 的 `activeIndex effect sync` 仅出现 1 次。
  - `profile_page.html:6417` 的 `maplibre.setActive` 在相同 `activeIdx=3`、相同 `hash=#loc=3` 下以约 50ms 间隔持续出现。
- 第二轮证据补充：
  - 还存在另一条更高频的调用链：`tick(...) -> refreshAnimatedSegmentFrame() -> controller.setActive(activeIndexRef.current)`。
  - 这条链在 `activeIdx` 不变时依然按动画帧重复触发 `setActive()`，与用户反馈“频次降低但仍闪烁”一致。
- 第三轮证据补充：
  - 去掉 `tick` 链后的用户反馈变为：“打开时不闪烁，但缩放后又开始闪烁，并跳回原视点”。
  - 最新日志不再出现 `tick(...) -> setActive()`，改为 `renderStoryOverlays -> performOverlayRebuild -> run` 的周期性触发。
  - 结合模板代码可知，这条链仅会被 `healMapLibreOverlaysIfMissing(...)` 拉起；在未切底图的前提下，最可疑的入口是 `idle` 自愈监听。
- 初步结论：
  - 假设 1 暂不支持，React 的 `activeIndex` 没有持续变化。
  - 假设 2 明显增强，`MapLibre` 控制器之外仍有重复调用链在持续触发 `setActive()`。
  - 假设 5 成立，时间线 transition / autoplay 动画链也会驱动重复激活。
  - 当前修复方向：
    1. 保留 `followSegmentProgress()`，移除动画帧里的重复 `setActive()`。
    2. 保留 `styledata` 自愈，移除 `idle` 上的 Overlay 自愈重建，避免缩放后被误判为“图层丢失”。

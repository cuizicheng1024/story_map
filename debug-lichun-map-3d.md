[OPEN] lichun-map-3d

# Debug Session: 李春页面点位乱飞 / 线不可见 / 三维黑屏

## Symptoms
- 页面: `http://localhost:8765/%E6%9D%8E%E6%98%A5.html#loc=0`
- 现象 1: 点的符号乱飞
- 现象 2: 看不到线
- 现象 3: 三维图一片黑色

## Hypotheses
1. 首屏 `#loc=0` 激活时，MapLibre 标记或 Cesium 实体被重复初始化，位置样式状态发生覆盖。
2. 线段图层已创建，但透明度/宽度/颜色在首屏状态下被错误写成近似不可见值。
3. `Terrain - 3D` 模式中 imagery 或 terrain provider 已加载，但相机、光照或底图图层组合导致画面发黑。
4. `setBasemap()` / `focusIndex()` / hash 初始定位之间存在竞态，导致首站状态与实际渲染不同步。

## Evidence Plan
- 为李春页首屏初始化、`focusIndex(0)`、MapLibre 线段样式、Cesium viewer/imagery/camera 状态加运行时日志。
- 在本地复现 `#loc=0`，记录 pre-fix 证据。
- 基于证据做最小修复，再跑 post-fix 对比。

## Evidence Summary
- `pre-fix` 日志显示 `#loc=0` 时 overlay 正常创建，但首段线没有被点亮：首屏 `segmentStates[0].lineOpacity = 0.24`。
- `pre-fix` 3D 日志显示 Cesium viewer 和 imagery 已创建，但初始相机 pitch 接近 `89.9`，用户容易看到黑色星空背景。
- 运行时截图证明 3D 黑屏本质是“进入 Cesium 后相机未及时聚焦到轨迹范围”，不是纯粹底图丢失。

## Fixes Applied
1. 首站 `loc=0` 也将第一段线作为当前段高亮，MapLibre 和 Cesium 同步修复。
2. 首屏 hash 进入不再自动触发 pulse，避免点位出现“乱飞”感。
3. Cesium 关闭地形光照、关闭星空背景，并在初始化后延迟重放当前节点聚焦。
4. 时间轴顶部控件改为可换行布局，避免摘要 chip 与按钮压盖。

## Post-fix Evidence
- `post-fix` 复现脚本显示：
  - `vector` 首屏 `segmentStates[0].lineOpacity = 1`
  - `terrain-3d` 首屏 `segmentStates[0].lineOpacity = 0.98`
- 调试日志显示 Cesium 已进入 `lighting=false`，且后续多次 `setActive` 时相机 pitch 稳定在约 `42°`。

## Current Status
- 等待用户在本地浏览器手动验证：
  - `李春.html#loc=0` 点位是否不再乱飞
  - 首段线是否可见
  - `Terrain - 3D` 是否不再黑屏
  - 时间轴顶部是否不再压盖

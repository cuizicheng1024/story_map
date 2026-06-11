[OPEN] white-map-dots

# Debug Session: white-map-dots

## Symptom
- 首页“空间分布”地图中的人物点显示为白色，未按年代/朝代显示彩色。

## Expected
- 地图点应根据 `time_year` 通过 `colorByYear()` 显示对应颜色。

## Hypotheses
- H1: `updateMapMarkers()` 已执行，但高德 `Marker` 未应用更新后的 DOM 内容。
- H2: `markerSvg()` 收到的 `fill/glow` 参数正确，但最终渲染时被覆盖为白色。
- H3: 地图上显示的并非 `markers` 数组里被更新的那批实例。
- H4: 初次着色后，某个后续流程又把 marker 重建为默认白点。

## Evidence Plan
- 在 `createMarkerContent()`、`addMarker()`、`updateMapMarkers()` 中插桩，记录颜色值、节点名、marker 数量、`setContent` 调用情况。
- 重新加载首页并查看运行时日志，验证哪一步发生了偏差。

## Status
- Session initialized, instrumentation pending.

## Follow-up Symptom
- After marker color fix, the user reports that dragging the time window still does not make map points follow the selected year range.

## Follow-up Hypotheses
- H5: Dragging the timeline updates `startYear/endYear`, but does not call `updateMapMarkers()` in the effective path.
- H6: `updateMapMarkers()` is called, but returns early because `mapInited` or `amap` is falsy when dragging occurs.
- H7: The drag interaction happens while map tab is not initialized, and later map creation does not inherit the latest time window correctly.

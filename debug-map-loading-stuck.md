# Debug Session: map-loading-stuck
- **Status**: [OPEN]
- **Issue**: 人物页地图长时间停留在“地图正在展开”，遮罩层不消失，地图未显示。
- **Debug Server**: http://127.0.0.1:7777/event
- **Log File**: .dbg/trae-debug-log-map-loading-stuck.ndjson

## Reproduction Steps
1. 打开任意人物页，如 `李白.html`。
2. 等待地图区域初始化。
3. 观察到遮罩层长时间停留在“地图正在展开”，地图不出图。

## Hypotheses & Verification
| ID | Hypothesis | Likelihood | Effort | Evidence |
|----|------------|------------|--------|----------|
| A | 地图初始化流程已触发，但底图 SDK 未真正 ready，`mapLoadState` 卡在 `loading` | High | Low | Pending |
| B | 初始化过程中抛错但被吞掉，UI 没拿到失败态 | High | Low | Pending |
| C | 首选 GeoVis/MapLibre 失败后，未正确切换到 AMap 备用链路 | Med | Med | Pending |
| D | 远程资源请求悬挂且没有超时/降级收口 | High | Med | Pending |

## Log Evidence
- Pending

## Verification Conclusion
- Pending

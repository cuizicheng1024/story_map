/* story_curves_config.js — 曲线参数配置中心
 *
 * 设计: 把曲线渲染的可调参数从 buildCurvedSegmentPath 函数体里抽出,
 * 作为单一真源。改这里的数字, 528 个 HTML 内嵌函数通过
 * (typeof window.STORY_CURVES_CONFIG !== 'undefined' ? ... : 默认值) 读取。
 *
 * 用法:
 *   <script src="/static/js/story_curves_config.js?v=N"></script>
 *   <script> buildCurvedSegmentPath(...) // 内嵌函数, 读 window.STORY_CURVES_CONFIG </script>
 *
 * 兼容性:
 * - 老 HTML (注入过曲线 v2 的): 直接读 window.STORY_CURVES_CONFIG
 * - 更老的 HTML (没注入): 用 function-local 默认值,行为不变
 * - 离线 / 单页打开: <script> 失败时 config === undefined,走 fallback
 *
 * 改动工作流:
 *   1) 改下面 CONFIG 块里的数字
 *   2) bump VERSION
 *   3) 跑 `scripts/inject_curves_config.py --bump=N` 把新 ?v=N 加到所有 HTML script src
 *   4) 浏览器刷新即生效,无需重生成人物
 */
(function (global) {
  'use strict';

  // 数字改了,跑 inject_curves_config.py --bump=N 同步所有 HTML
  global.STORY_CURVES_CONFIG = {
    version: '2.0.0',
    // tension 上限,0.05-0.17 → 0.06-0.22
    tension: { min: 0.06, max: 0.22, base: 0.06, span: 0.16 },
    // 采样密度, 18-28 → 24-64
    steps: { min: 24, max: 64, divisorKm: 60, base: 16 },
    // 曲线启动距离阈值 (km), < 30km 几乎不弯
    distanceThresholdKm: 30,
    // 距离归一化参数
    curveRangeKm: 1200,
    // 锐角阻尼系数 (3 级)
    sharp: {
      uTurn: 0.12,        // incoming/outgoing 反向 (dot < -0.55)
      acute: 0.18,        // 同向偏小 (segDot > 0.9, < 1500km)
      smallTriangle: 0.22 // 三点过近
    }
  };
})(window);
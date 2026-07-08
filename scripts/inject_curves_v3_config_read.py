"""在已有 HTML 的 buildCurvedSegmentPath 函数里,把硬编码的 v2 数值替换成读 config 的形式。

用法:
    python3 scripts/inject_curves_v3_config_read.py --check
    python3 scripts/inject_curves_v3_config_read.py
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOB = ROOT / "artifacts" / "story_map"

# 旧(v2)的几行
OLD_RAW = "const rawCurveStrength = clampLocal((distanceKm - 30) / 1200, 0, 1);\n  const curveStrength = rawCurveStrength * rawCurveStrength;"
# 旧 tension / steps — 支持单行/三行两种 v2 写法
OLD_TENSION = "const tension = clampLocal((0.06 + curveStrength * 0.16) * sharpDamping, 0.06, 0.22);"
OLD_STEPS_SINGLE = "const steps = sharpDamping < 1 ? 12 : Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16));"
OLD_STEPS_MULTI = (
    "const steps = sharpDamping < 1\n"
    "    ? 12\n"
    "    : Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16));"
)
OLD_STEPS = f"({OLD_STEPS_SINGLE}|{OLD_STEPS_MULTI})"

# 新模板 (注入在 buildCurvedSegmentPath 函数内 rawCurveStrength 之前)
NEW_BLOCK = (
    "  // [v3] config reader — 单真源 /static/js/story_curves_config.js\n"
    "  const _cfg = (typeof window !== 'undefined' && window.STORY_CURVES_CONFIG) || null;\n"
    "  const _tension = _cfg ? _cfg.tension : { min: 0.06, max: 0.22, base: 0.06, span: 0.16 };\n"
    "  const _steps = _cfg ? _cfg.steps : { min: 24, max: 64, divisorKm: 60, base: 16 };\n"
    "  const _distThreshold = _cfg ? _cfg.distanceThresholdKm : 30;\n"
    "  const _curveRange = _cfg ? _cfg.curveRangeKm : 1200;\n"
)
NEW_RAW = (
    "const rawCurveStrength = clampLocal((distanceKm - _distThreshold) / _curveRange, 0, 1);\n"
    "  const curveStrength = rawCurveStrength * rawCurveStrength;"
)
NEW_TENSION = (
    "const tension = clampLocal((_tension.base + curveStrength * _tension.span) * sharpDamping, _tension.min, _tension.max);"
)
NEW_STEPS = (
    "  const steps = sharpDamping < 1\n"
    "    ? 12\n"
    "    : Math.max(_steps.min, Math.min(_steps.max, Math.round(distanceKm / _steps.divisorKm) + _steps.base));"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    files = sorted(GLOB.glob("*.html"))
    to_patch: list[Path] = []
    already: list[Path] = []

    for p in files:
        txt = p.read_text(encoding="utf-8")
        if NEW_RAW in txt:
            already.append(p)
            continue
        # 三段都要在
        has_raw = OLD_RAW in txt
        has_tension = OLD_TENSION in txt
        has_steps = (OLD_STEPS_SINGLE in txt) or (OLD_STEPS_MULTI in txt)
        if has_raw and has_tension and has_steps:
            to_patch.append(p)

    print(f"扫描总数: {len(files)}")
    print(f"  已是 v3 (读 config): {len(already)}")
    print(f"  待升级到 v3: {len(to_patch)}")
    if args.check:
        return 0

    for p in to_patch:
        txt = p.read_text(encoding="utf-8")
        # 1) 注入 config reader block (在 rawCurveStrength 那一行的前面)
        new = txt.replace(
            OLD_RAW,
            NEW_BLOCK + NEW_RAW,
            1,
        )
        new = new.replace(OLD_TENSION, NEW_TENSION, 1)
        new = new.replace(OLD_STEPS, NEW_STEPS, 1)
        p.write_text(new, encoding="utf-8")

    print(f"已升级: {len(to_patch)} 个文件 (现在都通过 window.STORY_CURVES_CONFIG 读参数)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
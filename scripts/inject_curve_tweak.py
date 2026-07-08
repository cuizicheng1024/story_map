"""固化: 把曲线逻辑改动批量注入所有 artifacts HTML。

用法:
  python3 scripts/inject_curve_tweak.py            # 应用
  python3 scripts/inject_curve_tweak.py --check    # 仅检查有哪些待注入

# 原理
profile_page.html 模板改动后,profile/renderer.py 下次生成人物会自然用新逻辑。
但之前已经生成的 532 个 HTML 还是老 JS,所以用简单 string-replace 把变更同步过去。
变更点用一个稳定 grep 锚点 — 我们这里找了:
  - `Math.max(18, Math.min(28`          ->  `Math.max(24, Math.min(64`
  - `clampLocal(0.05 + curveStrength` ->  `clampLocal(0.06 + curveStrength`
  - `clampLocal(0.05 + curveStrength * 0.12, 0.05, 0.17)` →
                `clampLocal(0.06 + curveStrength * 0.16) * sharpDamping, 0.06, 0.22)`

脚本失败/报警不会写入,只输出 diff。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOB = ROOT / "artifacts" / "story_map"

# 曲线版本指纹: 在 profile_page.html / 当前网页里都会出现的稳定字符串
V1_FINGERPRINT = "Math.max(18, Math.min(28, Math.round(distanceKm / 110) + 10))"
V2_FINGERPRINT = "Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16))"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅检查待注入,不动文件")
    args = ap.parse_args()

    files = sorted(GLOB.glob("*.html"))
    if not args.check:
        # 1) 确保 V1 在模板里已经被替换 (指纹检测)
        template = (ROOT / "storymap" / "script" / "profile" / "templates" / "profile_page.html").read_text(
            encoding="utf-8"
        )
        if V1_FINGERPRINT in template:
            print("[ERROR] profile_page.html 模板还停留在 v1,先改模板再注入", file=sys.stderr)
            return 1
        if V2_FINGERPRINT not in template:
            print("[ERROR] template 里找不到 v2 指纹,请检查", file=sys.stderr)
            return 1

    to_patch: list[Path] = []
    already: list[Path] = []
    for p in files:
        txt = p.read_text(encoding="utf-8")
        if V2_FINGERPRINT in txt:
            already.append(p)
        elif V1_FINGERPRINT in txt:
            to_patch.append(p)
        # else: not a trajectory page (e.g. index.html), skip

    print(f"扫描总数: {len(files)}")
    print(f"  待注入(v1): {len(to_patch)}")
    print(f"  已是新(v2): {len(already)}")

    if args.check:
        if to_patch:
            print("需要注入,可重复执行: python3 scripts/inject_curve_tweak.py")
        return 0

    # 注入
    count = 0
    for p in to_patch:
        txt = p.read_text(encoding="utf-8")
        # tension 上限从 0.17 提到 0.22
        new = txt.replace(
            "clampLocal(0.05 + curveStrength * 0.12, 0.05, 0.17)",
            "clampLocal(0.06 + curveStrength * 0.16, 0.06, 0.22)",
        )
        # 采样密度 18~28 -> 24~64
        new = new.replace(
            "Math.max(18, Math.min(28, Math.round(distanceKm / 110) + 10))",
            "Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16))",
        )
        # 方案 3: sharp 阻尼 — 在 if (dot < -0.55)/segDot > 0.9/longEdgeKm 三个分支前
        # 把 `return [[fromLng, fromLat], [toLng, toLat]];` 替换成 `sharpDamping = X;`
        new = re.sub(
            r"if \(dot < -0\.55\) return \[\[fromLng, fromLat\], \[toLng, toLat\]\];",
            "if (dot < -0.55) sharpDamping = 0.12;",
            new,
        )
        new = re.sub(
            r"if \(segDot > 0\.9 && distanceKm < 1500\) return \[\[fromLng, fromLat\], \[toLng, toLat\]\];",
            "if (segDot > 0.9 && distanceKm < 1500) sharpDamping = 0.18;",
            new,
        )
        new = re.sub(
            r"if \(longEdgeKm > 0 && areaKm2 < longEdgeKm \* longEdgeKm \* 0\.04\) \{\s*return \[\[fromLng, fromLat\], \[toLng, toLat\]\];\s*\}",
            "if (longEdgeKm > 0 && areaKm2 < longEdgeKm * longEdgeKm * 0.04) sharpDamping = 0.22;",
            new,
        )
        # 在 `if (!Number.isFinite(distanceKm)) return [[fromLng` 后面、shouldSkipSegment 块前面,
        # 注入 `let sharpDamping = 1.0;`
        new = re.sub(
            r"(if \(shouldSkipSegmentConnection\(\[\s*fromLng\s*,\s*fromLat\s*\],\s*\[toLng\s*,\s*toLat\s*\],\s*\{\s*idx\s*\}\)\) return \[\];\n)(  // D\+G)",
            (
                r"\1  let sharpDamping = 1.0;\n"
                r"  // [v2] 方案 3 — 用贴角小弧替代硬直线 (sharpDamping<1 时压 tension + 降采样)\n\2"
            ),
            new,
        )
        # tension 行加 sharpDamping 乘子
        new = new.replace(
            "const tension = clampLocal(0.06 + curveStrength * 0.16, 0.06, 0.22);",
            "const tension = clampLocal((0.06 + curveStrength * 0.16) * sharpDamping, 0.06, 0.22);",
        )
        # steps 行为 sharp 时降采样
        new = new.replace(
            "const steps = Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16));",
            "const steps = sharpDamping < 1 ? 12 : Math.max(24, Math.min(64, Math.round(distanceKm / 60) + 16));",
        )
        p.write_text(new, encoding="utf-8")
        count += 1

    print(f"注入完成: {count} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

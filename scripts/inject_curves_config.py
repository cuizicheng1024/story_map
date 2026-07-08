"""批量把 <script src="...story_curves_config.js"> 注入到所有 HTML 头部。

# 工作流
# 1) 改 static/js/story_curves_config.js 里的数字
# 2) python3 scripts/inject_curves_config.py     # 默认 ?v=当前版本
#    python3 scripts/inject_curves_config.py --bump  # 自动 +1 (强制刷新)
# 3) 浏览器刷新就生效,528 HTML 自动同步
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOB = ROOT / "artifacts" / "story_map"
SCRIPT_URL = "/static/js/story_curves_config.js"

CONFIG_FILE = ROOT / "artifacts" / "story_map" / "static" / "js" / "story_curves_config.js"


def get_current_version() -> str:
    src = CONFIG_FILE.read_text(encoding="utf-8")
    m = re.search(r"version:\s*['\"]([^'\"]+)['\"]", src)
    return m.group(1) if m else "2.0.0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--bump", action="store_true",
                    help="把 ?v=N 的 N +1,强制浏览器刷新拿最新")
    ap.add_argument("--out-version", default=None, help="强制 ?v= 这个版本号")
    args = ap.parse_args()

    if not CONFIG_FILE.exists():
        print("[ERROR] 找不到 config:", CONFIG_FILE, file=sys.stderr)
        return 1
    version = args.out_version or get_current_version()
    if args.bump:
        # bump +1
        nums = re.findall(r"(\d+)", version)
        if nums:
            new = int(nums[-1]) + 1
            version = version.rsplit(nums[-1], 1)[0] + str(new)
    script_tag = f'<script src="{SCRIPT_URL}?v={version}"></script>'

    files = sorted(GLOB.glob("*.html"))
    to_patch: list[Path] = []
    already: list[Path] = []
    for p in files:
        txt = p.read_text(encoding="utf-8")
        # 已含正确版本
        if f"{SCRIPT_URL}?v={version}" in txt:
            already.append(p)
            continue
        # 含旧版本(任意 v=) → 替换
        if re.search(re.escape(SCRIPT_URL) + r"\?v=", txt):
            to_patch.append(p)
            continue
        # 不含 → 需新增 (排除主页 orange-office.html)
        if "story_curves_config.js" not in txt and p.name not in ("index.html", "stellar_home.html"):
            to_patch.append(p)

    print(f"扫描总数: {len(files)}")
    print(f"  已是新版本: {len(already)}")
    print(f"  待注入/替换: {len(to_patch)}")
    if args.check:
        return 0

    for p in to_patch:
        txt = p.read_text(encoding="utf-8")
        # 1) 替换旧版本
        if re.search(re.escape(SCRIPT_URL) + r"\?v=", txt):
            new = re.sub(
                re.escape(SCRIPT_URL) + r"\?v=[^\"']+",
                f"{SCRIPT_URL}?v={version}",
                txt,
                count=1,
            )
        else:
            # 2) 在 <head> 区插入 — 放在 google analytics 后最稳
            new = re.sub(
                r"(<script async src=\"https://www\.googletagmanager\.com[^\"]+\"></script>)",
                rf"\1\n  {script_tag}",
                txt,
                count=1,
            )
            if new == txt:
                # 没找到 GA,放在 <head> 末尾
                new = re.sub(r"</head>", f"  {script_tag}\n</head>", txt, count=1)
        p.write_text(new, encoding="utf-8")

    print(f"已应用: {len(to_patch)} 个文件, ?v={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
"""
acquire_portraits.py
职责：为 storymap 中的所有历史人物获取肖像图。

策略（按优先级）：
1. 本地已有缓存（artifacts/story_map/portraits/）：跳过
2. Wikimedia Commons（curated URL 表）：下载公开域历史画像（最权威）
3. LLM API 生成（--api 开启时）：调用 portrait_service.generate_portrait
4. 朝代风格 SVG 占位（兜底）：本地生成，无网络依赖

环境变量：
- LLM_API_KEY 已配置 → API 生成可用

用法：
    python3 tools/build/acquire_portraits.py            # 全部（Wiki + API + SVG）
    python3 tools/build/acquire_portraits.py --limit 5  # 仅前 5 个
    python3 tools/build/acquire_portraits.py --only "李白,杜甫"  # 指定
    python3 tools/build/acquire_portraits.py --force-svg # 强制用 SVG（调试）
    python3 tools/build/acquire_portraits.py --api       # 启用 API 生成
    python3 tools/build/acquire_portraits.py --no-wiki   # 跳过 Wikimedia
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
MD_DIR = REPO_ROOT / "storymap" / "examples" / "story"
PORTRAIT_DIR = REPO_ROOT / "artifacts" / "story_map" / "portraits"

# ---------------------------------------------------------------------------
# Wikimedia Commons 公开域历史画像映射表
# 由工具脚本探测得到；文件名是维基共享资源上经过验证存在的标准肖像。
# 优先于 API 生成，因为它提供真实历史画像，朝代气质最匹配。
# ---------------------------------------------------------------------------
WIKIMEDIA_PORTRAITS: Dict[str, str] = {
    # 中国古代（已验证存在）
    "孔子": "Confucius.jpg",
    "老子": "Laozi.png",
    "庄子": "Zhuangzi.png",
    "孟子": "Mencius.jpg",
    "杜甫": "Du_Fu.jpg",
    "李白": "LiBai.jpg",
    "白居易": "Bai_Juyi.jpg",
    "王维": "Wang_Wei.jpg",
    "欧阳修": "Ouyang_Xiu.jpg",
    "苏轼": "Su_shi.jpg",
    "王安石": "Wang_Anshi.jpg",
    "范仲淹": "Fan_Zhongyan.jpg",
    "李清照": "Li_Qingzhao.jpg",
    "屈原": "Qu_Yuan.jpg",
    "岳飞": "Yue_Fei.jpg",
    "文天祥": "Wen_Tianxiang.jpg",
    "成吉思汗": "Genghis_Khan.jpg",
    "鲁迅": "Luxun.jpg",
    "张飞": "Zhang_Fei.jpg",
    "诸葛亮": "Zhuge_Liang.jpg",
    "李商隐": "Li_Shangyin.jpg",
    "汉武帝": "Emperor_Wu_of_Han.jpg",
    "乾隆": "Qianlong_Emperor.jpg",
    "周恩来": "Zhou_Enlai.jpg",
    # 西洋（已验证存在）
    "苏格拉底": "Socrates_Louvre.jpg",
    "牛顿": "GodfreyKneller-IsaacNewton-1689.jpg",
    "艾萨克·牛顿": "GodfreyKneller-IsaacNewton-1689.jpg",
    "爱因斯坦": "Einstein_1921_by_F_Schmutzer_-_restoration.jpg",
    "阿尔伯特·爱因斯坦": "Einstein_1921_by_F_Schmutzer_-_restoration.jpg",
    "歌德": "Goethe_(Stieler_1828).jpg",
    "约翰·沃尔夫冈·冯·歌德": "Goethe_(Stieler_1828).jpg",
    "爱迪生": "Thomas_Edison2.jpg",
    "托马斯·阿尔瓦·爱迪生": "Thomas_Edison2.jpg",
    "林肯": "Abraham_Lincoln_O-77_matte_collodion_print.jpg",
    "亚伯拉罕·林肯": "Abraham_Lincoln_O-77_matte_collodion_print.jpg",
    "雨果": "Victor_Hugo.jpg",
    "维克多·雨果": "Victor_Hugo.jpg",
    "伽利略": "Galileo.arp.300pix.jpg",
    "伽利略·伽利莱": "Galileo.arp.300pix.jpg",
    "海明威": "ErnestHemingway.jpg",
    "欧内斯特·米勒·海明威": "ErnestHemingway.jpg",
    "梵高": "Vincent_van_Gogh_-_Self-Portrait_-_Google_Art_Project.jpg",
    "文森特·威廉·梵高": "Vincent_van_Gogh_-_Self-Portrait_-_Google_Art_Project.jpg",
    "马克思": "Karl_Marx.jpg",
    "卡尔·马克思": "Karl_Marx.jpg",
    "达尔文": "Charles_Darwin.jpg",
    "查尔斯·罗伯特·达尔文": "Charles_Darwin.jpg",
    "巴赫": "Johann_Sebastian_Bach.jpg",
    "约翰·塞巴斯蒂安·巴赫": "Johann_Sebastian_Bach.jpg",
    "乾隆": "Qianlong_Emperor.jpg",
}


def try_wikimedia(name: str) -> Optional[Path]:
    """从 Wikimedia Commons 拉取公开域历史画像（最权威）。"""
    fname = WIKIMEDIA_PORTRAITS.get(name)
    if not fname:
        return None
    base = PORTRAIT_DIR / safe_filename(name)
    # 推断扩展名
    ext = "." + fname.split(".")[-1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    dest = base.with_suffix(ext)
    if dest.exists() and dest.stat().st_size > 2048:
        return dest
    # 维基 Special:FilePath 会 302 跳转到真实 CDN URL
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(fname)}"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 1024:
            return None
        dest.write_bytes(data)
        return dest
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"  [wiki] fail {name}: {e}", file=sys.stderr)
        return None

# 朝代配色（背景渐变）
DYNASTY_PALETTE: Dict[str, Tuple[str, str, str]] = {
    "唐":  ("#a8351c", "#e8b066", "#7a2010"),  # 赤红+金
    "宋":  ("#1d3a5c", "#7090b0", "#0c1c30"),  # 群青+雾蓝
    "元":  ("#5a4a2c", "#c4a870", "#3a2d18"),  # 赭石+金
    "明":  ("#3d1f1f", "#8a5050", "#251010"),  # 暗红
    "清":  ("#2c4458", "#7a90a8", "#1a2838"),  # 藏蓝
    "汉":  ("#7a1f1f", "#c45a3c", "#4a0c0c"),  # 朱砂
    "魏晋": ("#3d4a3a", "#8a9c7a", "#202820"),  # 竹绿
    "近代": ("#2a2a3a", "#7070a0", "#14141c"),  # 灰蓝
    "清末": ("#2c4458", "#7a90a8", "#1a2838"),
    "现代": ("#3a3a4a", "#8090a0", "#1c1c28"),
    "当代": ("#3a3a4a", "#8090a0", "#1c1c28"),
    "default": ("#3a3a4a", "#8090a0", "#1c1c28"),
}


def safe_filename(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)[:48]
    return f"{safe}-{digest}"


def has_cached_portrait(name: str) -> Optional[Path]:
    """如果本地已有非占位肖像，返回路径；否则返回 None。
    支持 .jpg/.png/.webp/.gif/.svg 五种扩展名。
    二进制格式（jpg/png/webp/gif）需 >2KB；SVG 因可压缩可更小，>200B 即可。
    """
    base = PORTRAIT_DIR / safe_filename(name)
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        p = base.with_suffix(ext)
        if p.exists() and p.stat().st_size > 2048:
            return p
    for ext in (".svg",):
        p = base.with_suffix(ext)
        if p.exists() and p.stat().st_size > 200:
            return p
    return None


def get_dynasty_palette(dyn: str) -> Tuple[str, str, str]:
    for key, palette in DYNASTY_PALETTE.items():
        if key in dyn:
            return palette
    return DYNASTY_PALETTE["default"]


# ---------------------------------------------------------------------------
# Wikipedia / Wikimedia 抓图
# ---------------------------------------------------------------------------
WIKIMEDIA_HEADERS = {
    "User-Agent": "StoryMapPortraitBot/1.0 (educational project; +https://example.com)",
    "Accept": "application/json",
}


def _http_get_json(url: str, timeout: int = 15) -> Optional[dict]:
    try:
        req = Request(url, headers=WIKIMEDIA_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  [wiki] http fail: {e}", file=sys.stderr)
        return None


def _download_to(url: str, dest: Path, timeout: int = 30) -> bool:
    try:
        req = Request(url, headers=WIKIMEDIA_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 1024:
            return False
        dest.write_bytes(data)
        return True
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"  [wiki] download fail {url}: {e}", file=sys.stderr)
        return False


def try_wikipedia(name: str, lang: str = "zh") -> Optional[Path]:
    """尝试从维基百科获取该人物的肖像图。

    1) 通过 MediaWiki API 找到该词条
    2) 抓取页面 wikitext，提取 |image = ... 或 |肖像 = ...
    3) 用 File:xxx 名字到 commons 查 imageinfo，下载 thumb
    """
    base = PORTRAIT_DIR / safe_filename(name)
    # 尝试过的扩展名
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = base.with_suffix(ext)
        if candidate.exists() and candidate.stat().st_size > 2048:
            return candidate

    api = f"https://{lang}.wikipedia.org/w/api.php"
    # 1) 搜索标题
    search_url = (
        f"{api}?action=query&format=json&prop=pageimages|images"
        f"&piprop=original&titles={quote(name)}&redirects=1"
    )
    data = _http_get_json(search_url)
    pages = (data or {}).get("query", {}).get("pages", {}) if data else {}
    page = next(iter(pages.values()), {}) if pages else {}
    if not page or page.get("missing"):
        # 兜底：再尝试不带前缀的搜索
        search_url = (
            f"{api}?action=opensearch&format=json&limit=1"
            f"&search={quote(name)}"
        )
        data2 = _http_get_json(search_url)
        if data2 and len(data2) >= 2 and data2[1]:
            title = data2[1][0]
            search_url = (
                f"{api}?action=query&format=json&prop=pageimages"
                f"&piprop=original&titles={quote(title)}&redirects=1"
            )
            data = _http_get_json(search_url)
            pages = (data or {}).get("query", {}).get("pages", {}) if data else {}
            page = next(iter(pages.values()), {}) if pages else {}
    if not page:
        return None
    original = page.get("original") or {}
    if original.get("source"):
        url = original["source"]
        ext = "." + url.split(".")[-1].lower().split("?")[0]
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
        dest = base.with_suffix(ext)
        if _download_to(url, dest):
            return dest
    # 2) 通过 wikitext 提取肖像字段
    title = page.get("title") or name
    wt_url = (
        f"{api}?action=parse&format=json&prop=wikitext"
        f"&page={quote(title)}&redirects=1"
    )
    wt_data = _http_get_json(wt_url)
    wikitext = ""
    if wt_data:
        wikitext = wt_data.get("parse", {}).get("wikitext", {}).get("*", "")
    m = re.search(r"(?:\|image|肖像图|肖像)\s*=\s*([^\n|]+)", wikitext)
    if not m:
        return None
    raw = m.group(1).strip()
    # 可能是 File:xxx.jpg 或是 xxx.jpg
    if raw.lower().startswith("file:"):
        fname = raw[5:].strip()
    elif "/" in raw:
        fname = raw.split("/")[-1]
    else:
        fname = raw
    # 去掉 [[ ]] 包裹
    fname = fname.strip("[]").strip()
    # 去 Commons 查 imageinfo
    commons_api = "https://commons.wikimedia.org/w/api.php"
    info_url = (
        f"{commons_api}?action=query&format=json&prop=imageinfo"
        f"&iiprop=url&iiurlwidth=800&titles={quote('File:' + fname)}"
    )
    info = _http_get_json(info_url)
    if not info:
        return None
    pages2 = info.get("query", {}).get("pages", {})
    p2 = next(iter(pages2.values()), {}) if pages2 else {}
    img_infos = p2.get("imageinfo", [])
    if not img_infos:
        return None
    img_url = img_infos[0].get("thumburl") or img_infos[0].get("url")
    if not img_url:
        return None
    ext = "." + img_url.split(".")[-1].lower().split("?")[0]
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    dest = base.with_suffix(ext)
    if _download_to(img_url, dest):
        return dest
    return None


# ---------------------------------------------------------------------------
# 朝代风格 SVG 占位
# ---------------------------------------------------------------------------
def make_svg_placeholder(name: str, dynasty: str = "") -> Path:
    """生成朝代风格的 SVG 占位图。"""
    base = PORTRAIT_DIR / safe_filename(name)
    dest = base.with_suffix(".svg")
    palette = get_dynasty_palette(dynasty)
    primary, accent, deep = palette
    # 取首字作字标
    initial = re.sub(r"[^\u4e00-\u9fff]", "", name)
    if not initial:
        initial = name[0] if name else "?"
    initial = initial[0] if initial else "?"
    # 取字号作副标（如有）
    sub = ""
    # 朝代做底部装饰
    dyn_label = dynasty.split("（")[0].split("(")[0].strip()[:6] or "古代"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="bg-{safe_filename(name)}" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="{primary}"/>
      <stop offset="100%" stop-color="{deep}"/>
    </linearGradient>
    <radialGradient id="halo-{safe_filename(name)}" cx="50%" cy="40%" r="55%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.55"/>
      <stop offset="60%" stop-color="{accent}" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
    <filter id="grain">
      <feTurbulence type="fractalNoise" baseFrequency="0.95" numOctaves="2"/>
      <feColorMatrix values="0 0 0 0 0.96  0 0 0 0 0.92  0 0 0 0 0.86  0 0 0 0.08 0"/>
      <feComposite in2="SourceGraphic" operator="in"/>
    </filter>
  </defs>
  <rect width="200" height="200" fill="url(#bg-{safe_filename(name)})"/>
  <circle cx="100" cy="80" r="80" fill="url(#halo-{safe_filename(name)})"/>
  <rect width="200" height="200" filter="url(#grain)" opacity="0.6"/>
  <text x="100" y="120" text-anchor="middle" font-size="86" font-family="'Songti SC','STSong','SimSun','serif'" font-weight="700" fill="#fff7e6" stroke="{deep}" stroke-width="2" paint-order="stroke">{initial}</text>
  <text x="100" y="186" text-anchor="middle" font-size="14" font-family="'Songti SC','STSong','SimSun','serif'" fill="{accent}" opacity="0.85">{dyn_label}</text>
</svg>'''
    dest.write_text(svg, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# 枚举人物
# ---------------------------------------------------------------------------
def extract_figure_metadata(md_path: Path) -> Tuple[str, str, str]:
    """从 MD 文件抽取姓名 + 时代。"""
    text = md_path.read_text(encoding="utf-8")
    name_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    raw_name = name_m.group(1).strip() if name_m else md_path.stem
    canon_name = re.split(r"[（(]", raw_name, 1)[0].strip() or raw_name
    dyn_m = re.search(r"\*\*时代\*\*[：:]\s*([^\n]+)", text)
    dynasty = dyn_m.group(1).strip() if dyn_m else ""
    return canon_name, raw_name, dynasty


def list_figures() -> List[Tuple[Path, str, str, str]]:
    """返回 (md_path, canonical_name, raw_name, dynasty)。"""
    out = []
    for p in sorted(MD_DIR.glob("*.md")):
        canon, raw, dyn = extract_figure_metadata(p)
        out.append((p, canon, raw, dyn))
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", type=str, default="")
    parser.add_argument("--force-svg", action="store_true")
    parser.add_argument("--api", action="store_true", help="调用 LLM API 生成")
    parser.add_argument("--no-wiki", action="store_true", help="跳过 Wikimedia")
    parser.add_argument("--no-svg", action="store_true", help="跳过 SVG fallback")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--report", type=str, default="")
    parser.add_argument("--style", type=str, default="ink_wash",
                        choices=["ink_wash", "gongbi", "realistic", "cartoon"])
    args = parser.parse_args()

    PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    figures = list_figures()
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        figures = [f for f in figures if f[1] in wanted or f[2] in wanted or Path(f[0]).stem in wanted]
    if args.limit > 0:
        figures = figures[: args.limit]

    print(f"[acquire] targets: {len(figures)}", file=sys.stderr)
    stats = {"wiki_ok": 0, "wiki_fail": 0, "api_ok": 0, "api_fail": 0, "svg_ok": 0, "skipped": 0}
    rows = []

    # 检测 API 是否可用
    api_available = False
    if args.api:
        try:
            from storymap.script.map.portrait_service import _api_key
            if _api_key():
                api_available = True
            else:
                print("[acquire] LLM_API_KEY 未配置，回退到 SVG", file=sys.stderr)
        except Exception as e:
            print(f"[acquire] portrait_service import fail: {e}", file=sys.stderr)

    for idx, (md, canon, raw, dyn) in enumerate(figures, 1):
        cached = has_cached_portrait(canon) or has_cached_portrait(raw)
        if cached and not args.force_svg:
            stats["skipped"] += 1
            rows.append((canon, dyn, "cached", str(cached)))
            print(f"[{idx:>3}/{len(figures)}] {canon} — cached {Path(cached).name}")
            continue

        path: Optional[Path] = None

        # 1) Wikimedia Commons（真实历史画像，最优）
        if not args.no_wiki and not args.force_svg:
            try:
                # 仅对在 WIKIMEDIA_PORTRAITS 表中的人物尝试 Wiki
                p = try_wikimedia(canon)
                if p and p.exists() and p.stat().st_size > 2048:
                    path = p
                    stats["wiki_ok"] += 1
                    print(f"[{idx:>3}/{len(figures)}] {canon} — wikimedia {p.name} ({p.stat().st_size//1024}KB)")
                elif canon in WIKIMEDIA_PORTRAITS:
                    stats["wiki_fail"] += 1
                    # Wiki 失败但有表项 → 节流 3s 避免连坐
                    time.sleep(3)
            except Exception as e:
                stats["wiki_fail"] += 1
                print(f"[{idx:>3}/{len(figures)}] {canon} — wikimedia err: {e}", file=sys.stderr)

        # 2) API 生成
        if path is None and api_available and not args.force_svg:
            try:
                from storymap.script.map.portrait_service import (
                    PortraitRequest, generate_portrait,
                )
                short_bio = ""
                try:
                    md_text = md.read_text(encoding="utf-8")
                    bio_match = re.search(r"\*\*历史地位\*\*[：:]\s*([^\n]+)", md_text)
                    if bio_match:
                        short_bio = bio_match.group(1).strip()[:80]
                except Exception:
                    pass
                req = PortraitRequest(
                    name=canon, dynasty=dyn, title="",
                    short_bio=short_bio, style=args.style, aspect_ratio="1:1"
                )
                primary, _, from_cache = generate_portrait(req, force=False, n=1)
                if primary and primary.exists() and primary.stat().st_size > 0:
                    path = primary
                    stats["api_ok"] += 1
                    src = "api-cached" if from_cache else "api-generated"
                    print(f"[{idx:>3}/{len(figures)}] {canon} — {src} {primary.name}")
            except Exception as e:
                stats["api_fail"] += 1
                print(f"[{idx:>3}/{len(figures)}] {canon} — api fail: {e}", file=sys.stderr)

        # 3) SVG fallback（仅当未开启 --no-svg 时）
        if path is None and not args.no_svg:
            path = make_svg_placeholder(canon, dyn)
            stats["svg_ok"] += 1
            print(f"[{idx:>3}/{len(figures)}] {canon} — svg placeholder {path.name}")

        rows.append((canon, dyn, path.suffix.lstrip(".") if path else "missing", str(path)))

        # 礼貌节流维基
        time.sleep(0.5)

    print()
    print(f"[acquire] done: {stats}", file=sys.stderr)

    if args.report:
        Path(args.report).write_text(
            json.dumps([{"name": r[0], "dynasty": r[1], "source": r[2], "path": r[3]} for r in rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[acquire] report -> {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
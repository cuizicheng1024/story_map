#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_pure_story_map.py

纯 HTML（高德地图）生成入口。

目标：
- 只产出交互式 HTML 地图（高德底图）
- 不依赖 / 不触发任何 matplotlib 等静态海报逻辑

用法示例：
  python3 cli/generate_pure_story_map.py --md storymap/examples/story/苏轼.md
  python3 cli/generate_pure_story_map.py --person 苏轼

输出：默认写入 artifacts/story_map/ 目录。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from urllib.parse import quote

from storymap.script.project_paths import (
    BAD_PERSON_NAMES,
    classify_story_markdown_authenticity,
    classify_story_person_authenticity,
    is_publishable_person_markdown,
    person_name_from_filename,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
)


def _is_usable_result(result: dict) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


def _repo_root() -> str:
    return str(project_root_path())


def _story_artifacts_dir() -> str:
    return str(story_artifacts_dir_path())


def _add_import_paths() -> None:
    root = _repo_root()
    new_path = os.path.join(root, "storymap", "script")
    old_path = os.path.join(root, "map_story", "storymap", "script")
    for p in [new_path, old_path]:
        if p not in sys.path:
            sys.path.insert(0, p)


def _default_md_path(person: str) -> str:
    return str(story_md_dir_path() / f"{person}.md")


def _canonical_html_path(person: str) -> str:
    return str((story_artifacts_dir_path() / f"{person}.html").resolve())


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def generate_pure_html(md_path: str, out_path: Optional[str] = None, *, no_geocode: bool = False) -> dict:
    """Generate pure AMap HTML and return metadata."""

    md_path = os.path.abspath(md_path)
    accepted, reason = classify_story_markdown_authenticity(Path(md_path))
    if not accepted:
        raise RuntimeError(f"人物真实性过滤拦截：{Path(md_path).stem} ({reason})")

    _add_import_paths()
    import story_map as sm
    import map_html_renderer as renderer

    md = _read_text(md_path)
    if not md.strip():
        raise RuntimeError(f"Markdown 为空或无法读取：{md_path}")

    t0 = time.perf_counter()

    person_name = Path(md_path).stem
    if no_geocode:
        profile = sm.load_profile_from_md(md, allow_geocode=False)
        t1 = time.perf_counter()
        if profile:
            profile["markdown"] = md
            html = renderer.render_profile_html(profile)
            person_name = (profile.get("person") or {}).get("name") or person_name
        else:
            places = sm.parse_places(md)
            events = sm.parse_events(md)
            points = sm.build_points(places, events, allow_geocode=False)
            fields = sm.extract_intro_fields(md)
            info_panel_html = sm.build_info_panel_html(person_name, fields) if any(fields.values()) else ""
            html = sm.render_amap_html(person_name, points, info_panel_html)
    else:
        profile = sm.load_profile_from_md(md)
        t1 = time.perf_counter()
        if profile:
            profile["markdown"] = md
            html = renderer.render_profile_html(profile)
            person_name = (profile.get("person") or {}).get("name") or person_name
        else:
            places = sm.parse_places(md)
            events = sm.parse_events(md)
            points = sm.build_points(places, events)
            html = sm.render_html(person_name, points, md)

    t2 = time.perf_counter()

    if not out_path:
        out_dir = _story_artifacts_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"{person_name}__pure__{ts}.html")

    _write_text(out_path, html)

    try:
        _sync_alias_redirect_pages(Path(_story_artifacts_dir()).resolve())
    except Exception:
        pass
    t3 = time.perf_counter()

    return {
        "html_path": out_path,
        "duration": {
            "parse": f"{(t1 - t0) * 1000:.1f}ms",
            "render": f"{(t2 - t1) * 1000:.1f}ms",
            "write": f"{(t3 - t2) * 1000:.1f}ms",
            "total": f"{(t3 - t0) * 1000:.1f}ms",
        },
    }


def accept_person_html(person: str, *, mode: str = "pure", no_browser: bool = True) -> dict:
    person_name = str(person or "").strip()
    if not person_name:
        raise RuntimeError("需要提供人物名")
    md_dir = story_md_dir_path()
    try:
        from storymap.script.person_registry import person_redirects
        # 单页验收要以当前真实 Markdown 集合为准，不能无脑做 alias canonical；
        # 否则像“苏东坡.md”这样的真实页面会被重新跳回别的人物页。
        redirects = person_redirects(_scan_people_from_story_md(md_dir))
        person_name = str(redirects.get(person_name, person_name) or "").strip() or person_name
    except Exception:
        pass
    accepted, reason = classify_story_person_authenticity(person_name, md_dir, allow_unknown=False)
    if not accepted:
        raise RuntimeError(f"人物真实性过滤拦截：{person_name} ({reason})")
    md_path = _default_md_path(person_name)
    out_path = _canonical_html_path(person_name)
    if mode == "cache":
        html_dir = Path(_story_artifacts_dir()).resolve()
        rc = _render_people([person_name], md_dir=md_dir, html_dir=html_dir, mode=mode, allow_cache=False)
        if rc != 0:
            raise RuntimeError(f"单页验收失败：{person_name}")
        if not _refresh_homepage_once():
            raise RuntimeError(f"单页验收失败：首页刷新失败：{person_name}")
        _sync_alias_redirect_pages(html_dir)
        result = {"html_path": out_path, "duration": {}}
    else:
        result = generate_pure_html(md_path=md_path, out_path=out_path, no_geocode=(mode == "nogeocode"))
    if not no_browser:
        try:
            webbrowser.open(f"file://{os.path.abspath(result['html_path'])}")
        except Exception:
            pass
    return result


def impact_render_html(*, mode: str = "nogeocode", max_people: int = 0) -> int:
    return render_changed_people_html(mode=mode, max_people=max_people)


def publish_all_html(*, mode: str = "nogeocode") -> int:
    return render_all_people_html(mode=mode)


def _scan_people_from_story_md(story_md_dir: Path) -> Set[str]:
    if not story_md_dir.exists():
        return set()
    return {
        p.stem.strip()
        for p in story_md_dir.glob("*.md")
        if p.is_file()
        and p.stem.strip()
        and p.stem.strip() not in BAD_PERSON_NAMES
        and is_publishable_person_markdown(p)
    }


def _scan_people_from_story_map_html(story_map_dir: Path) -> Set[str]:
    if not story_map_dir.exists():
        return set()
    out: Set[str] = set()
    for p in story_map_dir.glob("*.html"):
        if not p.is_file():
            continue
        if p.name == "index.html":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        # alias redirect stub 不应被当成“真实人物页已存在”，否则 render-missing
        # 会跳过本该补刷的独立人物页。
        if "window.__EXPORT_DATA__" not in text:
            continue
        person = person_name_from_filename(p.name).strip()
        if person:
            out.add(person)
    return out


def _render_workers() -> int:
    return max(1, int(os.getenv("MAP_STORY_RENDER_CONCURRENCY", "4") or "4"))


def _template_dependency_paths(root: Path) -> list[Path]:
    from storymap.script.map_html_renderer import profile_render_dependency_paths

    return list(profile_render_dependency_paths(root))


def _latest_mtime(paths: list[Path]) -> float:
    vals = []
    for p in paths:
        if p.exists():
            vals.append(p.stat().st_mtime)
    return max(vals) if vals else 0.0


def _current_profile_signature() -> str:
    from storymap.script.map_html_renderer import profile_template_signature

    return str(profile_template_signature() or "").strip()


def _extract_html_template_signature(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    m = re.search(r'"templateSignature"\s*:\s*"([^"]+)"', text)
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def _changed_people(md_dir: Path, html_dir: Path) -> list[tuple[str, str]]:
    deps_mtime = _latest_mtime(_template_dependency_paths(Path(_repo_root()).resolve()))
    expected_signature = _current_profile_signature()
    out: list[tuple[str, str]] = []
    md_people = sorted([p for p in _scan_people_from_story_md(md_dir) if p not in BAD_PERSON_NAMES])
    for person in md_people:
        md_path = md_dir / f"{person}.md"
        html_path = html_dir / f"{person}.html"
        if not html_path.exists():
            out.append((person, "missing_html"))
            continue
        if expected_signature and _extract_html_template_signature(html_path) != expected_signature:
            out.append((person, "template_newer"))
            continue
        try:
            md_mtime = md_path.stat().st_mtime
            html_mtime = html_path.stat().st_mtime
        except Exception:
            out.append((person, "stat_failed"))
            continue
        if md_mtime > html_mtime:
            out.append((person, "md_newer"))
            continue
        if deps_mtime > html_mtime:
            out.append((person, "template_newer"))
            continue
    return out


def _render_people(people: list[str], *, md_dir: Path, html_dir: Path, mode: str, allow_cache: bool) -> int:
    _add_import_paths()
    import story_map as sm

    def work(person: str) -> tuple[str, str, float, str]:
        t0 = time.perf_counter()
        try:
            if mode == "cache":
                result = sm.generate_for_person(
                    client=None,
                    person=person,
                    progress=None,
                    allow_cache=allow_cache,
                    refresh_homepage=False,
                )
                if bool(result.get("ok")):
                    return (person, "ok", time.perf_counter() - t0, "")
                if _is_usable_result(result):
                    info = str(result.get("warning") or result.get("error") or result.get("quality_issue_summary") or "degraded").strip()
                    return (person, "degraded", time.perf_counter() - t0, info)
                info = str(result.get("error") or "render failed").strip()
                return (person, "fail", time.perf_counter() - t0, info)
            else:
                md_path = str((md_dir / f"{person}.md").resolve())
                out_path = str((html_dir / f"{person}.html").resolve())
                generate_pure_html(md_path=md_path, out_path=out_path, no_geocode=(mode == "nogeocode"))
            return (person, "ok", time.perf_counter() - t0, "")
        except Exception as exc:
            return (person, "fail", time.perf_counter() - t0, str(exc).replace("\n", " ").strip())

    ok = 0
    degraded = 0
    fail = 0
    done = 0
    with ThreadPoolExecutor(max_workers=_render_workers()) as ex:
        futs = [ex.submit(work, person) for person in people]
        for fut in as_completed(futs):
            person, outcome, dt, info = fut.result()
            done += 1
            if outcome == "ok":
                ok += 1
                tag = "OK"
            elif outcome == "degraded":
                degraded += 1
                tag = "WARN"
            else:
                fail += 1
                tag = "FAIL"
            info = (info[:160] + "…") if len(info) > 160 else info
            print(f"[{done}/{len(people)}] {tag} {person} {dt:.2f}s {info}".rstrip(), flush=True)
    print(f"done ok={ok} degraded={degraded} fail={fail} total={ok+degraded+fail}")
    return 0 if (fail == 0 and degraded == 0) else 2


def _refresh_homepage_once() -> bool:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from storymap.script.artifacts import refresh_stellar_homepage  # type: ignore
    except Exception:
        return False
    try:
        result = refresh_stellar_homepage("")
    except Exception:
        return False
    return bool((result or {}).get("ok"))


def _sync_alias_redirect_pages(html_dir: Path) -> None:
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from tools import build_stellar_homepage as homepage  # type: ignore
        from storymap.script.person_registry import person_redirects  # type: ignore
    except Exception:
        return
    # 这里必须保留动态过滤后的结果；如果过滤后为空，意味着当前磁盘上
    # 没有需要生成的 alias redirect，不能再回退到静态映射把真实人物页覆盖掉。
    redirects = person_redirects(_scan_people_from_story_md(story_md_dir_path()))
    render_redirect = getattr(homepage, "_render_person_alias_redirect_html", None)
    if not isinstance(redirects, dict) or not callable(render_redirect):
        return
    html_dir.mkdir(parents=True, exist_ok=True)
    for alias, canonical in redirects.items():
        alias_name = str(alias or "").strip()
        canonical_name = str(canonical or "").strip()
        if not alias_name or not canonical_name:
            continue
        try:
            (html_dir / f"{alias_name}.html").write_text(
                render_redirect(alias_name, canonical_name),
                encoding="utf-8",
            )
        except Exception:
            continue


def render_missing_people_html(*, max_people: int = 0, mode: str = "nogeocode") -> int:
    md_dir = story_md_dir_path()
    html_dir = Path(_story_artifacts_dir()).resolve()
    md_people = _scan_people_from_story_md(md_dir)
    html_people = _scan_people_from_story_map_html(html_dir)
    missing = sorted([p for p in (md_people - html_people) if p not in BAD_PERSON_NAMES])

    if max_people and max_people > 0:
        missing = missing[:max_people]

    print(f"md={len(md_people)} html_people={len(html_people)} missing={len(missing)}")
    rc = _render_people(missing, md_dir=md_dir, html_dir=html_dir, mode=mode, allow_cache=True)
    homepage_ok = True
    if mode == "cache":
        homepage_ok = _refresh_homepage_once() is not False
    _sync_alias_redirect_pages(html_dir)
    return rc if rc != 0 or homepage_ok else 2


def render_all_people_html(*, mode: str = "nogeocode") -> int:
    md_dir = story_md_dir_path()
    html_dir = Path(_story_artifacts_dir()).resolve()

    md_people = sorted([p for p in _scan_people_from_story_md(md_dir) if p not in BAD_PERSON_NAMES])
    print(f"md={len(md_people)} mode={mode}")
    rc = _render_people(md_people, md_dir=md_dir, html_dir=html_dir, mode=mode, allow_cache=False)
    homepage_ok = True
    if mode == "cache":
        homepage_ok = _refresh_homepage_once() is not False
    _sync_alias_redirect_pages(html_dir)
    return rc if rc != 0 or homepage_ok else 2

 
def render_changed_people_html(*, mode: str = "nogeocode", max_people: int = 0) -> int:
    md_dir = story_md_dir_path()
    html_dir = Path(_story_artifacts_dir()).resolve()
    changed = _changed_people(md_dir, html_dir)
    reason_counts: dict[str, int] = {}
    for _, reason in changed:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    if max_people and max_people > 0:
        changed = changed[:max_people]
    summary = " ".join([f"{k}={v}" for k, v in sorted(reason_counts.items())])
    print(f"changed={len(changed)}" + (f" {summary}" if summary else ""))
    if not changed:
        print("done ok=0 fail=0 total=0")
        homepage_ok = True
        if mode == "cache":
            homepage_ok = _refresh_homepage_once() is not False
        _sync_alias_redirect_pages(html_dir)
        return 0 if homepage_ok else 2
    people = [person for person, _ in changed]
    rc = _render_people(people, md_dir=md_dir, html_dir=html_dir, mode=mode, allow_cache=False)
    homepage_ok = True
    if mode == "cache":
        homepage_ok = _refresh_homepage_once() is not False
    _sync_alias_redirect_pages(html_dir)
    return rc if rc != 0 or homepage_ok else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="纯 HTML（高德地图）生成：只输出交互式 HTML")
    parser.add_argument("--md", type=str, help="直接指定人物 Markdown 路径")
    parser.add_argument("-p", "--person", type=str, help="人物名（用于定位 examples/story/<person>.md）")
    parser.add_argument("--out", type=str, help="输出 HTML 路径（可选）")
    parser.add_argument("--render-missing", action="store_true", help="批量渲染：为缺失 HTML 的人物补齐 artifacts/story_map/<person>.html（不调用模型）")
    parser.add_argument("--render-all", action="store_true", help="批量渲染：重渲染所有人物 HTML 到 artifacts/story_map/<person>.html")
    parser.add_argument("--render-changed", action="store_true", help="批量渲染：只重建 Markdown 更新或模板失效的人物 HTML")
    parser.add_argument("--accept-person", type=str, help="单页验收：生成并覆盖 artifacts/story_map/<person>.html")
    parser.add_argument("--accept-mode", type=str, default="pure", choices=["nogeocode", "pure", "cache"], help="单页验收模式：nogeocode=不做地理编码；pure=正常渲染；cache=走完整缓存刷新链路")
    parser.add_argument("--impact-render", action="store_true", help="影响面渲染：只重建受 Markdown 或模板变更影响的人物页")
    parser.add_argument("--impact-mode", type=str, default="nogeocode", choices=["nogeocode", "pure", "cache"], help="影响面渲染模式：nogeocode=最快；pure=正常渲染；cache=强制刷新缓存")
    parser.add_argument("--publish-all", action="store_true", help="全量发布：重建所有人物页到 artifacts/story_map/<person>.html")
    parser.add_argument("--publish-mode", type=str, default="nogeocode", choices=["nogeocode", "pure", "cache"], help="全量发布模式：nogeocode=最快；pure=正常渲染；cache=强制刷新缓存")
    parser.add_argument("--missing-limit", type=int, default=0, help="批量渲染时，最多处理多少人（0 表示不限制）")
    parser.add_argument("--missing-mode", type=str, default="nogeocode", choices=["nogeocode", "pure", "cache"], help="nogeocode=不做地理编码（最快）；pure=正常渲染（可能触发地理编码）；cache=复用 Markdown 并做地理编码+渲染（最慢）")
    parser.add_argument("--all-mode", type=str, default="nogeocode", choices=["nogeocode", "pure", "cache"], help="render-all 时的模式：nogeocode=最快；pure=可能触发地理编码；cache=强制刷新缓存")
    parser.add_argument("--changed-mode", type=str, default="nogeocode", choices=["nogeocode", "pure", "cache"], help="render-changed 时的模式：nogeocode=最快；pure=可能触发地理编码；cache=强制刷新缓存")
    parser.add_argument("--changed-limit", type=int, default=0, help="render-changed 时最多处理多少人（0 表示不限制）")
    parser.add_argument("--no-geocode", action="store_true", help="生成单人 HTML 时不触发地理编码（只渲染现有坐标）")
    parser.add_argument("--no-browser", action="store_true", help="生成单人 HTML 后不自动打开浏览器")
    args = parser.parse_args()

    accept_person = getattr(args, "accept_person", None)
    accept_mode = getattr(args, "accept_mode", "pure")
    impact_render = bool(getattr(args, "impact_render", False))
    impact_mode = getattr(args, "impact_mode", "nogeocode")
    publish_all = bool(getattr(args, "publish_all", False))
    publish_mode = getattr(args, "publish_mode", "nogeocode")

    if accept_person:
        result = accept_person_html(
            str(accept_person),
            mode=str(accept_mode or "pure"),
            no_browser=bool(args.no_browser),
        )
        html_path = result["html_path"]
        file_url = "file://" + quote(os.path.abspath(html_path))
        print(f"HTML: {html_path}")
        print(f"Open: {file_url}")
        d = result.get("duration") or {}
        if d:
            print(f"耗时：解析 {d.get('parse')}，渲染 {d.get('render')}，写入 {d.get('write')}，总计 {d.get('total')}")
        raise SystemExit(0)
    if impact_render:
        raise SystemExit(impact_render_html(mode=str(impact_mode or "pure"), max_people=int(args.changed_limit or 0)))
    if publish_all:
        raise SystemExit(publish_all_html(mode=str(publish_mode or "pure")))
    if args.render_missing:
        raise SystemExit(render_missing_people_html(max_people=int(args.missing_limit or 0), mode=str(args.missing_mode or "nogeocode")))
    if args.render_all:
        raise SystemExit(render_all_people_html(mode=str(args.all_mode or "nogeocode")))
    if args.render_changed:
        raise SystemExit(render_changed_people_html(mode=str(args.changed_mode or "nogeocode"), max_people=int(args.changed_limit or 0)))

    md_path: Optional[str] = args.md
    if not md_path:
        if not args.person:
            raise SystemExit("需要提供 --md 或 --person")
        md_path = _default_md_path(args.person)

    result = generate_pure_html(md_path=md_path, out_path=args.out, no_geocode=bool(args.no_geocode))

    html_path = result["html_path"]
    file_url = "file://" + quote(os.path.abspath(html_path))

    print(f"HTML: {html_path}")
    print(f"Open: {file_url}")

    # 自动在默认浏览器中打开 HTML 地图
    if not args.no_browser:
        try:
            webbrowser.open(f"file://{os.path.abspath(html_path)}")
        except Exception:
            pass

    d = result.get("duration") or {}
    print(f"耗时：解析 {d.get('parse')}，渲染 {d.get('render')}，写入 {d.get('write')}，总计 {d.get('total')}")


if __name__ == "__main__":
    main()

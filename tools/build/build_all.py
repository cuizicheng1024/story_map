#!/usr/bin/env python3
"""build_all.py - 数据单源构建入口

职责：
  1. 重新生成 data/corpus/people_master.json（教材总索引；旧 data/people_master.json 软链兼容）
  2. 重新生成 data/corpus/people_master_pep.json（PEP 教材人物；旧根路径软链兼容）
  3. 增量重渲染 artifacts/story_map/*.html（人物页）
  4. 重新生成 data/corpus/people_birth_coords_wgs84.json（出生地经纬度；旧根路径软链兼容）
  5. 重新生成 data/corpus/people_summary_index.json（人物摘要索引；旧根路径软链兼容）
  6. 重新生成 data/corpus/work_summary_index.json（作品摘要索引；旧根路径软链兼容）
  7. 重新生成 artifacts/story_map/stellar_home_data.json + index.html

数据源：单一来源 = storymap/examples/story/*.md
幂等：默认不会触发 LLM 补缺；批量人物页渲染默认走 nogeocode 模式，专门补坐标时再显式切到 pure/cache。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from storymap.script.project_paths import (
    BAD_PERSON_NAMES,
    classify_story_markdown_authenticity,
    data_reports_output_path,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
    story_person_names,
)
from storymap.script.map_html_renderer import profile_template_signature

REPO_ROOT = project_root_path()
STORY_DIR = story_md_dir_path()
STORY_MAP_DIR = story_artifacts_dir_path()
DATA_DIR = REPO_ROOT / "data"
HOME_DATA = STORY_MAP_DIR / "stellar_home_data.json"
HOME_DETAIL_DATA = STORY_MAP_DIR / "stellar_home_data_detail.json"
MANIFEST_JSON = data_reports_output_path("build_manifest.json")
VALIDATION_JSON = data_reports_output_path("build_validation_report.json")
MARKDOWN_SMOKE_JSON = data_reports_output_path("markdown_smoke_report.json")
LOW_COVERAGE_JSON = data_reports_output_path("low_coverage_story_report.json")
LOW_COVERAGE_MD = data_reports_output_path("low_coverage_story_report.md")
PERF_BASELINE_JSON = data_reports_output_path("performance_baseline.json")


def _data_corpus_input_path(filename: str) -> Path:
    candidate = DATA_DIR / "corpus" / filename
    return candidate if candidate.exists() else (DATA_DIR / filename)


def _data_corpus_output_path(filename: str) -> Path:
    corpus_dir = DATA_DIR / "corpus"
    return (corpus_dir / filename) if corpus_dir.exists() else (DATA_DIR / filename)


def _print_section(title: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}\n  {title}\n{bar}", flush=True)


def _run(cmd: list[str], cwd: str | None = None) -> int:
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=cwd or str(REPO_ROOT))


def _git_changed_story_files() -> list[Path]:
    story_prefix = "storymap/examples/story/"
    changed: set[Path] = set()
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD", "--", story_prefix],
        ["git", "ls-files", "--others", "--exclude-standard", "--", story_prefix],
    ]
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        for raw in out.splitlines():
            rel = raw.strip()
            if not rel.endswith(".md"):
                continue
            p = (REPO_ROOT / rel).resolve()
            if p.exists():
                changed.add(p)
    return sorted(changed)


def _run_markdown_smoke_check(scope: str) -> int:
    scope = (scope or "off").strip().lower()
    if scope == "off":
        print("  · 已跳过 Markdown 冒烟校验", flush=True)
        return 0
    files: list[Path]
    if scope == "all":
        files = _story_files()
    else:
        files = _git_changed_story_files()
    if not files:
        print("  · 未发现需要校验的 Markdown 变更", flush=True)
        return 0
    cmd = [
        sys.executable,
        "tools/validate_story_markdown.py",
        "--report-json",
        str(MARKDOWN_SMOKE_JSON),
        "--files",
        *[str(p.relative_to(REPO_ROOT)) for p in files],
    ]
    return _run(cmd)


def _story_files() -> list[Path]:
    if not STORY_DIR.exists():
        return []
    return sorted(STORY_DIR.glob("*.md"))


def _story_people() -> list[str]:
    return sorted(set(story_person_names(STORY_DIR)))


def _existing_htmls() -> set[str]:
    if not STORY_MAP_DIR.exists():
        return set()
    return {p.stem for p in STORY_MAP_DIR.glob("*.html") if _is_export_profile_html(p)}


def _is_export_profile_html(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if path.name == "index.html":
        return False
    stem = path.stem.strip()
    if not stem or "__pure__" in stem or stem in BAD_PERSON_NAMES:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "window.__EXPORT_DATA__" in text


def _canonical_html_people() -> list[str]:
    out: list[str] = []
    if not STORY_MAP_DIR.exists():
        return out
    for p in STORY_MAP_DIR.glob("*.html"):
        if not _is_export_profile_html(p):
            continue
        out.append(p.stem.strip())
    return sorted(set(out))


def _rejected_story_people() -> set[str]:
    rejected: set[str] = set()
    for path in _story_files():
        name = path.stem.strip()
        if not name or name in BAD_PERSON_NAMES:
            continue
        accepted, _ = classify_story_markdown_authenticity(path)
        if not accepted:
            rejected.add(name)
    return rejected


def _cleanup_non_publishable_artifacts() -> dict:
    removed: list[str] = []
    if not STORY_MAP_DIR.exists():
        return {"removed": 0, "samples": []}
    rejected_people = _rejected_story_people()
    for path in sorted(STORY_MAP_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.name == "index.html":
            continue
        stem = path.stem.strip()
        suffix = path.suffix.lower()
        should_delete = False
        if "__pure__" in stem and suffix == ".html":
            should_delete = True
        elif stem in BAD_PERSON_NAMES:
            should_delete = True
        elif stem in rejected_people and suffix in {".html", ".csv"}:
            should_delete = True
        if not should_delete:
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except Exception:
            continue
    return {"removed": len(removed), "samples": removed[:20]}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime": round(stat.st_mtime, 3),
        "sha1": _sha1_file(path)[:12],
        "path": str(path.relative_to(REPO_ROOT)),
    }


def _gzip_size_bytes(path: Path) -> int | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return len(gzip.compress(path.read_bytes(), compresslevel=6))
    except Exception:
        return None


def _safe_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return None


def _home_payload_metrics(path: Path) -> dict:
    if not path.exists():
        return {
            "nodes": 0,
            "edges": 0,
            "kg_edges": 0,
            "nodes_with_coords": 0,
            "nodes_with_story": 0,
            "nodes_with_work_summaries": 0,
            "total_aliases": 0,
            "total_works": 0,
            "total_work_summaries": 0,
            "year_range": {"min_year": None, "max_year": None},
        }
    try:
        payload = _read_json(path)
    except Exception:
        payload = {}
    nodes = payload.get("nodes") if isinstance(payload, dict) and isinstance(payload.get("nodes"), list) else []
    edges = payload.get("edges") if isinstance(payload, dict) and isinstance(payload.get("edges"), list) else []
    kg_edges = payload.get("kg_edges") if isinstance(payload, dict) and isinstance(payload.get("kg_edges"), list) else []
    nodes_with_coords = 0
    nodes_with_story = 0
    nodes_with_work_summaries = 0
    total_aliases = 0
    total_works = 0
    total_work_summaries = 0
    min_year: int | None = None
    max_year: int | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _has_home_coords(node):
            nodes_with_coords += 1
        if node.get("has_story") is True:
            nodes_with_story += 1
        aliases = node.get("aliases") if isinstance(node.get("aliases"), list) else []
        works = node.get("works") if isinstance(node.get("works"), list) else []
        work_summaries = node.get("work_summaries") if isinstance(node.get("work_summaries"), dict) else {}
        total_aliases += len([x for x in aliases if str(x or "").strip()])
        total_works += len([x for x in works if str(x or "").strip()])
        total_work_summaries += len(work_summaries)
        if work_summaries:
            nodes_with_work_summaries += 1
        birth_year = _safe_int(node.get("birth_year"))
        death_year = _safe_int(node.get("death_year"))
        for year in (birth_year, death_year):
            if year is None:
                continue
            min_year = year if min_year is None else min(min_year, year)
            max_year = year if max_year is None else max(max_year, year)
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "kg_edges": len(kg_edges),
        "nodes_with_coords": nodes_with_coords,
        "nodes_with_story": nodes_with_story,
        "nodes_with_work_summaries": nodes_with_work_summaries,
        "total_aliases": total_aliases,
        "total_works": total_works,
        "total_work_summaries": total_work_summaries,
        "year_range": {"min_year": min_year, "max_year": max_year},
    }


def _sample_profile_pages(limit: int = 3) -> list[dict]:
    rows: list[dict] = []
    if not STORY_MAP_DIR.exists():
        return rows
    for path in sorted(STORY_MAP_DIR.glob("*.html")):
        if not _is_export_profile_html(path):
            continue
        stem = path.stem.strip()
        meta = _file_meta(path)
        rows.append(
            {
                "person": stem,
                "path": meta.get("path"),
                "size": meta.get("size", 0),
                "gzip_size": _gzip_size_bytes(path),
            }
        )
    rows.sort(key=lambda item: int(item.get("size") or 0), reverse=True)
    return rows[:limit]


def _baseline_file_metrics(path: Path) -> dict:
    meta = _file_meta(path)
    return {
        **meta,
        "gzip_size": _gzip_size_bytes(path),
    }


def _build_performance_baseline() -> dict:
    home_metrics = _home_payload_metrics(HOME_DATA)
    profile_pages = _sample_profile_pages(limit=3)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "budgets": {
            "homepage_index_html_max_bytes": 250_000,
            "homepage_data_max_bytes": 1_500_000,
            "homepage_detail_data_max_bytes": 2_000_000,
            "profile_html_max_bytes": 900_000,
        },
        "files": {
            "index_html": _baseline_file_metrics(STORY_MAP_DIR / "index.html"),
            "stellar_home_data": _baseline_file_metrics(HOME_DATA),
            "stellar_home_data_detail": _baseline_file_metrics(HOME_DETAIL_DATA),
            "people_summary_index": _baseline_file_metrics(_data_corpus_input_path("people_summary_index.json")),
            "work_summary_index": _baseline_file_metrics(_data_corpus_input_path("work_summary_index.json")),
            "people_birth_coords_wgs84": _baseline_file_metrics(_data_corpus_input_path("people_birth_coords_wgs84.json")),
        },
        "homepage_payload": home_metrics,
        "profile_pages": profile_pages,
        "acceptance": {
            "homepage_index_html": "关注 index.html 原始/gzip 体积，后续缓存与模板优化以此对比。",
            "homepage_data": "关注首页 core/detail 数据包原始/gzip 体积，以及 nodes/edges/kg_edges 数量变化。",
            "profile_pages": "关注典型人物页体积，地图延迟加载后应优先下降大页体积或首屏阻塞成本。",
        },
    }


def _print_performance_summary(baseline: dict) -> None:
    files = baseline.get("files") if isinstance(baseline.get("files"), dict) else {}
    home = baseline.get("homepage_payload") if isinstance(baseline.get("homepage_payload"), dict) else {}
    index_size = ((files.get("index_html") or {}) if isinstance(files.get("index_html"), dict) else {}).get("size")
    home_size = ((files.get("stellar_home_data") or {}) if isinstance(files.get("stellar_home_data"), dict) else {}).get("size")
    home_detail_size = ((files.get("stellar_home_data_detail") or {}) if isinstance(files.get("stellar_home_data_detail"), dict) else {}).get("size")
    print(
        "[perf] "
        f"index.html={index_size or 0}B "
        f"stellar_home_data.json={home_size or 0}B "
        f"stellar_home_data_detail.json={home_detail_size or 0}B "
        f"nodes={home.get('nodes', 0)} "
        f"edges={home.get('edges', 0)} "
        f"kg_edges={home.get('kg_edges', 0)} "
        f"coords={home.get('nodes_with_coords', 0)}/{home.get('nodes', 0)}"
    )


def _load_people_index(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        obj = _read_json(path)
    except Exception:
        return {}
    items = obj.get(key, []) if isinstance(obj, dict) else []
    out: dict[str, dict] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("person", "")).strip()
        if not name:
            continue
        out[name] = item
    return out


def _load_coords_index(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    try:
        obj = _read_json(path)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, list[float]] = {}
    for k, v in obj.items():
        name = str(k or "").strip()
        if not name:
            continue
        if isinstance(v, list) and len(v) >= 2:
            out[name] = v
    return out


def _has_home_coords(node: dict) -> bool:
    try:
        lat = node.get("birth_lat_wgs84")
        lng = node.get("birth_lng_wgs84")
        return isinstance(lat, (int, float)) and isinstance(lng, (int, float))
    except Exception:
        return False


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


def _issue(code: str, items: list[str], level: str, message: str, limit: int = 20) -> dict | None:
    if not items:
        return None
    return {
        "code": code,
        "level": level,
        "message": message,
        "count": len(items),
        "samples": items[:limit],
    }


def _build_manifest() -> dict:
    story_people = _story_people()
    html_people = _canonical_html_people()
    master = _load_people_index(_data_corpus_input_path("people_master.json"), "people")
    pep = _load_people_index(_data_corpus_input_path("people_master_pep.json"), "people")
    home = _load_people_index(HOME_DATA, "nodes")
    coords = _load_coords_index(_data_corpus_input_path("people_birth_coords_wgs84.json"))
    people_union = sorted(set(story_people) | set(html_people) | set(master.keys()) | set(home.keys()) | set(coords.keys()))

    people_rows = []
    for name in people_union:
        md_path = STORY_DIR / f"{name}.md"
        html_path = STORY_MAP_DIR / f"{name}.html"
        master_item = master.get(name) or {}
        home_item = home.get(name) or {}
        people_rows.append(
            {
                "person": name,
                "md_exists": md_path.exists(),
                "html_exists": html_path.exists(),
                "in_master": name in master,
                "in_pep": name in pep,
                "in_home": name in home,
                "in_coords": name in coords,
                "master_has_story": master_item.get("has_story"),
                "master_story_md": master_item.get("story_md"),
                "home_has_story": home_item.get("has_story"),
                "home_file": home_item.get("file"),
                "home_has_coords": _has_home_coords(home_item) if home_item else False,
                "md": _file_meta(md_path),
                "html": _file_meta(html_path),
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "story_md": len(story_people),
            "story_html": len(html_people),
            "people_master": len(master),
            "people_master_pep": len(pep),
            "home_nodes": len(home),
            "birth_coords": len(coords),
        },
        "files": {
            "people_master": _file_meta(_data_corpus_input_path("people_master.json")),
            "people_master_pep": _file_meta(_data_corpus_input_path("people_master_pep.json")),
            "people_birth_coords_wgs84": _file_meta(_data_corpus_input_path("people_birth_coords_wgs84.json")),
            "people_summary_index": _file_meta(_data_corpus_input_path("people_summary_index.json")),
            "stellar_home_data": _file_meta(HOME_DATA),
            "index_html": _file_meta(STORY_MAP_DIR / "index.html"),
            "map_html_renderer": _file_meta(REPO_ROOT / "storymap" / "script" / "profile" / "renderer.py"),
            "build_stellar_homepage": _file_meta(REPO_ROOT / "tools" / "build" / "build_stellar_homepage.py"),
            "generate_pure_story_map": _file_meta(REPO_ROOT / "cli" / "generate_pure_story_map.py"),
            "markdown_smoke_report": _file_meta(MARKDOWN_SMOKE_JSON),
            "low_coverage_story_report_json": _file_meta(LOW_COVERAGE_JSON),
            "low_coverage_story_report_md": _file_meta(LOW_COVERAGE_MD),
            "performance_baseline": _file_meta(PERF_BASELINE_JSON),
        },
        "people": people_rows,
    }


def _build_validation_report() -> dict:
    story_people = set(_story_people())
    html_people = set(_canonical_html_people())
    master = _load_people_index(_data_corpus_input_path("people_master.json"), "people")
    pep = _load_people_index(_data_corpus_input_path("people_master_pep.json"), "people")
    home = _load_people_index(HOME_DATA, "nodes")
    coords = _load_coords_index(_data_corpus_input_path("people_birth_coords_wgs84.json"))

    master_people = set(master.keys())
    pep_people = set(pep.keys())
    home_people = set(home.keys())
    coords_people = set(coords.keys())

    errors: list[dict] = []
    warnings: list[dict] = []

    def push_issue(bucket: list[dict], entry: dict | None) -> None:
        if entry:
            bucket.append(entry)

    push_issue(
        errors,
        _issue("story_missing_in_master", sorted(story_people - master_people), "error", "存在 Markdown 但未进入 people_master.json"),
    )
    push_issue(
        errors,
        _issue("story_missing_in_home", sorted(story_people - home_people), "error", "存在 Markdown 但未进入 stellar_home_data.json"),
    )
    push_issue(
        errors,
        _issue("story_missing_html", sorted(story_people - html_people), "error", "存在 Markdown 但缺少对应人物 HTML"),
    )
    push_issue(
        warnings,
        _issue("html_without_story", sorted(html_people - story_people), "warning", "存在人物 HTML，但没有对应 Markdown 源文件"),
    )
    push_issue(
        warnings,
        _issue("master_has_story_true_without_md", sorted([p for p, item in master.items() if bool(item.get("has_story")) and p not in story_people]), "warning", "people_master.json 中 has_story=true，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        _issue("home_without_story", sorted(home_people - story_people), "warning", "stellar_home_data.json 中存在节点，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        _issue("story_missing_coords", sorted(story_people - coords_people), "warning", "存在 Markdown 但出生地坐标缓存中没有对应人物"),
    )
    push_issue(
        warnings,
        _issue("pep_missing_in_master", sorted(pep_people - master_people), "warning", "people_master_pep.json 中的人物未出现在 people_master.json"),
    )

    master_has_story_false = []
    master_story_md_mismatch = []
    for p in sorted(story_people & master_people):
        item = master[p]
        if not bool(item.get("has_story")):
            master_has_story_false.append(p)
        expected_story_md = f"storymap/examples/story/{p}.md"
        if str(item.get("story_md") or "").strip() != expected_story_md:
            master_story_md_mismatch.append(p)
    push_issue(errors, _issue("master_has_story_false", master_has_story_false, "error", "people_master.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, _issue("master_story_md_mismatch", master_story_md_mismatch, "error", "people_master.json 中 story_md 路径与 Markdown 不一致"))

    home_has_story_false = []
    home_file_mismatch = []
    home_missing_coords = []
    stale_profile_html = []
    expected_template_signature = profile_template_signature()
    for p in sorted(story_people & home_people):
        item = home[p]
        if item.get("has_story") is not True:
            home_has_story_false.append(p)
        expected_file = f"{p}.html"
        if str(item.get("file") or "").strip() != expected_file:
            home_file_mismatch.append(p)
        if not _has_home_coords(item):
            home_missing_coords.append(p)
    push_issue(errors, _issue("home_has_story_false", home_has_story_false, "error", "stellar_home_data.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, _issue("home_file_mismatch", home_file_mismatch, "error", "stellar_home_data.json 中 file 字段与人物 HTML 文件名不一致"))
    push_issue(warnings, _issue("home_missing_coords", home_missing_coords, "warning", "stellar_home_data.json 中存在节点，但缺少出生地坐标"))
    for p in sorted(story_people & html_people):
        html_path = STORY_MAP_DIR / f"{p}.html"
        if _extract_html_template_signature(html_path) != expected_template_signature:
            stale_profile_html.append(p)
    push_issue(errors, _issue("story_html_template_stale", stale_profile_html, "error", "人物 HTML 未按当前共享模板重新生成"))

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": len(errors) == 0,
        "summary": {
            "story_md": len(story_people),
            "story_html": len(html_people),
            "people_master": len(master_people),
            "people_master_pep": len(pep_people),
            "home_nodes": len(home_people),
            "birth_coords": len(coords_people),
            "error_count": sum(int(x.get("count", 0)) for x in errors),
            "warning_count": sum(int(x.get("count", 0)) for x in warnings),
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def _patch_master_with_has_story(master_fp: Path) -> dict:
    """按可发布 Markdown 口径强制刷新 has_story 与 story_md 字段。"""
    obj = json.loads(master_fp.read_text(encoding="utf-8"))
    people = obj.get("people", [])
    if not isinstance(people, list):
        return {"updated": 0, "total": 0}
    publishable_people = set(_story_people())
    updated = 0
    for p in people:
        name = str(p.get("person", "")).strip()
        if not name:
            continue
        has_story = name in publishable_people
        was = bool(p.get("has_story"))
        if was != has_story:
            updated += 1
        p["has_story"] = has_story
        p["story_md"] = f"storymap/examples/story/{name}.md" if has_story else ""
    obj["count"] = len(people)
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    master_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(people)}


def _patch_home_with_has_story(home_fp: Path) -> dict:
    """给首页节点补 has_story 字段，源于可发布 Markdown 口径。"""
    obj = json.loads(home_fp.read_text(encoding="utf-8"))
    nodes = obj.get("nodes", [])
    if not isinstance(nodes, list):
        return {"updated": 0, "total": 0}
    publishable_people = set(_story_people())
    updated = 0
    for n in nodes:
        name = str(n.get("person", "")).strip()
        if not name:
            continue
        has_story = name in publishable_people
        was = n.get("has_story")
        if was != has_story:
            updated += 1
        n["has_story"] = has_story
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    home_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(nodes)}


def main() -> int:
    ap = argparse.ArgumentParser(description="数据单源构建入口（幂等）")
    ap.add_argument("--skip-master", action="store_true")
    ap.add_argument("--skip-pep", action="store_true")
    ap.add_argument("--skip-html", action="store_true")
    ap.add_argument("--skip-home", action="store_true")
    ap.add_argument("--validate", action="store_true", help="兼容保留；当前默认已在校验错误时返回非 0")
    ap.add_argument("--validate-only", action="store_true", help="只生成 manifest 与校验报告，不执行重建")
    ap.add_argument("--allow-validation-errors", action="store_true", help="即使校验报告存在错误也返回 0")
    ap.add_argument(
        "--markdown-smoke-check",
        choices=["off", "changed", "all"],
        default="changed",
        help="构建前执行 Markdown 冒烟校验：changed=仅校验 git 变更文件，all=全量校验，off=关闭",
    )
    ap.add_argument("--refresh-geocode", action="store_true",
                    help="兼容保留；默认批量渲染已走 pure 模式，会在缺失坐标时补齐地理编码")
    ap.add_argument("--fill-missing-md", action="store_true",
                    help="对 master 里没有 .md 的人物尝试 LLM 生成（需要 API key）")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    t0 = time.time()
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"[init] .md 源文件: {len(story_files)} 个, 已渲染 .html: {len(html_files)} 个")

    _print_section("0/6 markdown smoke check")
    rc = _run_markdown_smoke_check(args.markdown_smoke_check)
    if rc != 0:
        print(f"  ✗ Markdown 冒烟校验未通过，退出码 {rc}", flush=True)
        return rc

    if args.validate_only:
        manifest = _build_manifest()
        report = _build_validation_report()
        baseline = _build_performance_baseline()
        _write_json(MANIFEST_JSON, manifest)
        _write_json(VALIDATION_JSON, report)
        _write_json(PERF_BASELINE_JSON, baseline)
        print(f"[validate-only] manifest: {MANIFEST_JSON}")
        print(f"[validate-only] report:   {VALIDATION_JSON}")
        print(f"[validate-only] perf:     {PERF_BASELINE_JSON}")
        print(f"[validate-only] ok={report['ok']} errors={report['summary']['error_count']} warnings={report['summary']['warning_count']}")
        _print_performance_summary(baseline)
        return 0 if report["ok"] else 2

    # ── 1. people_master.json ───────────────────────────────────
    if not args.skip_master:
        _print_section("1/6 rebuild data/corpus/people_master.json")
        rc = _run([
            sys.executable, "tools/build_people_master.py",
            "--scope", "all",
            "--out", str(_data_corpus_output_path("people_master.json")),
            "--concurrency", str(args.concurrency),
        ])
        if rc != 0:
            print(f"  ✗ build_people_master.py 退出码 {rc}", flush=True)
            return rc
        # 关键：用可发布 Markdown 口径强制覆盖 has_story
        master_fp = _data_corpus_input_path("people_master.json")
        stat = _patch_master_with_has_story(master_fp)
        print(f"  ✓ has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)

    # ── 2. people_master_pep.json ────────────────────────────────
    if not args.skip_pep:
        _print_section("2/6 rebuild data/corpus/people_master_pep.json")
        rc = _run([
            sys.executable, "tools/build_people_master.py",
            "--scope", "pep",
            "--out", str(_data_corpus_output_path("people_master_pep.json")),
            "--concurrency", str(args.concurrency),
        ])
        if rc != 0:
            print(f"  ✗ build_people_master.py (pep) 退出码 {rc}", flush=True)
            return rc
        # PEP 索引是教材口径的人物，用可发布 Markdown 口径刷 has_story
        pep_fp = _data_corpus_input_path("people_master_pep.json")
        stat = _patch_master_with_has_story(pep_fp)
        print(f"  ✓ pep has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)

    # ── 3. 增量重渲染人物页 ───────────────────────────────────────
    if not args.skip_html:
        _print_section("3/6 render changed artifacts/story_map/*.html")
        rc = _run([
            sys.executable, "cli/generate_pure_story_map.py",
            "--render-changed",
            "--changed-mode", "nogeocode",
            "--changed-limit", "0",
        ])
        if rc != 0:
            print(f"  ✗ generate_pure_story_map.py --render-changed 退出码 {rc}", flush=True)
            return rc
        cleanup = _cleanup_non_publishable_artifacts()
        print(f"  ✓ 已清理不可发布/临时产物: {cleanup['removed']} 个", flush=True)
        if cleanup["samples"]:
            print(f"    样例: {', '.join(cleanup['samples'])}", flush=True)

    # ── 4. 出生地经纬度 ─────────────────────────────────────────
    _print_section("4/6 sync data/corpus/people_birth_coords_wgs84.json")
    if args.refresh_geocode:
        print("  → 重新跑 build_stellar_homepage.py 以触发 geocode（如果有缺失）", flush=True)
    # 后续 build_stellar_homepage 也会写 coords 文件，这里仅做提示

    # ── 5. people_summary_index.json ────────────────────────────
    if not args.skip_home:
        _print_section("5/7 rebuild data/corpus/people_summary_index.json")
        rc = _run([sys.executable, "tools/build_people_summary_index.py"])
        if rc != 0:
            print(f"  ✗ build_people_summary_index.py 退出码 {rc}", flush=True)
            return rc
        _print_section("6/7 rebuild data/corpus/work_summary_index.json")
        rc = _run([sys.executable, "tools/build_work_summary_index.py"])
        if rc != 0:
            print(f"  ✗ build_work_summary_index.py 退出码 {rc}", flush=True)
            return rc

    # ── 7. stellar_home_data.json + index.html ──────────────────
    if not args.skip_home:
        _print_section("7/7 rebuild stellar_home_data.json + index.html")
        rc = _run([
            sys.executable, "tools/build_stellar_homepage.py",
            "--story-map-dir", str(STORY_MAP_DIR),
            "--story-md-dir", str(STORY_DIR),
        ])
        if rc != 0:
            print(f"  ✗ build_stellar_homepage.py 退出码 {rc}", flush=True)
            return rc
        # 强制 home 节点与可发布 Markdown 口径一致
        if HOME_DATA.exists():
            stat = _patch_home_with_has_story(HOME_DATA)
            print(f"  ✓ home has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 节点", flush=True)

    # ── 收尾统计 ────────────────────────────────────────────────
    elapsed = time.time() - t0
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"\n[done] .md={len(story_files)} .html={len(html_files)}  耗时 {elapsed:.1f}s")
    if not story_files and not html_files:
        print("  ⚠ 警告：未找到 .md 源文件。请确认 storymap/examples/story/ 目录非空。")

    manifest = _build_manifest()
    report = _build_validation_report()
    baseline = _build_performance_baseline()
    _write_json(MANIFEST_JSON, manifest)
    _write_json(VALIDATION_JSON, report)
    _write_json(PERF_BASELINE_JSON, baseline)
    _print_section("coverage report")
    rc = _run(
        [
            sys.executable,
            "tools/report_low_coverage_places.py",
            "--story-dir",
            str(STORY_DIR),
            "--out-json",
            str(LOW_COVERAGE_JSON),
            "--out-md",
            str(LOW_COVERAGE_MD),
        ]
    )
    if rc != 0:
        print(f"  ✗ report_low_coverage_places.py 退出码 {rc}", flush=True)
        return rc
    manifest = _build_manifest()
    _write_json(MANIFEST_JSON, manifest)
    print(f"[manifest] {MANIFEST_JSON}")
    print(f"[validate] {VALIDATION_JSON}  ok={report['ok']} errors={report['summary']['error_count']} warnings={report['summary']['warning_count']}")
    print(f"[perf] {PERF_BASELINE_JSON}")
    _print_performance_summary(baseline)
    if (not report["ok"]) and (not args.allow_validation_errors):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

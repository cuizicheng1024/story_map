from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_meta(path: Path, repo_root: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    try:
        rel_path = str(path.relative_to(repo_root))
    except ValueError:
        rel_path = str(path)
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime": round(stat.st_mtime, 3),
        "sha1": sha1_file(path)[:12],
        "path": rel_path,
    }


def gzip_size_bytes(path: Path) -> int | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return len(gzip.compress(path.read_bytes(), compresslevel=6))
    except Exception:
        return None


def safe_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return None


def has_home_coords(node: dict) -> bool:
    try:
        lat = node.get("birth_lat_wgs84")
        lng = node.get("birth_lng_wgs84")
        return isinstance(lat, (int, float)) and isinstance(lng, (int, float))
    except Exception:
        return False


def home_payload_metrics(path: Path) -> dict:
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
        payload = read_json(path)
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
        if has_home_coords(node):
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
        birth_year = safe_int(node.get("birth_year"))
        death_year = safe_int(node.get("death_year"))
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


def sample_profile_pages(story_map_dir: Path, repo_root: Path, is_export_profile_html: Callable[[Path], bool], limit: int = 3) -> list[dict]:
    rows: list[dict] = []
    if not story_map_dir.exists():
        return rows
    for path in sorted(story_map_dir.glob("*.html")):
        if not is_export_profile_html(path):
            continue
        stem = path.stem.strip()
        meta = file_meta(path, repo_root)
        rows.append(
            {
                "person": stem,
                "path": meta.get("path"),
                "size": meta.get("size", 0),
                "gzip_size": gzip_size_bytes(path),
            }
        )
    rows.sort(key=lambda item: int(item.get("size") or 0), reverse=True)
    return rows[:limit]


def baseline_file_metrics(path: Path, repo_root: Path) -> dict:
    meta = file_meta(path, repo_root)
    return {
        **meta,
        "gzip_size": gzip_size_bytes(path),
    }


def build_performance_baseline(
    *,
    repo_root: Path,
    story_map_dir: Path,
    home_data: Path,
    home_detail_data: Path,
    data_corpus_input_path: Callable[[str], Path],
    is_export_profile_html: Callable[[Path], bool],
) -> dict:
    home_metrics = home_payload_metrics(home_data)
    profile_pages = sample_profile_pages(story_map_dir, repo_root, is_export_profile_html, limit=3)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "budgets": {
            "homepage_index_html_max_bytes": 250_000,
            "homepage_data_max_bytes": 1_500_000,
            "homepage_detail_data_max_bytes": 2_000_000,
            "profile_html_max_bytes": 900_000,
        },
        "files": {
            "index_html": baseline_file_metrics(story_map_dir / "index.html", repo_root),
            "stellar_home_data": baseline_file_metrics(home_data, repo_root),
            "stellar_home_data_detail": baseline_file_metrics(home_detail_data, repo_root),
            "people_summary_index": baseline_file_metrics(data_corpus_input_path("people_summary_index.json"), repo_root),
            "work_summary_index": baseline_file_metrics(data_corpus_input_path("work_summary_index.json"), repo_root),
            "people_birth_coords_wgs84": baseline_file_metrics(data_corpus_input_path("people_birth_coords_wgs84.json"), repo_root),
        },
        "homepage_payload": home_metrics,
        "profile_pages": profile_pages,
        "acceptance": {
            "homepage_index_html": "关注 index.html 原始/gzip 体积，后续缓存与模板优化以此对比。",
            "homepage_data": "关注首页 core/detail 数据包原始/gzip 体积，以及 nodes/edges/kg_edges 数量变化。",
            "profile_pages": "关注典型人物页体积，地图延迟加载后应优先下降大页体积或首屏阻塞成本。",
        },
    }


def print_performance_summary(baseline: dict) -> None:
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

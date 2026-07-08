from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .performance import file_meta, has_home_coords, read_json


def load_people_index(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        obj = read_json(path)
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


def load_coords_index(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    try:
        obj = read_json(path)
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


def build_manifest(
    *,
    repo_root: Path,
    story_dir: Path,
    story_map_dir: Path,
    home_data: Path,
    markdown_smoke_json: Path,
    low_coverage_json: Path,
    low_coverage_md: Path,
    perf_baseline_json: Path,
    story_people: Callable[[], list[str]],
    canonical_html_people: Callable[[], list[str]],
    data_corpus_input_path: Callable[[str], Path],
) -> dict:
    story_people_list = story_people()
    html_people = canonical_html_people()
    master = load_people_index(data_corpus_input_path("people_master.json"), "people")
    pep = load_people_index(data_corpus_input_path("people_master_pep.json"), "people")
    home = load_people_index(home_data, "nodes")
    coords = load_coords_index(data_corpus_input_path("people_birth_coords_wgs84.json"))
    people_union = sorted(set(story_people_list) | set(html_people) | set(master.keys()) | set(home.keys()) | set(coords.keys()))

    people_rows = []
    for name in people_union:
        md_path = story_dir / f"{name}.md"
        html_path = story_map_dir / f"{name}.html"
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
                "home_has_coords": has_home_coords(home_item) if home_item else False,
                "md": file_meta(md_path, repo_root),
                "html": file_meta(html_path, repo_root),
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "story_md": len(story_people_list),
            "story_html": len(html_people),
            "people_master": len(master),
            "people_master_pep": len(pep),
            "home_nodes": len(home),
            "birth_coords": len(coords),
        },
        "files": {
            "people_master": file_meta(data_corpus_input_path("people_master.json"), repo_root),
            "people_master_pep": file_meta(data_corpus_input_path("people_master_pep.json"), repo_root),
            "people_birth_coords_wgs84": file_meta(data_corpus_input_path("people_birth_coords_wgs84.json"), repo_root),
            "people_summary_index": file_meta(data_corpus_input_path("people_summary_index.json"), repo_root),
            "stellar_home_data": file_meta(home_data, repo_root),
            "index_html": file_meta(story_map_dir / "index.html", repo_root),
            "map_html_renderer": file_meta(repo_root / "storymap" / "script" / "profile" / "renderer.py", repo_root),
            "build_stellar_homepage": file_meta(repo_root / "tools" / "build" / "homepage" / "main.py", repo_root),
            "generate_pure_story_map": file_meta(repo_root / "cli" / "generate_pure_story_map.py", repo_root),
            "markdown_smoke_report": file_meta(markdown_smoke_json, repo_root),
            "low_coverage_story_report_json": file_meta(low_coverage_json, repo_root),
            "low_coverage_story_report_md": file_meta(low_coverage_md, repo_root),
            "performance_baseline": file_meta(perf_baseline_json, repo_root),
        },
        "people": people_rows,
    }

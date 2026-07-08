from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from .manifest import load_coords_index, load_people_index
from .performance import has_home_coords


def extract_html_template_signature(path: Path) -> str:
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


def issue(code: str, items: list[str], level: str, message: str, limit: int = 20) -> dict | None:
    if not items:
        return None
    return {
        "code": code,
        "level": level,
        "message": message,
        "count": len(items),
        "samples": items[:limit],
    }


def build_validation_report(
    *,
    story_dir: Path,
    story_map_dir: Path,
    home_data: Path,
    story_people: Callable[[], list[str]],
    canonical_html_people: Callable[[], list[str]],
    data_corpus_input_path: Callable[[str], Path],
    profile_template_signature: Callable[[], str],
) -> dict:
    story_people_set = set(story_people())
    html_people = set(canonical_html_people())
    master = load_people_index(data_corpus_input_path("people_master.json"), "people")
    pep = load_people_index(data_corpus_input_path("people_master_pep.json"), "people")
    home = load_people_index(home_data, "nodes")
    coords = load_coords_index(data_corpus_input_path("people_birth_coords_wgs84.json"))

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
        issue("story_missing_in_master", sorted(story_people_set - master_people), "error", "存在 Markdown 但未进入 people_master.json"),
    )
    push_issue(
        errors,
        issue("story_missing_in_home", sorted(story_people_set - home_people), "error", "存在 Markdown 但未进入 stellar_home_data.json"),
    )
    push_issue(
        errors,
        issue("story_missing_html", sorted(story_people_set - html_people), "error", "存在 Markdown 但缺少对应人物 HTML"),
    )
    push_issue(
        warnings,
        issue("html_without_story", sorted(html_people - story_people_set), "warning", "存在人物 HTML，但没有对应 Markdown 源文件"),
    )
    push_issue(
        warnings,
        issue("master_has_story_true_without_md", sorted([p for p, item in master.items() if bool(item.get("has_story")) and p not in story_people_set]), "warning", "people_master.json 中 has_story=true，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        issue("home_without_story", sorted(home_people - story_people_set), "warning", "stellar_home_data.json 中存在节点，但磁盘上无对应 Markdown"),
    )
    push_issue(
        warnings,
        issue("story_missing_coords", sorted(story_people_set - coords_people), "warning", "存在 Markdown 但出生地坐标缓存中没有对应人物"),
    )
    push_issue(
        warnings,
        issue("pep_missing_in_master", sorted(pep_people - master_people), "warning", "people_master_pep.json 中的人物未出现在 people_master.json"),
    )

    master_has_story_false = []
    master_story_md_mismatch = []
    for p in sorted(story_people_set & master_people):
        item = master[p]
        if not bool(item.get("has_story")):
            master_has_story_false.append(p)
        expected_story_md = f"storymap/examples/story/{p}.md"
        if str(item.get("story_md") or "").strip() != expected_story_md:
            master_story_md_mismatch.append(p)
    push_issue(errors, issue("master_has_story_false", master_has_story_false, "error", "people_master.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, issue("master_story_md_mismatch", master_story_md_mismatch, "error", "people_master.json 中 story_md 路径与 Markdown 不一致"))

    home_has_story_false = []
    home_file_mismatch = []
    home_missing_coords = []
    stale_profile_html = []
    expected_template_signature = profile_template_signature()
    for p in sorted(story_people_set & home_people):
        item = home[p]
        if item.get("has_story") is not True:
            home_has_story_false.append(p)
        expected_file = f"{p}.html"
        if str(item.get("file") or "").strip() != expected_file:
            home_file_mismatch.append(p)
        if not has_home_coords(item):
            home_missing_coords.append(p)
    push_issue(errors, issue("home_has_story_false", home_has_story_false, "error", "stellar_home_data.json 中 has_story 与 Markdown 不一致"))
    push_issue(errors, issue("home_file_mismatch", home_file_mismatch, "error", "stellar_home_data.json 中 file 字段与人物 HTML 文件名不一致"))
    push_issue(warnings, issue("home_missing_coords", home_missing_coords, "warning", "stellar_home_data.json 中存在节点，但缺少出生地坐标"))
    for p in sorted(story_people_set & html_people):
        html_path = story_map_dir / f"{p}.html"
        if extract_html_template_signature(html_path) != expected_template_signature:
            stale_profile_html.append(p)
    push_issue(errors, issue("story_html_template_stale", stale_profile_html, "error", "人物 HTML 未按当前共享模板重新生成"))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": len(errors) == 0,
        "summary": {
            "story_md": len(story_people_set),
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

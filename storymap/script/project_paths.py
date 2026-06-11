from __future__ import annotations

import json
import os
import re
from pathlib import Path

BAD_PERSON_NAMES = frozenset(
    {
        "人物",
        "母亲",
        "刘某",
        "人物 生平传记与足迹",
    }
)

_NON_AUTHENTIC_STORY_MARKERS = (
    "文学虚构人物",
    "虚构示例",
    "格式示例",
    "此人物为格式示例或虚构角色",
    "并非真实历史人物",
    "并非真实存在的历史人物",
    "无任何可靠史料支持",
    "不将其视为历史人物",
    "疑似虚构人物",
    "身份存疑，可能非真实历史人物",
    "人物真实性存疑",
    "可能为虚构、误传或同名混淆",
    "更可能为现代人物、虚构角色或同名误配",
)
_NON_AUTHENTIC_TITLE_RE = re.compile(
    r"^#\s*.+(?:文学虚构人物|神话人物|虚构示例|示例人物|《[^》]+》人物)[】）)\]]?\s*$",
    re.MULTILINE,
)


def project_root_path() -> Path:
    return Path(__file__).resolve().parents[2]


def story_md_dir_path() -> Path:
    return project_root_path() / "storymap" / "examples" / "story"


def story_artifacts_dir_path() -> Path:
    configured = (os.getenv("MAP_STORY_OUTPUT_DIR") or "").strip()
    if configured:
        output_dir = Path(configured)
        if not output_dir.is_absolute():
            output_dir = project_root_path() / output_dir
        return output_dir.resolve()
    return project_root_path() / "artifacts" / "story_map"


def is_valid_person_name(name: object) -> bool:
    cleaned = str(name or "").strip()
    return bool(cleaned and cleaned not in BAD_PERSON_NAMES)


def classify_story_markdown_authenticity(path: Path) -> tuple[bool, str]:
    name = str(Path(path).stem or "").strip()
    if not is_valid_person_name(name):
        return False, "invalid_name"
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return True, ""
    head = text[:4000]
    if _NON_AUTHENTIC_TITLE_RE.search(head):
        return False, "non_authentic_title"
    if "神话人物" in head:
        return False, "mythological_character"
    for marker in _NON_AUTHENTIC_STORY_MARKERS:
        if marker in head:
            return False, "non_authentic_marker"
    return True, ""


def is_publishable_person_markdown(path: Path) -> bool:
    accepted, _ = classify_story_markdown_authenticity(path)
    return accepted


def _collect_people_from_json(path: Path) -> set[str]:
    names: set[str] = set()
    if not path.exists() or not path.is_file():
        return names
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return names

    def _add_name(value: object) -> None:
        cleaned = str(value or "").strip()
        if is_valid_person_name(cleaned):
            names.add(cleaned)

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _add_name(item.get("person") or item.get("id") or item.get("label") or item.get("name"))
            else:
                _add_name(item)
        return names
    if isinstance(payload, dict):
        people = payload.get("people")
        if isinstance(people, list):
            for item in people:
                if isinstance(item, dict):
                    _add_name(item.get("person") or item.get("id") or item.get("label") or item.get("name"))
                else:
                    _add_name(item)
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            for item in nodes:
                if isinstance(item, dict):
                    _add_name(item.get("person") or item.get("id") or item.get("label") or item.get("name"))
                else:
                    _add_name(item)
        for value in payload.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _add_name(item.get("person") or item.get("id") or item.get("label") or item.get("name"))
                    else:
                        _add_name(item)
    return names


def _collect_rejected_story_people(story_dir: Path) -> set[str]:
    rejected: set[str] = set()
    if not story_dir.exists() or not story_dir.is_dir():
        return rejected
    for path in story_dir.glob("*.md"):
        name = str(path.stem or "").strip()
        if not is_valid_person_name(name):
            continue
        accepted, _ = classify_story_markdown_authenticity(path)
        if not accepted:
            rejected.add(name)
    return rejected


def known_authentic_person_names(project_root: Path | None = None, story_dir: Path | None = None) -> set[str]:
    base_story_dir = Path(story_dir or (Path(project_root or project_root_path()) / "storymap" / "examples" / "story"))
    root = Path(project_root or project_root_path())
    if project_root is None:
        for parent in base_story_dir.resolve().parents:
            if (parent / "data").exists() and (parent / "storymap").exists():
                root = parent
                break
    names = set()
    data_dir = root / "data"
    for filename in (
        "pep_people_merged.json",
        "pep_junior_all_people.json",
        "pep_junior_all_people_by_book.json",
        "pep_history_figures_sample.json",
    ):
        names.update(_collect_people_from_json(data_dir / filename))
    publishable_names = set(story_person_names(base_story_dir))
    names.update(publishable_names)
    names.difference_update(_collect_rejected_story_people(base_story_dir))
    try:
        from .person_registry import person_redirects
    except Exception:
        try:
            from person_registry import person_redirects  # type: ignore
        except Exception:
            person_redirects = None  # type: ignore
    if callable(person_redirects) and publishable_names:
        redirects = dict(person_redirects(sorted(publishable_names)) or {})
        names.update(str(alias or "").strip() for alias in redirects.keys() if is_valid_person_name(alias))
        names.update(str(canonical or "").strip() for canonical in redirects.values() if is_valid_person_name(canonical))
    return names


def classify_story_person_authenticity(
    name: object,
    story_dir: Path | None = None,
    *,
    allow_unknown: bool = True,
) -> tuple[bool, str]:
    cleaned = str(name or "").strip()
    if not is_valid_person_name(cleaned):
        return False, "invalid_name"
    candidate = Path(story_dir or story_md_dir_path()) / f"{cleaned}.md"
    if candidate.exists() and candidate.is_file():
        return classify_story_markdown_authenticity(candidate)
    rejected_names = _collect_rejected_story_people(candidate.parent)
    known_names = known_authentic_person_names(story_dir=candidate.parent)
    canonical = cleaned
    if cleaned in known_names:
        return True, ""
    try:
        from .person_registry import canonical_person_name
    except Exception:
        try:
            from person_registry import canonical_person_name  # type: ignore
        except Exception:
            canonical_person_name = None  # type: ignore
    if callable(canonical_person_name):
        canonical = str(canonical_person_name(cleaned, known_names) or "").strip()
    if cleaned in rejected_names or canonical in rejected_names:
        return False, "non_authentic_person"
    if canonical and canonical in known_names:
        return True, ""
    if allow_unknown:
        return True, ""
    return False, "unknown_person"


def story_person_names(story_dir: Path | None = None) -> list[str]:
    base_dir = Path(story_dir or story_md_dir_path())
    if not base_dir.exists():
        return []
    names: list[str] = []
    for path in sorted(base_dir.glob("*.md")):
        if path.is_file() and is_publishable_person_markdown(path):
            names.append(path.stem.strip())
    return names


def person_name_from_filename(name: str) -> str:
    stem = Path(name).stem
    if "__pure__" in stem:
        return stem.split("__pure__", 1)[0]
    return stem

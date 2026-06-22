import json
import re
from pathlib import Path
from typing import Dict, List, Any

try:
    from tools.homepage_search import normalize_search_text, pinyin_variants
except Exception:
    from homepage_search import normalize_search_text, pinyin_variants
from storymap.script.core import parsers as parser_utils
from storymap.script.profile import builder as profile_builder
from storymap.script.core.project_paths import data_corpus_output_path, story_person_names


SUMMARY_INDEX_FILENAME = "people_summary_index.json"


def _pick_first_nonempty(lines: List[str]) -> str:
    for ln in lines:
        t = (ln or "").strip()
        if t:
            return t
    return ""


def _strip_outer_quotes(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    quote_pairs = [("“", "”"), ('"', '"'), ("'", "'"), ("‘", "’")]
    for left, right in quote_pairs:
        if cleaned.startswith(left) and cleaned.endswith(right) and len(cleaned) >= len(left) + len(right):
            cleaned = cleaned[len(left) : len(cleaned) - len(right)].strip()
            break
    return cleaned


def _uniq_preserve_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _person_sort_key(name: str) -> tuple[str, str, str]:
    raw = str(name or "").strip()
    normalized = normalize_search_text(raw) or raw.casefold()
    pinyin_list = pinyin_variants(raw)
    primary = str(pinyin_list[0] or "").strip() if pinyin_list else normalized
    return primary, normalized, raw


def _extract_quotes(md: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(r"“([^”]{6,80})”", md):
        quote = _strip_outer_quotes(m.group(0))
        if quote:
            out.append(quote)
        out = _uniq_preserve_order(out)
        if len(out) >= 6:
            break
    return out


def _extract_section(md: str, title: str) -> str:
    lines = md.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == title:
            start = i + 1
            break
    if start is None:
        return ""
    buf: List[str] = []
    for ln in lines[start:]:
        if ln.strip().startswith("## "):
            break
        buf.append(ln.rstrip())
    return "\n".join(buf).strip()


def _clean_review_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
    cleaned = re.sub(r"^(?:人物)?短评\s*[：:]\s*", "", cleaned)
    return cleaned.strip()


def _merge_intro_fields_into_info(info: Dict[str, str], md: str) -> Dict[str, str]:
    merged = dict(info or {})
    if merged.get("姓名"):
        return merged
    fields = profile_builder.extract_intro_fields(md)
    if not any(fields.values()):
        return merged
    if fields.get("朝代"):
        merged.setdefault("时代", str(fields.get("朝代") or "").strip())
    if fields.get("身份"):
        merged.setdefault("主要身份", str(fields.get("身份") or "").strip())
    if fields.get("历史地位"):
        merged.setdefault("历史地位", str(fields.get("历史地位") or "").strip())
    if fields.get("主要事件"):
        merged.setdefault("主要成就", str(fields.get("主要事件") or "").strip())
    return merged


def _clean_review_items(items: List[str], *, limit: int = 3, max_len: int = 90) -> List[str]:
    out: List[str] = []
    for item in items:
        cleaned = _clean_review_text(item)
        cleaned = _strip_outer_quotes(cleaned)
        if not cleaned or cleaned in out:
            continue
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip() + "…"
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _summarize(name: str, md: str) -> Dict[str, Any]:
    parsed_doc = parser_utils.parse_story_document(md)
    normalized_md = parsed_doc.normalized_markdown
    info = _merge_intro_fields_into_info(dict(parsed_doc.basic_info_map), normalized_md)
    name_raw = str(info.get("姓名") or name or "").strip()
    quotes = _extract_quotes(md)
    intro = _extract_section(md, "### 生平概述")
    if not intro:
        intro = _extract_section(md, "## 一、人物档案")
    intro_line = _pick_first_nonempty(re.split(r"[。！？\n]", intro))
    if intro_line and len(intro_line) > 70:
        intro_line = intro_line[:70].rstrip() + "…"

    review_items = _clean_review_items([str(item or "") for item in parsed_doc.historical_reviews])
    review_pick = review_items[0] if review_items else ""
    title = (
        profile_builder.extract_title_from_text(str(info.get("历史地位") or ""))
        or profile_builder.extract_title_from_text(review_pick)
        or profile_builder.extract_title_from_text(name_raw)
    )
    locations = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    work_texts = profile_builder.extract_work_texts(normalized_md)
    short_review = profile_builder.choose_short_review(
        info=info,
        locations=locations,
        work_texts=work_texts,
        historical_reviews=parsed_doc.historical_reviews,
        fallback=title,
    )
    short_review = _strip_outer_quotes(short_review)
    works = profile_builder.extract_works(
        " ".join(
            [
                str(parsed_doc.overview or "").strip(),
                str(info.get("主要成就") or "").strip(),
                str(info.get("历史地位") or "").strip(),
            ]
        )
    )

    best_quote = quotes[0] if quotes else ""
    best_text = _strip_outer_quotes(best_quote or review_pick or intro_line)
    if best_text and len(best_text) > 110:
        best_text = best_text[:110].rstrip() + "…"

    return {
        "spotlight": best_text,
        "quotes": quotes,
        "review": review_pick,
        "reviews": review_items,
        "intro": intro_line,
        "title": title,
        "honor": title,
        "short_review": short_review,
        "status": str(info.get("历史地位") or "").strip(),
        "identities": str(info.get("主要身份") or "").strip(),
        "achievements": str(info.get("主要成就") or "").strip(),
        "works": works,
    }


def main() -> int:
    file_path = Path(__file__).resolve()
    repo_root = file_path.parents[2] if file_path.parent.name == "build" else file_path.parents[1]
    story_dir = repo_root / "storymap" / "examples" / "story"
    out: Dict[str, Any] = {}
    for name in sorted(story_person_names(story_dir), key=_person_sort_key):
        p = story_dir / f"{name}.md"
        if not p.is_file():
            continue
        md = p.read_text(encoding="utf-8", errors="ignore")
        out[name] = _summarize(name, md)

    payload = {"items": out, "meta": {"count": len(out)}}
    path = data_corpus_output_path(SUMMARY_INDEX_FILENAME, project_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

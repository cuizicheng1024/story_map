from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from storymap.script.core.person_registry import canonical_person_name
from storymap.script.core.project_paths import (
    data_corpus_file_path,
    data_corpus_output_path,
    is_publishable_person_markdown,
    is_valid_person_name,
    story_person_names,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
STORY_DIR = REPO_ROOT / "storymap" / "examples" / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)


def _data_input_path(filename: str) -> Path:
    data_dir = Path(DATA_DIR)
    if data_dir != Path(REPO_ROOT) / "data":
        corpus_path = data_dir / "corpus" / filename
        return corpus_path if corpus_path.exists() else (data_dir / filename)
    direct_path = data_dir / filename
    corpus_path = data_dir / "corpus" / filename
    if direct_path.exists():
        return direct_path
    if corpus_path.exists():
        return corpus_path
    return data_corpus_file_path(filename, project_root=REPO_ROOT)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(REPO_ROOT / ".env")
        load_dotenv(REPO_ROOT.parent / ".env")
        load_dotenv(REPO_ROOT.parent.parent / ".env")
    except Exception:
        pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_name(s: object) -> str:
    return str(s or "").strip()


def _uniq(xs: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in xs:
        x = _safe_name(x)
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _extract_year(text: str) -> Optional[int]:
    content = str(text or "")
    bce_match = re.search(r"(?:公元前|前)\s*(\d{1,4})(?!\d)", content)
    if bce_match:
        try:
            return -int(bce_match.group(1))
        except Exception:
            return None
    match = re.search(r"(-?\d{1,4})(?!\d)", content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_years(text: str) -> List[int]:
    content = str(text or "")
    years: List[int] = []
    for match in re.finditer(r"(公元前|前|公元)?\s*(-?\d{1,4})(?!\d)", content):
        prefix = str(match.group(1) or "").strip()
        raw = str(match.group(2) or "").strip()
        if not raw:
            continue
        try:
            year = int(raw)
        except Exception:
            continue
        if prefix in {"公元前", "前"} and year > 0:
            year = -year
        years.append(year)
    return years


def _normalize_year_pair(birth: Optional[int], death: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    if birth is None or death is None:
        return birth, death
    if birth < 0 and death < 0 and birth >= death:
        return min(birth, death), max(birth, death)
    if birth >= 0 and death >= 0 and birth > death:
        return min(birth, death), max(birth, death)
    return birth, death


def _pick_years(md_text: str) -> Tuple[Optional[int], Optional[int]]:
    text = md_text or ""

    def pick_line_value(patterns: Sequence[str]) -> str:
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return str(m.group(1) or "").strip()
        return ""

    def pick_two_years(s: str) -> Tuple[Optional[int], Optional[int]]:
        ys = _extract_years(s)
        if len(ys) < 2:
            return None, None
        return ys[0], ys[1]

    lifespan_text = pick_line_value(
        [
            r"\*\*生卒年\*\*[:：][ \t]*([^\n]*)",
            r"(?:生卒年|生卒)[:：][ \t]*([^\n]*)",
        ]
    )
    if lifespan_text:
        b, d = pick_two_years(lifespan_text)
        if b is not None or d is not None:
            return _normalize_year_pair(b, d)

    birth = None
    death = None
    birth_text = pick_line_value(
        [
            r"\*\*出生\*\*[:：][ \t]*([^\n]*)",
            r"(?:出生)[:：][ \t]*([^\n]*)",
        ]
    )
    if birth_text:
        birth = _extract_year(birth_text)

    death_text = pick_line_value(
        [
            r"\*\*(?:去世|逝世)\*\*[:：][ \t]*([^\n]*)",
            r"(?:去世|逝世)[:：][ \t]*([^\n]*)",
        ]
    )
    if death_text:
        death = _extract_year(death_text)

    return _normalize_year_pair(birth, death)


def _pick_dynasty(md_text: str) -> str:
    for pat in [
        r"\*\*时代\*\*[:：]\s*([^\n]+)",
        r"时代[：:]\s*([^\n]+)",
        r"\*\*朝代\*\*[:：]\s*([^\n]+)",
        r"朝代[：:]\s*([^\n]+)",
    ]:
        m = re.search(pat, md_text or "")
        if m:
            return str(m.group(1) or "").strip()
    return ""


def _pick_birthplace(md_text: str) -> Tuple[str, str, str]:
    if not isinstance(md_text, str) or not md_text.strip():
        return "", "", ""
    m = re.search(r"\*\*出生\*\*[:：][ \t]*([^\n]*)", md_text)
    if not m:
        m = re.search(r"(?:出生)[:：][ \t]*([^\n]*)", md_text)
    text = str(m.group(1) or "").strip() if m else ""
    if not text:
        return "", "", ""
    text = re.sub(
        r"^(?:约|大约)?(?:(?:公元前|公元|前)?\s*-?\d{1,4}(?:/\d{1,4})?\s*年(?:\d{1,2}月(?:\d{1,2}日)?)*[，,、 ]*)",
        "",
        text,
    ).strip()
    text = re.sub(r"^[（(][^）)]*[）)]\s*", "", text).strip()
    text = re.sub(r"^(?:出生于|生于|出生在|诞生于)", "", text).strip()
    text = re.sub(r"[（(][^）)]*(?:存疑|说法|待考|不详)[^）)]*[）)]$", "", text).strip(" ，,。；;")
    if not text:
        return "", "", ""
    if any(token in text for token in ("出生地存疑", "多种说法", "说法不一", "一说", "存疑")):
        return text, text, ""
    parts = [p.strip() for p in re.split(r"[，,]", text) if p.strip()]
    loc = parts[0] if parts else text
    loc = re.sub(r"^一说[^，,]+[，,]\s*", "", loc).strip()
    ancient = loc
    modern = ""
    if "（" in loc and "）" in loc:
        left, right = loc.split("（", 1)
        ancient = left.strip()
        modern = right.split("）", 1)[0].strip()
    elif "(" in loc and ")" in loc:
        left, right = loc.split("(", 1)
        ancient = left.strip()
        modern = right.split(")", 1)[0].strip()
    modern = re.sub(r"^今", "", modern).strip()
    return loc, ancient, modern


def _collect_people() -> List[str]:
    names: List[str] = []

    for p in [
        _data_input_path("pep_people_merged.json"),
        _data_input_path("pep_junior_all_people.json"),
        _data_input_path("pep_history_figures_sample.json"),
    ]:
        if p.exists():
            data = _read_json(p)
            if isinstance(data, list):
                names.extend([_safe_name(x) for x in data])

    p_by_book = _data_input_path("pep_junior_all_people_by_book.json")
    if p_by_book.exists():
        data = _read_json(p_by_book)
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    names.extend([_safe_name(x) for x in v])

    kg = _data_input_path("people_knowledge_graph.json")
    if kg.exists():
        data = _read_json(kg)
        if isinstance(data, dict):
            ns = data.get("nodes")
            if isinstance(ns, list):
                for n in ns:
                    if isinstance(n, dict):
                        names.append(_safe_name(n.get("id") or n.get("label")))
                    else:
                        names.append(_safe_name(n))

    names.extend(story_person_names(STORY_DIR))

    return sorted([name for name in _uniq(names) if is_valid_person_name(name)])


def _collect_people_pep() -> List[str]:
    p = _data_input_path("pep_people_merged.json")
    if p.exists():
        data = _read_json(p)
        if isinstance(data, list):
            return sorted([name for name in _uniq([_safe_name(x) for x in data]) if is_valid_person_name(name)])
    kg = _data_input_path("people_knowledge_graph.json")
    if kg.exists():
        data = _read_json(kg)
        if isinstance(data, dict):
            ns = data.get("nodes")
            if isinstance(ns, list):
                names: List[str] = []
                for n in ns:
                    if isinstance(n, dict):
                        names.append(_safe_name(n.get("id") or n.get("label")))
                    else:
                        names.append(_safe_name(n))
                return sorted([name for name in _uniq(names) if is_valid_person_name(name)])
    return []


def _add_storymap_to_syspath() -> None:
    p = str(REPO_ROOT / "storymap" / "script")
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_story_md(
    people: List[str], fill_missing: bool, limit: int, skip_existing: bool, concurrency: int
) -> Dict[str, object]:
    created = 0
    attempted = 0
    failures: List[Dict[str, str]] = []
    if not fill_missing:
        return {"attempted": 0, "created": 0, "failures": []}

    targets: List[str] = []
    seen_targets = set()
    available_story_names = story_person_names(STORY_DIR)
    for name in people:
        target = str(canonical_person_name(name, available_story_names) or name).strip()
        if not target or target not in available_story_names or target in seen_targets:
            continue
        path = STORY_DIR / f"{target}.md"
        if skip_existing and path.exists():
            continue
        targets.append(target)
        seen_targets.add(target)
        if limit and len(targets) >= limit:
            break

    if not targets:
        return {"attempted": 0, "created": 0, "failures": []}

    _load_env()
    _add_storymap_to_syspath()
    from storymap.script.agent.registry import StoryAgentLLM, generate_historical_markdown, save_markdown  # type: ignore

    try:
        StoryAgentLLM()
    except Exception as e:
        return {"attempted": 0, "created": 0, "failures": [{"person": "", "error": f"{type(e).__name__}: {e}"}]}

    attempted = len(targets)
    workers = max(1, int(concurrency or 1))

    def _job(person: str) -> Tuple[str, Optional[str]]:
        client = StoryAgentLLM()
        md = generate_historical_markdown(client, person)
        if not md or not str(md).strip():
            raise RuntimeError("empty response")
        save_markdown(person, str(md))
        return person, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_job, person): person for person in targets}
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                fut.result()
                created += 1
                print(f"✅ 已保存人物生平: {name} ({created}/{attempted})", flush=True)
            except Exception as e:
                failures.append({"person": name, "error": f"{type(e).__name__}: {e}"})
                print(f"⚠️ 生成失败: {name} ({created}/{attempted}) - {type(e).__name__}: {e}", flush=True)
    return {"attempted": attempted, "created": created, "failures": failures[:20]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(data_corpus_output_path("people_master.json", project_root=REPO_ROOT)))
    ap.add_argument("--scope", choices=["pep", "all"], default="pep")
    ap.add_argument("--fill-missing", action="store_true", default=False)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    people = _collect_people_pep() if str(args.scope) == "pep" else _collect_people()
    only = _uniq([x.strip() for x in str(args.only or "").split(",") if x.strip()])
    if only:
        s = set(only)
        people = [p for p in people if p in s]

    gen = _ensure_story_md(
        people,
        bool(args.fill_missing),
        int(args.limit),
        bool(args.skip_existing),
        int(args.concurrency),
    )

    items: List[Dict[str, object]] = []
    for name in people:
        md_path = STORY_DIR / f"{name}.md"
        has_story = md_path.exists() and is_publishable_person_markdown(md_path)
        md_text = md_path.read_text(encoding="utf-8", errors="ignore") if has_story else ""
        birth_year, death_year = _pick_years(md_text) if md_text else (None, None)
        dynasty = _pick_dynasty(md_text) if md_text else ""
        bp_raw, bp_ancient, bp_modern = _pick_birthplace(md_text) if md_text else ("", "", "")
        items.append(
            {
                "person": name,
                "has_story": has_story,
                "story_md": str(md_path.relative_to(REPO_ROOT)) if has_story else "",
                "birth_year": birth_year,
                "death_year": death_year,
                "dynasty": dynasty,
                "birthplace": bp_ancient,
                "birthplace_raw": bp_raw,
                "birthplace_modern": bp_modern,
            }
        )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now(),
        "count": len(items),
        "people": items,
        "generation": gen,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "count": len(items), "generation": gen}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

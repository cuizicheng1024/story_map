#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List


file_path = Path(__file__).resolve()
REPO_ROOT = file_path.parents[2] if file_path.parent.name == "debug" else file_path.parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import geocode_service as gs
import map_client as mc
import parsers as ps
from project_paths import data_corpus_file_path, data_reports_output_path, data_runtime_output_path
from story_agents import StoryAgentLLM


JsonDict = Dict[str, object]


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_strings(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_string_list(value: object) -> List[str]:
    if isinstance(value, str):
        return _dedupe_strings([value])
    if not isinstance(value, list):
        return []
    return _dedupe_strings([str(item) for item in value if str(item or "").strip()])


def _normalize_candidate_names(value: object) -> List[str]:
    if isinstance(value, str):
        return _dedupe_strings([value])
    if not isinstance(value, list):
        return []
    names: List[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or "").strip()
            if text:
                names.append(text)
            continue
        text = str(item or "").strip()
        if text:
            names.append(text)
    return _dedupe_strings(names)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _pick_story_snippet(file_path: Path, place: str) -> str:
    target = str(place or "").strip()
    if not target or not file_path.exists():
        return ""
    try:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if target in stripped:
                return stripped[:200]
    except Exception:
        return ""
    return ""


def _place_type_from_text(raw_place: str, ancient_name: str, modern_candidates: List[str]) -> str:
    text = str(raw_place or "").strip()
    if ancient_name and modern_candidates:
        return "historical_place"
    if any(marker in text for marker in ("一带", "沿线", "流域", "地区", "高原", "山区", "草原", "群岛", "海域")):
        return "region"
    if any(marker in text for marker in ("道", "路", "走廊", "航线", "路线")):
        return "route"
    if modern_candidates:
        return "modern_place"
    return "uncertain"


def _write_target_from_type(place_type: str) -> str:
    if place_type == "historical_place":
        return "historical_index"
    if place_type in {"modern_place", "uncertain"}:
        return "place_aliases"
    if place_type in {"region", "route"}:
        return "skip"
    return "place_aliases"


def _build_heuristic_review(raw_place: str) -> JsonDict:
    ancient_name, modern_name = ps._split_ancient_modern(raw_place)
    recommended = ps._pick_geocode_name(modern_name or raw_place or ancient_name)
    modern_candidates = _dedupe_strings([recommended, modern_name])
    place_type = _place_type_from_text(raw_place, ancient_name, modern_candidates)
    return {
        "raw_place": raw_place,
        "normalized_place_key": gs.normalize_place_key(raw_place),
        "place_type": place_type,
        "ancient_name": str(ancient_name or "").strip(),
        "modern_candidates": modern_candidates,
        "recommended_search_name": recommended,
        "country": "",
        "admin_hint": "",
        "is_point_like": place_type not in {"region", "route"},
        "confidence": 0.35 if recommended else 0.2,
        "evidence": ["heuristic_pick_geocode_name"] if recommended else [],
        "needs_human_review": True,
        "should_write_to": _write_target_from_type(place_type),
        "llm_status": "skipped",
        "llm_error": "",
        "status": "pending_review",
        "human_decision": "",
        "human_notes": "",
        "approved_search_name": "",
        "approved_write_to": "",
        "approved_lat": None,
        "approved_lon": None,
    }


def _looks_like_real_place(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw in {"—", "-", "--", "世", "公元", "不详"}:
        return False
    place_markers = ("省", "市", "县", "区", "州", "郡", "府", "国", "镇", "乡", "村", "岛", "城", "京", "海", "山", "河", "湖")
    if any(marker in raw for marker in place_markers):
        return True
    if "（今" in raw or "(今" in raw:
        return True
    if "一说" in raw and any(marker in raw for marker in ("河南", "河北", "安徽", "江苏", "浙江", "四川", "湖北", "湖南", "福建", "广东", "山东", "陕西")):
        return True
    trimmed = getattr(mc, "_trim_geocode_candidate", lambda value: str(value or "").strip())(raw)
    reason = getattr(mc, "_reject_geocode_candidate_reason", lambda _value: "")(trimmed or raw)
    return not bool(reason)


def _load_negative_cache(path: Path) -> Dict[str, JsonDict]:
    if not path.exists():
        return {}
    try:
        raw = _read_json(path)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, JsonDict] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name or not isinstance(value, dict):
            continue
        out[name] = {
            "reason": str(value.get("reason") or "").strip(),
            "updated_at": _safe_float(value.get("updated_at")),
            "expires_at": _safe_float(value.get("expires_at")),
        }
    return out


def _load_low_coverage_report(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    try:
        raw = _read_json(path)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _ensure_review_item(queue: Dict[str, JsonDict], raw_place: str) -> JsonDict:
    place = str(raw_place or "").strip()
    if not _looks_like_real_place(place):
        return {}
    item = queue.get(place)
    if item is not None:
        return item
    heuristic = _build_heuristic_review(place)
    item = {
        **heuristic,
        "sources": {
            "negative_cache": False,
            "low_coverage_mentions": 0,
        },
        "negative_cache": {},
        "references": [],
    }
    queue[place] = item
    return item


def _append_reference(item: JsonDict, *, person: str, file: str, kind: str, snippet: str) -> None:
    refs = item.get("references")
    if not isinstance(refs, list):
        refs = []
        item["references"] = refs
    ref = {
        "person": str(person or "").strip(),
        "file": str(file or "").strip(),
        "kind": str(kind or "").strip(),
        "snippet": str(snippet or "").strip(),
    }
    ref_key = (ref["person"], ref["file"], ref["kind"], ref["snippet"])
    existing = {
        (str(x.get("person") or ""), str(x.get("file") or ""), str(x.get("kind") or ""), str(x.get("snippet") or ""))
        for x in refs
        if isinstance(x, dict)
    }
    if ref_key not in existing:
        refs.append(ref)


def collect_review_items(low_coverage_report: JsonDict, negative_cache: Dict[str, JsonDict], limit: int = 100) -> List[JsonDict]:
    queue: Dict[str, JsonDict] = {}

    for raw_place, meta in negative_cache.items():
        item = _ensure_review_item(queue, raw_place)
        if not item:
            continue
        sources = item.get("sources")
        if isinstance(sources, dict):
            sources["negative_cache"] = True
        item["negative_cache"] = dict(meta)

    top_people = low_coverage_report.get("top_people")
    if isinstance(top_people, list):
        for row in top_people:
            if not isinstance(row, dict):
                continue
            person = str(row.get("person") or "").strip()
            file_rel = str(row.get("file") or "").strip()
            file_path = (REPO_ROOT / file_rel).resolve() if file_rel else Path()
            places: List[tuple[str, str]] = []
            for loc in list(row.get("unresolved_locations") or []):
                if str(loc or "").strip():
                    places.append((str(loc).strip(), "unresolved"))
            if row.get("birth_missing_coord") and str(row.get("birth_location") or "").strip():
                places.append((str(row.get("birth_location")).strip(), "birth"))
            if row.get("death_missing_coord") and str(row.get("death_location") or "").strip():
                places.append((str(row.get("death_location")).strip(), "death"))
            for raw_place, kind in places:
                item = _ensure_review_item(queue, raw_place)
                if not item:
                    continue
                sources = item.get("sources")
                if isinstance(sources, dict):
                    sources["low_coverage_mentions"] = int(sources.get("low_coverage_mentions", 0)) + 1
                snippet = _pick_story_snippet(file_path, raw_place)
                _append_reference(item, person=person, file=file_rel, kind=kind, snippet=snippet)

    items = list(queue.values())
    items.sort(
        key=lambda item: (
            -int(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("low_coverage_mentions", 0)),
            0 if (((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("negative_cache")) else 1,
            str(item.get("raw_place") or ""),
        )
    )
    return items[: max(1, int(limit))]


def _extract_json_array(raw: str) -> List[JsonDict]:
    text = str(raw or "").strip()
    if not text:
        return []
    for candidate in [text, text[text.find("[") : text.rfind("]") + 1] if "[" in text and "]" in text else ""]:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, list):
            return [dict(item) for item in data if isinstance(item, dict)]
    return []


def _build_llm_messages(chunk: List[JsonDict]) -> List[Dict[str, str]]:
    payload = []
    for item in chunk:
        payload.append(
            {
                "raw_place": str(item.get("raw_place") or ""),
                "references": [
                    {
                        "person": str(ref.get("person") or ""),
                        "kind": str(ref.get("kind") or ""),
                        "snippet": str(ref.get("snippet") or ""),
                    }
                    for ref in list(item.get("references") or [])
                    if isinstance(ref, dict)
                ][:3],
                "negative_cache_reason": str(((item.get("negative_cache") or {}) if isinstance(item.get("negative_cache"), dict) else {}).get("reason") or ""),
                "heuristic_recommended_search_name": str(item.get("recommended_search_name") or ""),
            }
        )
    sys_prompt = (
        "你是疑难地名审核助手。请基于输入地名、人物上下文与已有启发式结果，"
        "输出严格 JSON 数组，每个元素包含字段："
        "raw_place, place_type, ancient_name, modern_candidates, recommended_search_name, "
        "country, admin_hint, is_point_like, confidence, evidence, needs_human_review, should_write_to。"
        "不要编造经纬度。无法确定时 needs_human_review=true，confidence 取 0 到 1。"
        "should_write_to 仅能是 markdown_coords、place_aliases、historical_index、skip 之一。"
    )
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"待审核地点列表：{json.dumps(payload, ensure_ascii=False)}"},
    ]


def enrich_items_with_llm(
    items: List[JsonDict],
    *,
    llm_mode: str,
    llm_factory: Callable[[], StoryAgentLLM] = StoryAgentLLM,
    chunk_size: int = 8,
) -> List[JsonDict]:
    mode = str(llm_mode or "auto").strip().lower()
    if mode == "off":
        return items
    try:
        client = llm_factory()
    except Exception as exc:
        if mode == "on":
            for item in items:
                item["llm_status"] = "error"
                item["llm_error"] = str(exc)
            return items
        for item in items:
            item["llm_status"] = "fallback"
            item["llm_error"] = str(exc)
        return items

    for i in range(0, len(items), max(1, int(chunk_size))):
        chunk = items[i : i + max(1, int(chunk_size))]
        raw = client.think(_build_llm_messages(chunk), temperature=0) or ""
        mapped = {
            str(entry.get("raw_place") or "").strip(): entry
            for entry in _extract_json_array(raw)
            if str(entry.get("raw_place") or "").strip()
        }
        for item in chunk:
            place = str(item.get("raw_place") or "").strip()
            llm_entry = mapped.get(place)
            if not isinstance(llm_entry, dict):
                item["llm_status"] = "fallback"
                continue
            item["place_type"] = str(llm_entry.get("place_type") or item.get("place_type") or "")
            item["ancient_name"] = str(llm_entry.get("ancient_name") or item.get("ancient_name") or "")
            item["modern_candidates"] = _normalize_candidate_names(llm_entry.get("modern_candidates"))
            item["recommended_search_name"] = str(llm_entry.get("recommended_search_name") or item.get("recommended_search_name") or "")
            item["country"] = str(llm_entry.get("country") or "")
            item["admin_hint"] = str(llm_entry.get("admin_hint") or "")
            item["is_point_like"] = bool(llm_entry.get("is_point_like"))
            item["confidence"] = max(0.0, min(1.0, _safe_float(llm_entry.get("confidence"), _safe_float(item.get("confidence"), 0.0))))
            item["evidence"] = _normalize_string_list(llm_entry.get("evidence"))
            item["needs_human_review"] = bool(llm_entry.get("needs_human_review", True))
            write_target = str(llm_entry.get("should_write_to") or item.get("should_write_to") or "")
            item["should_write_to"] = write_target if write_target in {"markdown_coords", "place_aliases", "historical_index", "skip"} else item.get("should_write_to")
            item["llm_status"] = "ok"
            item["llm_error"] = ""
    return items


def build_review_queue(
    *,
    low_coverage_path: Path,
    negative_cache_path: Path,
    out_story_dir: Path,
    limit: int,
    llm_mode: str,
    llm_factory: Callable[[], StoryAgentLLM] = StoryAgentLLM,
) -> JsonDict:
    _ = out_story_dir
    low_coverage_report = _load_low_coverage_report(low_coverage_path)
    negative_cache = _load_negative_cache(negative_cache_path)
    items = collect_review_items(low_coverage_report, negative_cache, limit=limit)
    items = enrich_items_with_llm(items, llm_mode=llm_mode, llm_factory=llm_factory)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "llm_mode": llm_mode,
        "inputs": {
            "low_coverage_json": str(low_coverage_path.relative_to(REPO_ROOT)) if low_coverage_path.is_relative_to(REPO_ROOT) else str(low_coverage_path),
            "negative_cache_json": str(negative_cache_path.relative_to(REPO_ROOT)) if negative_cache_path.is_relative_to(REPO_ROOT) else str(negative_cache_path),
        },
        "summary": {
            "items": len(items),
            "with_negative_cache": sum(1 for item in items if bool(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("negative_cache"))),
            "with_low_coverage_context": sum(1 for item in items if int(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("low_coverage_mentions", 0)) > 0),
            "llm_enriched": sum(1 for item in items if str(item.get("llm_status") or "") == "ok"),
        },
        "items": items,
    }


def _is_valid_coord_pair(lat: object, lon: object) -> bool:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return False
    return -90 <= lat_f <= 90 and -180 <= lon_f <= 180


def _resolve_item_coord(item: JsonDict) -> tuple[Optional[float], Optional[float], str]:
    approved_lat = item.get("approved_lat")
    approved_lon = item.get("approved_lon")
    if _is_valid_coord_pair(approved_lat, approved_lon):
        return float(approved_lat), float(approved_lon), "manual"
    search_name = str(item.get("approved_search_name") or item.get("recommended_search_name") or "").strip()
    if not search_name:
        return None, None, "missing_search_name"
    coord = mc.geocode_city(search_name)
    if coord and _is_valid_coord_pair(coord[0], coord[1]):
        return float(coord[0]), float(coord[1]), "geocode"
    return None, None, "geocode_failed"


def _load_place_aliases_json(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    try:
        raw = _read_json(path)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_place_aliases_json(path: Path, data: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_historical_index_rows(path: Path) -> List[JsonDict]:
    rows: List[JsonDict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        s = str(line or "").strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _write_historical_index_rows(path: Path, rows: List[JsonDict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else "")
    path.write_text(content, encoding="utf-8")


def apply_confirmed_items(
    queue: JsonDict,
    *,
    place_aliases_path: Path,
    historical_index_path: Path,
) -> JsonDict:
    alias_data = _load_place_aliases_json(place_aliases_path)
    historical_rows = _load_historical_index_rows(historical_index_path)
    hist_map = {
        gs.normalize_place_key(str(row.get("ancient_name") or "")): idx
        for idx, row in enumerate(historical_rows)
        if isinstance(row, dict) and gs.normalize_place_key(str(row.get("ancient_name") or ""))
    }
    applied = 0
    skipped = 0
    failed = 0

    for item in list(queue.get("items") or []):
        if not isinstance(item, dict):
            continue
        decision = str(item.get("human_decision") or item.get("status") or "").strip().lower()
        if decision not in {"approve", "approved", "accept", "accepted", "apply"}:
            skipped += 1
            continue
        target = str(item.get("approved_write_to") or item.get("should_write_to") or "").strip()
        raw_place = str(item.get("raw_place") or "").strip()
        if target not in {"place_aliases", "historical_index", "markdown_coords"}:
            item["status"] = "apply_skipped"
            item["human_notes"] = (str(item.get("human_notes") or "") + " unsupported_target").strip()
            skipped += 1
            continue
        if target == "markdown_coords":
            item["status"] = "apply_skipped"
            item["human_notes"] = (str(item.get("human_notes") or "") + " markdown_coords_requires_manual_patch").strip()
            skipped += 1
            continue

        search_name = str(item.get("approved_search_name") or item.get("recommended_search_name") or "").strip()
        candidate_names = _dedupe_strings([search_name, *_normalize_candidate_names(item.get("modern_candidates"))])
        lat, lon, coord_source = _resolve_item_coord(item)

        if target == "place_aliases":
            entry: JsonDict = {"names": candidate_names}
            if _is_valid_coord_pair(lat, lon):
                entry["coords"] = [float(lat), float(lon)]
            alias_data[raw_place] = entry
            item["status"] = "applied"
            item["applied_target"] = "place_aliases"
            item["applied_coord_source"] = coord_source
            if _is_valid_coord_pair(lat, lon):
                item["approved_lat"] = float(lat)
                item["approved_lon"] = float(lon)
            applied += 1
            continue

        ancient_name = str(item.get("ancient_name") or raw_place).strip()
        if not ancient_name or not search_name or not _is_valid_coord_pair(lat, lon):
            item["status"] = "apply_failed"
            item["human_notes"] = (str(item.get("human_notes") or "") + f" missing_historical_coord_or_name:{coord_source}").strip()
            failed += 1
            continue
        row = {
            "ancient_name": ancient_name,
            "modern_name": search_name,
            "lat": float(lat),
            "lon": float(lon),
        }
        norm_ancient = gs.normalize_place_key(ancient_name)
        if norm_ancient in hist_map:
            historical_rows[hist_map[norm_ancient]] = row
        else:
            hist_map[norm_ancient] = len(historical_rows)
            historical_rows.append(row)
        item["status"] = "applied"
        item["applied_target"] = "historical_index"
        item["applied_coord_source"] = coord_source
        item["approved_lat"] = float(lat)
        item["approved_lon"] = float(lon)
        applied += 1

    _write_place_aliases_json(place_aliases_path, alias_data)
    _write_historical_index_rows(historical_index_path, historical_rows)
    queue["apply_summary"] = {
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "place_aliases_path": str(place_aliases_path.relative_to(REPO_ROOT)) if place_aliases_path.is_relative_to(REPO_ROOT) else str(place_aliases_path),
        "historical_index_path": str(historical_index_path.relative_to(REPO_ROOT)) if historical_index_path.is_relative_to(REPO_ROOT) else str(historical_index_path),
    }
    return queue


def render_markdown(queue: JsonDict) -> str:
    lines = [
        "# 疑难地点人工审核队列",
        "",
        f"- 生成时间：{queue.get('generated_at', '')}",
        f"- LLM 模式：`{queue.get('llm_mode', '')}`",
        f"- 待审核地点数：`{queue.get('summary', {}).get('items', 0)}`",
        f"- 命中负缓存的地点数：`{queue.get('summary', {}).get('with_negative_cache', 0)}`",
        f"- 带低覆盖上下文的地点数：`{queue.get('summary', {}).get('with_low_coverage_context', 0)}`",
        "",
        "## 待审核地点",
        "",
        "| 地点 | 推荐搜索名 | 类型 | 建议落点 | 置信度 | 来源 | LLM |",
        "| :--- | :--- | :--- | :--- | ---: | :--- | :--- |",
    ]
    for item in list(queue.get("items") or []):
        if not isinstance(item, dict):
            continue
        sources = item.get("sources") if isinstance(item.get("sources"), dict) else {}
        source_labels = []
        if sources.get("negative_cache"):
            source_labels.append("负缓存")
        if int(sources.get("low_coverage_mentions", 0)) > 0:
            source_labels.append(f"低覆盖x{int(sources.get('low_coverage_mentions', 0))}")
        lines.append(
            "| {raw} | {search} | {ptype} | {target} | {confidence:.2f} | {sources} | {llm} |".format(
                raw=str(item.get("raw_place") or ""),
                search=str(item.get("recommended_search_name") or "-"),
                ptype=str(item.get("place_type") or "-"),
                target=str(item.get("should_write_to") or "-"),
                confidence=_safe_float(item.get("confidence"), 0.0),
                sources="、".join(source_labels) or "-",
                llm=str(item.get("llm_status") or "-"),
            )
        )
    lines.extend(["", "## 审核说明", "", "- `place_aliases`：适合别名、旧译名、国外中文长串写法。", "- `historical_index`：适合古今映射稳定的历史地名。", "- `markdown_coords`：适合只在单个人物稿件中成立的专属地点。", "- `skip`：区域、路线或证据不足，暂不落点。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成疑难地点人工审核队列，可选调用 MiniMax 生成候选归一结果")
    parser.add_argument("--low-coverage-json", default=str(data_reports_output_path("low_coverage_story_report.json", project_root=REPO_ROOT)))
    parser.add_argument("--negative-cache-json", default=str(REPO_ROOT / ".cache" / "map_story_geocode_negative_cache.json"))
    parser.add_argument("--story-dir", default=str(REPO_ROOT / "storymap" / "examples" / "story"))
    parser.add_argument("--out-json", default=str(data_runtime_output_path("hard_place_review_queue.json", project_root=REPO_ROOT)))
    parser.add_argument("--out-md", default=str(data_runtime_output_path("hard_place_review_queue.md", project_root=REPO_ROOT)))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--llm-mode", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--queue-json", default="")
    parser.add_argument("--apply-confirmed", action="store_true")
    parser.add_argument("--place-aliases-json", default=str(data_corpus_file_path("place_aliases.json", project_root=REPO_ROOT)))
    parser.add_argument("--historical-index-jsonl", default=str(data_corpus_file_path("historical_places_index.jsonl", project_root=REPO_ROOT)))
    args = parser.parse_args()

    low_coverage_path = Path(args.low_coverage_json).resolve()
    negative_cache_path = Path(args.negative_cache_json).resolve()
    story_dir = Path(args.story_dir).resolve()
    out_json = Path(args.out_json).resolve()
    out_md = Path(args.out_md).resolve()
    queue_json = Path(args.queue_json).resolve() if str(args.queue_json or "").strip() else out_json
    place_aliases_path = Path(args.place_aliases_json).resolve()
    historical_index_path = Path(args.historical_index_jsonl).resolve()

    if args.apply_confirmed:
        loaded = _read_json(queue_json) if queue_json.exists() else {}
        queue = loaded if isinstance(loaded, dict) else {}
        if not queue:
            raise SystemExit(f"审核队列不存在或格式无效: {queue_json}")
        queue = apply_confirmed_items(
            queue,
            place_aliases_path=place_aliases_path,
            historical_index_path=historical_index_path,
        )
        out_json = queue_json
    else:
        queue = build_review_queue(
            low_coverage_path=low_coverage_path,
            negative_cache_path=negative_cache_path,
            out_story_dir=story_dir,
            limit=max(1, int(args.limit)),
            llm_mode=str(args.llm_mode or "auto"),
        )

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(queue), encoding="utf-8")

    print(f"[review] json={out_json}")
    print(f"[review] md={out_md}")
    print(
        "[summary] items={items} negative_cache={negative_cache} low_coverage={low_coverage} llm_enriched={llm}".format(
            items=int(queue.get("summary", {}).get("items", 0)),
            negative_cache=int(queue.get("summary", {}).get("with_negative_cache", 0)),
            low_coverage=int(queue.get("summary", {}).get("with_low_coverage_context", 0)),
            llm=int(queue.get("summary", {}).get("llm_enriched", 0)),
        )
    )
    if args.apply_confirmed:
        apply_summary = queue.get("apply_summary") if isinstance(queue.get("apply_summary"), dict) else {}
        print(
            "[apply] applied={applied} skipped={skipped} failed={failed}".format(
                applied=int(apply_summary.get("applied", 0)),
                skipped=int(apply_summary.get("skipped", 0)),
                failed=int(apply_summary.get("failed", 0)),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

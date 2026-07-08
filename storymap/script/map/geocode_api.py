from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


JsonDict = Dict[str, object]
_HARD_PLACE_QUEUE_LOCK = threading.Lock()

from ..core.project_paths import data_runtime_output_path
from .geocode_candidates import reject_geocode_candidate_reason, trim_geocode_candidate


def _parser_utils():
    from ..core import parsers as parser_utils
    return parser_utils

def _dedupe_strings(values: List[object]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _load_json_dict(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_dict(path: Path, data: JsonDict) -> None:
    """Write JSON atomically: write to a sibling temp file then rename.

    Avoids leaving the queue file half-written when the process is killed
    or the disk is full mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _hard_place_queue_path(queue_json_path: str = "") -> Path:
    override = str(queue_json_path or "").strip() or str(os.getenv("STORY_HARD_PLACE_QUEUE_JSON") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return data_runtime_output_path("hard_place_review_queue.json", project_root=project_root_path()).resolve()


def _looks_like_reviewable_place(place_name: str) -> bool:
    raw = str(place_name or "").strip()
    if not raw:
        return False
    trimmed = trim_geocode_candidate(raw)
    reject_reason = reject_geocode_candidate_reason(trimmed or raw)
    return not bool(reject_reason)


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


def _append_reference(item: JsonDict, *, person: str, context: str) -> None:
    person_name = str(person or "").strip()
    snippet = str(context or "").strip()
    if not person_name and not snippet:
        return
    refs = item.get("references")
    if not isinstance(refs, list):
        refs = []
        item["references"] = refs
    ref = {
        "person": person_name,
        "file": "",
        "kind": "agent_context",
        "snippet": snippet,
    }
    ref_key = (ref["person"], ref["kind"], ref["snippet"])
    existing = {
        (str(x.get("person") or ""), str(x.get("kind") or ""), str(x.get("snippet") or ""))
        for x in refs
        if isinstance(x, dict)
    }
    if ref_key not in existing:
        refs.append(ref)


def _refresh_queue_summary(queue: JsonDict) -> None:
    items = [item for item in list(queue.get("items") or []) if isinstance(item, dict)]
    queue["summary"] = {
        "items": len(items),
        "with_negative_cache": sum(
            1
            for item in items
            if bool(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("negative_cache"))
        ),
        "with_low_coverage_context": sum(
            1
            for item in items
            if int(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("low_coverage_mentions", 0)) > 0
        ),
        "llm_enriched": sum(1 for item in items if str(item.get("llm_status") or "") == "ok"),
        "agent_submitted": sum(
            1
            for item in items
            if int(((item.get("sources") or {}) if isinstance(item.get("sources"), dict) else {}).get("agent_submissions", 0)) > 0
        ),
    }


def _build_agent_review_item(place_name: str, *, geocode_service_utils: object) -> JsonDict:
    parser_utils = _parser_utils()
    raw_place = str(place_name or "").strip()
    ancient_name, modern_name = geocode_service_utils.split_ancient_modern(raw_place, event_callback=None)
    recommended = parser_utils.pick_geocode_name(modern_name or raw_place or ancient_name)
    modern_candidates = _dedupe_strings([recommended, modern_name])
    place_type = _place_type_from_text(raw_place, ancient_name, modern_candidates)
    return {
        "raw_place": raw_place,
        "normalized_place_key": geocode_service_utils.normalize_place_key(raw_place),
        "place_type": place_type,
        "ancient_name": str(ancient_name or "").strip(),
        "modern_candidates": modern_candidates,
        "recommended_search_name": recommended,
        "country": "",
        "admin_hint": "",
        "is_point_like": place_type not in {"region", "route"},
        "confidence": 0.25 if recommended else 0.15,
        "evidence": ["agent_geocode_fallback"] if recommended else [],
        "needs_human_review": True,
        "should_write_to": _write_target_from_type(place_type),
        "llm_status": "queued_by_agent",
        "llm_error": "",
        "status": "pending_review",
        "human_decision": "",
        "human_notes": "",
        "approved_search_name": "",
        "approved_write_to": "",
        "approved_lat": None,
        "approved_lon": None,
        "sources": {
            "negative_cache": False,
            "low_coverage_mentions": 0,
            "agent_submissions": 0,
        },
        "negative_cache": {},
        "references": [],
    }


def submit_hard_place_for_review(
    payload: Dict[str, object],
    *,
    geocode_service_utils: object,
) -> Dict[str, object]:
    data = dict(payload or {})
    place_name = str(data.get("place_name") or data.get("raw_place") or "").strip()
    if not place_name:
        return {
            "status": "skipped",
            "queued": False,
            "raw_place": "",
            "normalized_place_key": "",
            "recommended_search_name": "",
            "review_item_id": "",
            "queue_path": "",
            "reason": "missing_place_name",
        }
    if not _looks_like_reviewable_place(place_name):
        return {
            "status": "skipped",
            "queued": False,
            "raw_place": place_name,
            "normalized_place_key": "",
            "recommended_search_name": "",
            "review_item_id": "",
            "queue_path": "",
            "reason": "invalid_place_name",
        }
    queue_path = _hard_place_queue_path(str(data.get("queue_json_path") or ""))
    normalized_key = geocode_service_utils.normalize_place_key(place_name)
    reason = str(data.get("reason") or "geocode_failed").strip() or "geocode_failed"
    person = str(data.get("person") or "").strip()
    context = str(data.get("context") or "").strip()
    with _HARD_PLACE_QUEUE_LOCK:
        queue = _load_json_dict(queue_path)
        items = queue.get("items")
        if not isinstance(items, list):
            items = []
            queue["items"] = items
        existing: Optional[JsonDict] = None
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_place = str(item.get("raw_place") or "").strip()
            if raw_place == place_name or geocode_service_utils.normalize_place_key(raw_place) == normalized_key:
                existing = item
                break
        if existing is None:
            existing = _build_agent_review_item(place_name, geocode_service_utils=geocode_service_utils)
            items.append(existing)
            status = "queued"
        else:
            status = "already_queued"
        if reason:
            evidence = existing.get("evidence")
            if not isinstance(evidence, list):
                evidence = []
                existing["evidence"] = evidence
            if reason not in {str(item or "").strip() for item in evidence}:
                evidence.append(reason)
        sources = existing.get("sources")
        if not isinstance(sources, dict):
            sources = {}
            existing["sources"] = sources
        sources["negative_cache"] = bool(sources.get("negative_cache"))
        sources["low_coverage_mentions"] = int(sources.get("low_coverage_mentions", 0) or 0)
        sources["agent_submissions"] = int(sources.get("agent_submissions", 0) or 0) + 1
        _append_reference(existing, person=person, context=context)
        existing["status"] = "pending_review"
        queue.setdefault("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        queue["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        queue["llm_mode"] = str(queue.get("llm_mode") or "agent_queue")
        queue_inputs = queue.get("inputs")
        if not isinstance(queue_inputs, dict):
            queue_inputs = {}
            queue["inputs"] = queue_inputs
        queue_inputs.setdefault("source", "agent_queue")
        _refresh_queue_summary(queue)
        _write_json_dict(queue_path, queue)
    return {
        "status": status,
        "queued": True,
        "raw_place": place_name,
        "normalized_place_key": str(existing.get("normalized_place_key") or normalized_key),
        "recommended_search_name": str(existing.get("recommended_search_name") or ""),
        "review_item_id": normalized_key or place_name,
        "queue_path": str(queue_path),
        "reason": reason,
    }


def create_geocode_api(*, geocode_service_utils: object) -> Dict[str, Callable[..., object]]:
    def lookup_coords_from_historical_index(*names: str, dynasty: Optional[str] = None) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.lookup_coords_from_historical_index(*names, dynasty=dynasty)

    def resolve_place_coord(place: str, year: Optional[int] = None, *aliases: str, dynasty: Optional[str] = None) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.resolve_place_coord(place, year, *aliases, dynasty=dynasty)

    def batch_split_ancient_modern(
        loc_texts: List[str], event_callback: Optional[callable] = None
    ) -> Dict[str, Tuple[str, str]]:
        return geocode_service_utils.batch_split_ancient_modern(
            loc_texts,
            event_callback=event_callback,
        )

    def split_ancient_modern(
        loc_text: str,
        event_callback: Optional[callable] = None,
    ) -> Tuple[str, str]:
        return geocode_service_utils.split_ancient_modern(
            loc_text,
            event_callback=event_callback,
        )

    def fuzzy_coord_lookup(
        coords_cache: Dict[str, Tuple[float, float]],
        candidates: List[str],
    ) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.fuzzy_coord_lookup(coords_cache, candidates)

    def submit_hard_place_review(payload: Dict[str, object]) -> Dict[str, object]:
        return submit_hard_place_for_review(payload, geocode_service_utils=geocode_service_utils)

    return {
        "lookup_coords_from_historical_index": lookup_coords_from_historical_index,
        "resolve_place_coord": resolve_place_coord,
        "batch_split_ancient_modern": batch_split_ancient_modern,
        "split_ancient_modern": split_ancient_modern,
        "fuzzy_coord_lookup": fuzzy_coord_lookup,
        "submit_hard_place_review": submit_hard_place_review,
    }

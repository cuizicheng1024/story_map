from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tools.build.homepage.config import HOME_DETAIL_NODE_FIELDS, MAX_YEAR, MIN_YEAR, ROLE_BAND_LABELS, ROLE_BAND_ORDER
from tools.build.homepage_search import HAS_PINYIN
from storymap.script.core.build_meta import build_artifact_meta
from tools.build.homepage.loaders import _is_foreign_person


def _build_payload_meta() -> Dict[str, object]:
    return build_artifact_meta(component="stellar_homepage")

def _prepare_home_payload_for_output(base_payload: Dict[str, Any], *, default_start: int, default_end: int) -> Dict[str, Any]:
    try:
        min_year = int(base_payload.get("min_year")) if base_payload.get("min_year") not in (None, "") else None
    except Exception:
        min_year = None
    try:
        max_year = int(base_payload.get("max_year")) if base_payload.get("max_year") not in (None, "") else None
    except Exception:
        max_year = None
    nodes = base_payload.get("nodes") if isinstance(base_payload.get("nodes"), list) else []
    normalized_nodes: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        normalized = dict(node)
        normalized["is_foreign"] = _is_foreign_person(
            foreign_name=str(normalized.get("foreign_name") or ""),
            birthplace_modern=str(normalized.get("birthplace_modern") or ""),
            birthplace_raw=str(normalized.get("birthplace_raw") or ""),
            dynasty=str(normalized.get("dynasty") or ""),
        )
        normalized_nodes.append(normalized)
    edges = base_payload.get("edges") if isinstance(base_payload.get("edges"), list) else []
    kg_edges = base_payload.get("kg_edges") if isinstance(base_payload.get("kg_edges"), list) else []
    return {
        **_build_payload_meta(),
        "min_year": min_year if min_year is not None else MIN_YEAR,
        "max_year": max_year if max_year is not None else MAX_YEAR,
        "default_start": int(default_start),
        "default_end": int(default_end),
        "role_band_order": ROLE_BAND_ORDER,
        "role_band_labels": ROLE_BAND_LABELS,
        "search_capabilities": {
            "aliases": True,
            "foreign_name": True,
            "pinyin": HAS_PINYIN,
        },
        "nodes": normalized_nodes,
        "edges": edges,
        "kg_edges": kg_edges,
    }


def _derive_home_detail_file_name(out_data_name: str) -> str:
    path = Path(str(out_data_name or "stellar_home_data.json"))
    suffix = path.suffix or ".json"
    stem = path.stem or "stellar_home_data"
    return f"{stem}_detail{suffix}"


def _split_home_payload_for_delivery(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    core_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    detail_payload: Dict[str, Any] = {
        **_build_payload_meta(),
        "fields": list(HOME_DETAIL_NODE_FIELDS),
        "nodes": [],
    }
    nodes = core_payload.get("nodes") if isinstance(core_payload.get("nodes"), list) else []
    detail_nodes: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        detail_node: Dict[str, Any] = {}
        for field in HOME_DETAIL_NODE_FIELDS:
            if field in node:
                detail_node[field] = node.pop(field)
        if detail_node:
            detail_node["person"] = str(node.get("person") or "").strip()
            detail_node["file"] = str(node.get("file") or "").strip()
            detail_nodes.append(detail_node)
    detail_payload["nodes"] = detail_nodes
    detail_payload["count"] = len(detail_nodes)
    return core_payload, detail_payload


def _write_homepage_outputs(
    *,
    story_map_dir: Path,
    out_index_name: str,
    out_data_name: str,
    title: str,
    payload: Dict[str, Any],
    active_redirects: Dict[str, str],
    sync_payload_to_neo4j: bool,
) -> Dict[str, Any]:
    out_data = story_map_dir / str(out_data_name)
    out_detail = story_map_dir / _derive_home_detail_file_name(str(out_data_name))
    out_index = story_map_dir / str(out_index_name)
    core_payload, detail_payload = _split_home_payload_for_delivery(payload)
    if write_normalized_graph_json:
        try:
            write_normalized_graph_json(payload, GRAPH_ARTIFACT_DIR / "normalized_graph.json")
        except Exception:
            pass
    if sync_payload_to_neo4j and should_sync_to_neo4j and sync_graph_payload_to_neo4j:
        try:
            if should_sync_to_neo4j():
                sync_graph_payload_to_neo4j(payload, replace=True)
        except Exception:
            pass
    out_data.write_text(json.dumps(core_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_detail.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_index.write_text(_render_index_html(title, out_data.name, out_detail.name), encoding="utf-8")
    _remove_person_alias_redirect_pages(story_map_dir, active_redirects)
    _sync_vendor_assets(story_map_dir)
    _sync_embedded_apps(story_map_dir)
    _sync_homepage_pet_asset(story_map_dir)
    return {
        "index": str(out_index),
        "data": str(out_data),
        "detail": str(out_detail),
        "count": len(core_payload.get("nodes") if isinstance(core_payload.get("nodes"), list) else []),
    }



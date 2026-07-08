"""人物关系图谱匹配 — Markdown 语义提取 + 图谱查询。

存储层（Neo4j / JSON / SQLite 加载）见 graph_store.py。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3 as _sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

from .graph_store import (  # noqa: F401 - re-exported for backward compatibility
    Neo4jConfig,
    _build_payload_from_neo4j,
    _coerce_bool,
    _coerce_float,
    _coerce_graph_person_row,
    _coerce_int,
    _decode_json_property,
    _domain_id,
    _driver,
    _dynasty_id,
    _json_property,
    _person_id,
    _string_list,
    build_home_graph_file_fallback,
    close_graph_driver,
    graph_backend_name,
    home_graph_person_names,
    invalidate_graph_service_cache,
    load_home_graph_payload,
    load_home_graph_payload_with_source,
    neo4j_config,
    neo4j_enabled,
    normalize_graph_payload,
    should_sync_to_neo4j,
    sync_graph_payload_to_neo4j,
    write_normalized_graph_json,
)
from ..core.person_registry import canonical_person_name


def _normalize_person_token(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    s = re.sub(r"[（(].*?[）)]", "", s).strip()
    s = re.sub(r"[《》【】\[\]<>\"“”‘’·•\s]+", "", s)
    return s.strip()


def _normalize_dynasty(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    for sep in ("（", "("):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    for suffix in ("时期", "时代", "王朝"):
        s = s.replace(suffix, "")
    return s.strip()


def _same_dynasty(a: Any, b: Any) -> bool:
    sa = _normalize_dynasty(a)
    sb = _normalize_dynasty(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    if sa in sb or sb in sa:
        return True
    return len(sa) >= 2 and len(sb) >= 2 and sa[:2] == sb[:2]


def _extract_markdown_title(markdown: str) -> str:
    text = str(markdown or "")
    m = re.search(r"^\s*#\s+([^\n#]+)", text, flags=re.MULTILINE)
    return str(m.group(1) or "").strip() if m else ""


def _pick_year_range(
    person: Dict[str, Any],
    node: Optional[Dict[str, Any]] = None,
    *,
    use_heuristics: bool = True,
) -> Tuple[Optional[int], Optional[int]]:
    """Extract birth/death years from person + node data.

    When ``use_heuristics=True`` (default for scoring/matching), also tries
    ``time_year`` and lifespan-derived death for gap-filling.
    When ``False`` (display-only), strictly uses birth/death dates and node years.
    """
    node = node or {}
    birth = _coerce_int(((person.get("birth") or {}) if isinstance(person.get("birth"), dict) else {}).get("date"))
    death = _coerce_int(((person.get("death") or {}) if isinstance(person.get("death"), dict) else {}).get("date"))
    if birth is None:
        birth = _coerce_int(node.get("birth_year"))
    if death is None:
        death = _coerce_int(node.get("death_year"))
    if use_heuristics:
        if birth is None:
            birth = _coerce_int(node.get("time_year"))
        if death is None and birth is not None:
            life_raw = str(person.get("lifespan") or "").strip()
            life_years = _coerce_int(life_raw)
            if life_years and 0 < life_years < 130:
                death = birth + life_years
    return _normalize_year_order(birth, death)


def _pick_display_year_range(person: Dict[str, Any], node: Optional[Dict[str, Any]] = None) -> Tuple[Optional[int], Optional[int]]:
    return _pick_year_range(person, node, use_heuristics=False)


def _normalize_year_order(birth: Optional[int], death: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    if birth is None or death is None:
        return birth, death
    # For BCE years, earlier means "more negative".
    if birth < 0 and death < 0 and birth >= death:
        return min(birth, death), max(birth, death)
    if birth >= 0 and death >= 0 and birth > death:
        return min(birth, death), max(birth, death)
    return birth, death


_INVALID_GRAPH_LOGGER = logging.getLogger(__name__)

def _is_invalid_graph_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if text in {"{", "}", "summary"}:
        return True
    if re.fullmatch(r"[-_*:\s]+", text):
        _INVALID_GRAPH_LOGGER.debug("invalid_graph_text_rejected pattern_match=%r", text[:80])
        return True
    if text.startswith("- **") or text.startswith("### "):
        _INVALID_GRAPH_LOGGER.debug("invalid_graph_text_rejected markdown_fragment=%r", text[:80])
        return True
    return False


def _choose_graph_text(primary: Any, fallback: Any = "") -> str:
    if not _is_invalid_graph_text(primary):
        return str(primary or "").strip()
    if not _is_invalid_graph_text(fallback):
        return str(fallback or "").strip()
    return ""


def _collect_node_aliases(node: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    alias_noise = re.compile(r"存疑|待考|说法不一|史料|一说|本名|原名|今译|误作|未详")

    def push(value: Any, *, primary: bool = False) -> None:
        raw = str(value or "").strip()
        if not raw:
            return
        norm = _normalize_person_token(raw)
        if len(norm) < 2 or norm in seen:
            return
        if alias_noise.search(norm):
            return
        if not primary and len(norm) < 3:
            return
        seen.add(norm)
        out.append(raw)

    push(node.get("person"), primary=True)
    for item in node.get("aliases") or []:
        push(item)
    return out


def _guess_relation_label(context: str) -> str:
    text = str(context or "")
    if re.search(r"禅位|禅让|受禅|代汉", text):
        return "禅让"
    if re.search(r"父亲|母亲|兄长|弟弟|姐姐|妹妹|儿子|女儿|宗亲|皇叔|叔父|叔侄|兄弟|姐妹", text):
        return "宗亲"
    if re.search(r"师从|师事|老师|导师|弟子|门生|从学", text):
        return "师生"
    if re.search(r"好友|友人|朋友|结交|交游|唱和|酬答|相会", text):
        return "好友"
    if re.search(r"并称|齐名", text):
        return "并称"
    if re.search(r"政敌|对手|征讨|讨伐|反对|攻打|兵败|作乱", text):
        return "对手"
    if re.search(r"拥立|废.*立|立.*为帝|挟天子|奉天子|迎.*至|迎.*都|控制|挟持|辅佐|主公|君臣|幕僚|部下|麾下|丞相", text):
        return "君臣"
    return "人物关联"


def _extract_markdown_relation_candidates(
    markdown: str,
    alias_to_idx: Dict[str, int],
    nodes: List[Dict[str, Any]],
    current_aliases: List[str],
) -> List[Tuple[float, str, Dict[str, Any], Optional[float]]]:
    text = str(markdown or "")
    if not text:
        return []

    current_set = {_normalize_person_token(x) for x in current_aliases if _normalize_person_token(x)}
    hits: Dict[int, Dict[str, Any]] = {}
    alias_items = sorted(alias_to_idx.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, idx in alias_items:
        norm_alias = _normalize_person_token(alias)
        if not norm_alias or norm_alias in current_set:
            continue
        start = 0
        while True:
            pos = text.find(alias, start)
            if pos < 0:
                break
            start = pos + len(alias)
            prefix = text[max(0, pos - 8):pos]
            suffix = text[pos + len(alias):min(len(text), pos + len(alias) + 12)]
            lo = max(0, pos - 10)
            hi = min(len(text), pos + len(alias) + 10)
            context = text[lo:hi]
            item = hits.get(idx)
            label = "人物关联"
            suppress_sentence = False
            if re.search(r"禅位于|禅让给|受禅于", prefix) or re.search(r"^(受禅|代汉|继位)", suffix):
                label = "禅让"
            elif "去世后" in suffix and "禅位" in suffix:
                suppress_sentence = True
            elif re.search(r"关系密切|联系紧密|交往密切|往来密切|来往密切", prefix + suffix + context):
                label = "相关人物"
            elif re.search(r"政敌|对手|征讨|讨伐|反对|攻打|兵败|作乱", prefix + suffix + context):
                label = "对手"
            elif re.search(r"迎.*至|迎.*都|挟持|控制|辅佐|拥立|废.*立|立.*为帝|奉天子|挟天子", prefix + suffix):
                label = "君臣"
            else:
                label = _guess_relation_label(context)
            used_sentence = False
            if label == "人物关联" and not suppress_sentence:
                left = max(text.rfind("。", 0, pos), text.rfind("\n", 0, pos), text.rfind("！", 0, pos), text.rfind("？", 0, pos))
                right_candidates = [x for x in [text.find("。", pos), text.find("\n", pos), text.find("！", pos), text.find("？", pos)] if x >= 0]
                right = min(right_candidates) if right_candidates else len(text)
                sentence = text[(left + 1) if left >= 0 else 0:right]
                label = _guess_relation_label(sentence)
                used_sentence = label != "人物关联"
            if label == "人物关联":
                continue
            score = 88.0
            if label == "禅让":
                score = 99.0
            elif label == "君臣":
                score = 97.0
            elif label == "宗亲":
                score = 96.0
            elif label == "师生":
                score = 95.0
            elif label == "好友":
                score = 94.0
            elif label == "并称":
                score = 93.0
            elif label == "对手":
                score = 92.0
            if used_sentence:
                score = min(score, 91.0)
            if item is None or score > float(item.get("score") or 0):
                hits[idx] = {"score": score, "label": label}
    out: List[Tuple[float, str, Dict[str, Any], Optional[float]]] = []
    for idx, meta in hits.items():
        if 0 <= idx < len(nodes):
            out.append((float(meta["score"]), str(meta["label"]), nodes[idx], None))
    out.sort(key=lambda item: (item[0], str(item[2].get("person") or "")), reverse=True)
    return out


def _special_relation_candidates(
    *,
    person_name: str,
    nodes: List[Dict[str, Any]],
) -> List[Tuple[float, str, Dict[str, Any], Optional[float]]]:
    canonical = canonical_person_name(person_name) or str(person_name or "").strip()
    if canonical != "刘禅":
        return []

    preferred = {
        "刘备": ("父子", 103.0),
        "诸葛亮": ("托孤辅政", 102.0),
        "姜维": ("后期主战", 101.0),
    }
    out: List[Tuple[float, str, Dict[str, Any], Optional[float]]] = []
    seen = set()
    for node in nodes:
        name = str(node.get("person") or "").strip()
        if not name or name not in preferred or name in seen:
            continue
        label, score = preferred[name]
        out.append((score, label, node, 0.98))
        seen.add(name)
    out.sort(key=lambda item: (item[0], str(item[2].get("person") or "")), reverse=True)
    return out



def get_related_people_graph(
    person: Dict[str, Any],
    *,
    markdown: str = "",
    limit: int = 6,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    if not neo4j_enabled(backend):
        return {}
    config = neo4j_config()
    driver = _driver()
    if config is None or driver is None:
        return {}

    person_name = str(person.get("name") or "").strip()
    if not person_name:
        return {}
    title_match = re.search(r"^\s*#\s+([^\n#]+)", str(markdown or ""), flags=re.MULTILINE)
    display_name = str(title_match.group(1) or "").strip() if title_match else ""
    if not display_name:
        display_name = person_name
    candidate_names: List[str] = []
    for raw in [person_name, display_name, person.get("title"), person.get("alias")]:
        text = str(raw or "").strip()
        if text and text not in candidate_names:
            candidate_names.append(text)

    try:
        with driver.session(database=config.database) as session:
            center_rows = list(
                session.run(
                """
                MATCH (p:StoryMap:Person)
                OPTIONAL MATCH (p)-[:BELONGS_TO_DYNASTY]->(dyn:StoryMap:Dynasty)
                OPTIONAL MATCH (p)-[:HAS_DOMAIN]->(domain:StoryMap:Domain)
                WITH p, dyn, collect(DISTINCT domain.name) AS domain_tags
                WHERE p.name IN $candidates OR any(alias IN coalesce(p.aliases, []) WHERE alias IN $candidates)
                RETURN
                  p.id AS id,
                  p.name AS person,
                  p.file AS file,
                  coalesce(dyn.name, p.dynasty, '') AS dynasty,
                  p.birth_year AS birth_year,
                  p.death_year AS death_year,
                  p.quote AS quote,
                  p.review AS review,
                  p.aliases AS aliases,
                  p.foreign_name AS foreign_name,
                  domain_tags AS domain_tags,
                  p.main_role_label AS main_role_label,
                  p.birthplace AS birthplace,
                  p.birthplace_modern AS birthplace_modern,
                  p.has_story AS has_story
                ORDER BY CASE WHEN p.name = $person_name THEN 0 WHEN p.name = $display_name THEN 1 ELSE 2 END, p.name
                LIMIT 1
                """,
                candidates=candidate_names,
                person_name=person_name,
                display_name=display_name,
            )
            )
            if not center_rows:
                return {}
            center_row = {key: center_rows[0].get(key) for key in center_rows[0].keys()}
            center_id = str(center_row.get("id") or "").strip()
            if not center_id:
                return {}
            neighbor_rows = list(
                session.run(
                """
                MATCH (p:StoryMap:Person {id: $person_id})-[r:RELATED_TO]-(n:StoryMap:Person)
                OPTIONAL MATCH (n)-[:BELONGS_TO_DYNASTY]->(dyn:StoryMap:Dynasty)
                OPTIONAL MATCH (n)-[:HAS_DOMAIN]->(domain:StoryMap:Domain)
                WITH n, dyn, r, collect(DISTINCT domain.name) AS domain_tags
                RETURN
                  n.id AS id,
                  n.name AS person,
                  n.file AS file,
                  coalesce(dyn.name, n.dynasty, '') AS dynasty,
                  n.birth_year AS birth_year,
                  n.death_year AS death_year,
                  n.quote AS quote,
                  n.review AS review,
                  n.aliases AS aliases,
                  n.foreign_name AS foreign_name,
                  domain_tags AS domain_tags,
                  n.main_role_label AS main_role_label,
                  n.birthplace AS birthplace,
                  n.birthplace_modern AS birthplace_modern,
                  n.has_story AS has_story,
                  r.label AS relation_label,
                  r.relation_type AS relation_type,
                  r.confidence AS confidence
                ORDER BY coalesce(r.weight, 0) DESC, coalesce(r.confidence, 0) DESC, n.name
                LIMIT $limit
                """,
                person_id=center_id,
                limit=max(1, int(limit)),
                )
            )
    except Exception as exc:
        _LOGGER.warning("Neo4j graph query failed for %r: %s", display_name, exc)
        return {}

    center = _coerce_graph_person_row(center_row, override_name=display_name)
    center["relationLabel"] = "中心人物"
    center["isCenter"] = True
    center_dynasty = str(center.get("dynasty") or "").strip()

    nodes: List[Dict[str, Any]] = [center]
    links: List[Dict[str, Any]] = []
    seen_neighbor_tokens = {_normalize_person_token(display_name), _normalize_person_token(person_name)}
    for row_obj in neighbor_rows:
        row = {key: row_obj.get(key) for key in row_obj.keys()}
        node = _coerce_graph_person_row(row)
        norm = _normalize_person_token(node.get("name"))
        if not norm or norm in seen_neighbor_tokens:
            continue
        seen_neighbor_tokens.add(norm)
        raw_label = str(row.get("relation_label") or "相关人物").strip() or "相关人物"
        neighbor_dynasty = str(node.get("dynasty") or "").strip()
        node["relationLabel"] = _sanitize_relation_label(raw_label, center_dynasty, neighbor_dynasty)
        node["sourceType"] = str(row.get("relation_type") or "graph").strip() or "graph"
        node["confidence"] = _coerce_float(row.get("confidence"))
        node["isCenter"] = False
        nodes.append(node)
        links.append(
            {
                "source": display_name,
                "target": node["name"],
                "label": node["relationLabel"],
                "confidence": node.get("confidence"),
            }
        )
    return {"center": center, "nodes": nodes, "links": links}


def get_related_people_graph_from_payload(
    person: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    markdown: str = "",
    limit: int = 6,
) -> Dict[str, Any]:
    person_name = str(person.get("name") or "").strip()
    if not person_name:
        return {"center": {}, "nodes": [], "links": []}

    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    display_name = _extract_markdown_title(markdown) or person_name
    current_aliases = [x for x in [person_name, display_name] if str(x or "").strip()]

    nodes: List[Dict[str, Any]] = []
    raw_idx_to_idx: Dict[int, int] = {}
    person_to_idx: Dict[str, int] = {}
    alias_to_idx: Dict[str, int] = {}
    normalized_alias_to_idx: Dict[str, int] = {}
    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["_idx"] = idx
        compact_idx = len(nodes)
        raw_idx_to_idx[idx] = compact_idx
        name = str(item.get("person") or "").strip()
        if name:
            person_to_idx[name] = compact_idx
        for alias in _collect_node_aliases(item):
            alias_to_idx.setdefault(alias, compact_idx)
            normalized = _normalize_person_token(alias)
            if normalized:
                normalized_alias_to_idx.setdefault(normalized, compact_idx)
        nodes.append(item)
    adjacency: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        try:
            a = int(raw.get("a"))
            b = int(raw.get("b"))
        except Exception:
            continue
        if a < 0 or b < 0 or a == b:
            continue
        a_idx = raw_idx_to_idx.get(a)
        b_idx = raw_idx_to_idx.get(b)
        if a_idx is None or b_idx is None or a_idx == b_idx:
            continue
        adjacency.setdefault(a_idx, []).append((b_idx, raw))
        adjacency.setdefault(b_idx, []).append((a_idx, raw))

    current_idx = None
    for alias in current_aliases:
        normalized = _normalize_person_token(alias)
        current_idx = normalized_alias_to_idx.get(normalized)
        if current_idx is None:
            current_idx = person_to_idx.get(str(alias).strip())
        if current_idx is not None:
            break
    if current_idx is None:
        current_idx = person_to_idx.get(person_name)
    if current_idx is None and display_name:
        current_idx = person_to_idx.get(display_name)
    current_node = nodes[current_idx] if current_idx is not None else {}
    current_dynasty = str(person.get("dynasty") or current_node.get("dynasty") or "").strip()
    current_birth, current_death = _pick_year_range(person, current_node)
    current_tags = {
        str(x).strip()
        for x in (current_node.get("domain_tags") if isinstance(current_node.get("domain_tags"), list) else [])
        if str(x).strip()
    }

    selected: List[Dict[str, Any]] = []
    seen_names = {person_name, display_name, str(current_node.get("person") or "").strip()}
    seen_canonical_names = {
        canonical
        for canonical in (canonical_person_name(name) for name in seen_names)
        if canonical
    }

    def add_candidate(node: Dict[str, Any], relation_label: str, score: float, source_type: str, confidence: Optional[float] = None) -> None:
        name = str(node.get("person") or "").strip()
        canonical_name = canonical_person_name(name)
        if not name or name in seen_names or (canonical_name and canonical_name in seen_canonical_names):
            return
        node_dynasty = str(node.get("dynasty") or "").strip()
        relation_label = _sanitize_relation_label(relation_label, current_dynasty, node_dynasty)
        file_name = str(node.get("file") or f"{name}.html").strip()
        aliases = [x for x in _collect_node_aliases(node) if str(x or "").strip() and str(x).strip() != name][:4]
        selected.append(
            {
                "id": name,
                "name": name,
                "file": file_name,
                "dynasty": str(node.get("dynasty") or "").strip(),
                "aliases": aliases,
                "birth_year": _coerce_int(node.get("birth_year")),
                "death_year": _coerce_int(node.get("death_year")),
                "quote": str(node.get("quote") or "").strip(),
                "review": str(node.get("review") or "").strip(),
                "foreign_name": str(node.get("foreign_name") or "").strip(),
                "main_role_label": str(node.get("main_role_label") or "").strip(),
                "birthplace": str(node.get("birthplace") or "").strip(),
                "birthplace_modern": str(node.get("birthplace_modern") or "").strip(),
                "domain_tags": [str(x).strip() for x in (node.get("domain_tags") if isinstance(node.get("domain_tags"), list) else []) if str(x).strip()][:4],
                "has_story": bool(node.get("has_story", True)),
                "relationLabel": str(relation_label or "相关人物").strip() or "相关人物",
                "sourceType": source_type,
                "confidence": round(float(confidence), 2) if confidence is not None else None,
                "_score": float(score),
            }
        )
        seen_names.add(name)
        if canonical_name:
            seen_canonical_names.add(canonical_name)

    if current_idx is not None:
        explicit_edges = sorted(
            adjacency.get(current_idx, []),
            key=lambda item: (
                float(item[1].get("confidence") or 0),
                float(item[1].get("weight") or 0),
                str(nodes[item[0]].get("person") or ""),
            ),
            reverse=True,
        )
        for other_idx, edge in explicit_edges:
            other = nodes[other_idx]
            label = str(edge.get("label") or "相关人物").strip() or "相关人物"
            edge_type = str(edge.get("type") or "graph").strip()
            try:
                confidence = float(edge.get("confidence"))
            except Exception:
                confidence = None
            if edge_type == "same_book":
                continue
            base_score = 100.0
            if edge_type == "manual":
                base_score = 104.0
            score = base_score + (confidence or 0.0) * 10.0
            try:
                score += float(edge.get("weight") or 0)
            except Exception:
                pass
            add_candidate(other, label, score, edge_type, confidence)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        for score, label, node, confidence in _special_relation_candidates(
            person_name=display_name or person_name,
            nodes=nodes,
        ):
            add_candidate(node, label, score, "special", confidence)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        for score, label, node, confidence in _extract_markdown_relation_candidates(markdown, alias_to_idx, nodes, current_aliases):
            add_candidate(node, label, score, "markdown", confidence)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        fallback: List[Tuple[float, str, Dict[str, Any], Optional[float]]] = []
        for node in nodes:
            name = str(node.get("person") or "").strip()
            if not name or name in seen_names:
                continue
            score = 0.0
            same_dynasty = _same_dynasty(current_dynasty, node.get("dynasty"))
            cand_tags = {
                str(x).strip()
                for x in (node.get("domain_tags") if isinstance(node.get("domain_tags"), list) else [])
                if str(x).strip()
            }
            shared_tags = current_tags & cand_tags
            cand_birth = _coerce_int(node.get("birth_year")) or _coerce_int(node.get("time_year"))
            cand_death = _coerce_int(node.get("death_year"))
            overlap = False
            if current_birth is not None and current_death is not None and cand_birth is not None and cand_death is not None:
                overlap = max(current_birth, cand_birth) <= min(current_death, cand_death)
            if same_dynasty:
                score += 60.0
            if overlap:
                score += 24.0
            elif current_birth is not None and cand_birth is not None:
                diff = abs(current_birth - cand_birth)
                if diff <= 30:
                    score += 18.0
                elif diff <= 80:
                    score += 10.0
                elif diff <= 160:
                    score += 4.0
            if shared_tags:
                score += 10.0 + min(12.0, 4.0 * len(shared_tags))
            if score <= 0:
                continue
            if same_dynasty and shared_tags:
                label = "同朝同领域"
            elif same_dynasty:
                label = "同时代人物"
            elif shared_tags:
                label = "同领域人物"
            elif overlap:
                label = "同时代人物"
            else:
                label = "相关人物"
            fallback.append((score, label, node, None))
        fallback.sort(key=lambda item: (item[0], str(item[2].get("person") or "")), reverse=True)
        for score, label, node, confidence in fallback:
            add_candidate(node, label, score, "fallback", confidence)
            if len(selected) >= limit:
                break

    selected = sorted(selected, key=lambda item: item.get("_score", 0), reverse=True)[:limit]
    for item in selected:
        item.pop("_score", None)

    center_file = str(current_node.get("file") or f"{display_name}.html").strip()
    center_birth, center_death = _pick_display_year_range(person, current_node)
    center = {
        "id": display_name,
        "name": display_name,
        "file": center_file,
        "dynasty": current_dynasty,
        "aliases": [x for x in _collect_node_aliases(current_node) if str(x or "").strip() and str(x).strip() != display_name][:4],
        "birth_year": center_birth,
        "death_year": center_death,
        "quote": _choose_graph_text(current_node.get("quote"), person.get("quote")),
        "review": _choose_graph_text(current_node.get("review"), person.get("shortReview")),
        "foreign_name": str(current_node.get("foreign_name") or "").strip(),
        "main_role_label": str(current_node.get("main_role_label") or person.get("title") or "").strip(),
        "birthplace": _choose_graph_text(current_node.get("birthplace"), person.get("birthplace")),
        "birthplace_modern": _choose_graph_text(current_node.get("birthplace_modern")),
        "domain_tags": [str(x).strip() for x in (current_node.get("domain_tags") if isinstance(current_node.get("domain_tags"), list) else []) if str(x).strip()][:4],
        "has_story": bool(current_node.get("has_story", True)),
        "relationLabel": "中心人物",
        "isCenter": True,
    }
    links = [
        {
            "source": display_name,
            "target": item["name"],
            "label": item.get("relationLabel") or "相关人物",
            "confidence": item.get("confidence"),
        }
        for item in selected
    ]
    nodes_out = [center] + [{**item, "isCenter": False} for item in selected]
    return {"center": center, "nodes": nodes_out, "links": links}


# ── 关系标签清洗 ──────────────────────────────────────────────

_MODERN_DYNASTY_PATTERNS = [
    "近现代", "现当代", "中华人民共和国", "中华民国",
    "清末至中华人民共和国", "抗日战争时期", "中国现当代",
    "中国近现代", "近现代中国", "清末民初", "中国近代",
]

_FEUDAL_ONLY_LABELS = {"君臣"}

_MODERN_REMAP = {
    "君臣": "工作关系",
}


def _is_modern_dynasty(dynasty: str) -> bool:
    """判断一个朝代是否属于近现代（不应使用封建关系标签）。"""
    if not dynasty:
        return False
    return any(p in str(dynasty) for p in _MODERN_DYNASTY_PATTERNS)


def _sanitize_relation_label(
    label: str,
    source_dynasty: str = "",
    target_dynasty: str = "",
) -> str:
    """清洗关系标签：近现代人物不应使用'君臣'等封建术语。"""
    if label not in _FEUDAL_ONLY_LABELS:
        return label
    if _is_modern_dynasty(source_dynasty) or _is_modern_dynasty(target_dynasty):
        return _MODERN_REMAP.get(label, "工作关系")
    return label


# ── SQLite backend ──────────────────────────────────────────────

_KNOWLEDGE_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "people_knowledge.db"


def _graph_db_path() -> Path:
    custom = os.getenv("MAP_STORY_GRAPH_DB_PATH", "").strip()
    return Path(custom) if custom else _KNOWLEDGE_DB_PATH


def _graph_db_connect(readonly: bool = True) -> _sqlite3.Connection:
    db_path = _graph_db_path()
    uri = f"file:{db_path}?mode=ro" if readonly else str(db_path)
    conn = _sqlite3.connect(uri, uri=readonly)
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_related_people_graph_from_sqlite(
    person_name: str,
    *,
    limit: int = 6,
) -> Dict[str, Any]:
    """从 SQLite 查询人物关系图谱（当前人物 + 关联邻居）。"""
    name = str(person_name or "").strip()
    if not name:
        return {"center": {}, "nodes": [], "links": []}

    try:
        conn = _graph_db_connect(readonly=True)
    except Exception as exc:
        _LOGGER.warning("SQLite graph DB connect failed: %s", exc)
        return {"center": {}, "nodes": [], "links": []}

    try:
        center_row = conn.execute(
            "SELECT * FROM people WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        if not center_row:
            return {"center": {}, "nodes": [], "links": []}

        center = _dict_row(center_row)
        center["isCenter"] = True
        center["relationLabel"] = "中心人物"

        neighbors = conn.execute(
            """
            SELECT DISTINCT p.*, r.relationship AS relation_label, r.origin,
                   r.weight AS relation_weight, r.confidence AS relation_confidence,
                   r.evidence AS relation_evidence
            FROM relationships r
            JOIN people p ON (
                (r.source_person = ? AND p.name = r.target_person)
                OR (r.target_person = ? AND p.name = r.source_person)
            )
            WHERE p.name != ?
            ORDER BY r.weight DESC, r.confidence DESC, p.name
            LIMIT ?
            """,
            (name, name, name, max(1, int(limit))),
        ).fetchall()

        center_dynasty = str(center.get("dynasty") or "").strip()
        nodes: List[Dict[str, Any]] = [center]
        links: List[Dict[str, Any]] = []
        for row in neighbors:
            node = _dict_row(row)
            raw_label = str(row["relation_label"] or "相关人物").strip() or "相关人物"
            neighbor_dynasty = str(node.get("dynasty") or "").strip()
            node["relationLabel"] = _sanitize_relation_label(raw_label, center_dynasty, neighbor_dynasty)
            node["sourceType"] = str(row["origin"] or "manual").strip()
            node["confidence"] = row["relation_confidence"]
            node["isCenter"] = False
            nodes.append(node)
            links.append({
                "source": name,
                "target": node["name"],
                "label": node["relationLabel"],
                "confidence": node.get("confidence"),
            })

        return {"center": center, "nodes": nodes, "links": links}
    finally:
        conn.close()


def list_all_relations(conn: _sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
    """列出所有关系边（需要 writable connection）。"""
    close_conn = False
    if conn is None:
        conn = _graph_db_connect(readonly=False)
        close_conn = True
    try:
        rows = conn.execute(
            "SELECT * FROM relationships ORDER BY weight DESC, source_person"
        ).fetchall()
        return [_dict_row(r) for r in rows]
    finally:
        if close_conn:
            conn.close()


def search_people(query: str, conn: _sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
    """全文搜索人物。"""
    close_conn = False
    if conn is None:
        conn = _graph_db_connect(readonly=False)
        close_conn = True
    try:
        rows = conn.execute(
            """
            SELECT p.* FROM people p
            JOIN people_fts fts ON p.id = fts.rowid
            WHERE people_fts MATCH ?
            ORDER BY rank
            LIMIT 20
            """,
            (query,),
        ).fetchall()
        return [_dict_row(r) for r in rows]
    except Exception:
        # FTS may fail on empty/special queries; fall back to LIKE
        rows = conn.execute(
            "SELECT * FROM people WHERE name LIKE ? OR aliases LIKE ? LIMIT 20",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [_dict_row(r) for r in rows]
    finally:
        if close_conn:
            conn.close()


def _dict_row(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    # 把 JSON 字符串字段还原为列表
    for key in ("aliases", "domain_tags", "search_keys", "search_tokens", "search_pinyin"):
        if key in d:
            try:
                val = json.loads(d[key]) if isinstance(d[key], str) else d[key]
                d[key] = val if isinstance(val, list) else []
            except Exception:
                d[key] = []
    return d

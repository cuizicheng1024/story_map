"""图谱数据访问层 — Neo4j / JSON / SQLite 存储与加载。

从 graph_service.py 拆分而来，避免单个文件混合存储与关系匹配逻辑。
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    GraphDatabase = None

from ..core.env_utils import _first_env, apply_story_map_env_aliases, env_flag
from ..core.project_paths import data_corpus_file_path, project_root_path, story_artifacts_dir_path

apply_story_map_env_aliases()

_REPO_ROOT = project_root_path()
_DEFAULT_HOME_DATA_JSON = story_artifacts_dir_path() / "stellar_home_data.json"
_PEOPLE_MASTER_JSON = data_corpus_file_path("people_master.json")
_KNOWLEDGE_GRAPH_JSON = data_corpus_file_path("people_knowledge_graph.json")


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str


def graph_backend_name(preferred: Optional[str] = None) -> str:
    backend = str(preferred or "").strip().lower()
    if backend:
        return backend
    backend = _first_env("MAP_STORY_GRAPH_BACKEND", "STORY_MAP_GRAPH_BACKEND").strip().lower()
    return backend or "file"


def neo4j_config() -> Optional[Neo4jConfig]:
    uri = _first_env("MAP_STORY_NEO4J_URI", "NEO4J_URI")
    user = _first_env("MAP_STORY_NEO4J_USER", "NEO4J_USERNAME", "NEO4J_USER")
    password = _first_env("MAP_STORY_NEO4J_PASSWORD", "NEO4J_PASSWORD")
    if not uri or not user or not password:
        return None
    database = _first_env("MAP_STORY_NEO4J_DATABASE", "NEO4J_DATABASE") or "neo4j"
    return Neo4jConfig(uri=uri, user=user, password=password, database=database)


def neo4j_enabled(preferred_backend: Optional[str] = None) -> bool:
    return graph_backend_name(preferred_backend) == "neo4j" and neo4j_config() is not None


def should_sync_to_neo4j() -> bool:
    return neo4j_enabled() or env_flag("MAP_STORY_NEO4J_SYNC", "STORY_MAP_NEO4J_SYNC")


@lru_cache(maxsize=1)
def _driver() -> Any:
    config = neo4j_config()
    if config is None or GraphDatabase is None:
        return None
    return GraphDatabase.driver(config.uri, auth=(config.user, config.password))


def close_graph_driver() -> None:
    try:
        driver = _driver()
        if driver is not None:
            driver.close()
    except Exception as exc:
        _LOGGER.warning("Failed to close Neo4j graph driver: %s", exc)
    _driver.cache_clear()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _build_home_graph_file_fallback() -> Dict[str, Any]:
    master = _read_json(_PEOPLE_MASTER_JSON)
    people = master.get("people") if isinstance(master.get("people"), list) else []
    nodes: List[Dict[str, Any]] = []
    person_to_idx: Dict[str, int] = {}
    for item in people:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("has_story")):
            continue
        name = str(item.get("person") or "").strip()
        if not name or name in person_to_idx:
            continue
        person_to_idx[name] = len(nodes)
        nodes.append(
            {
                "person": name,
                "file": f"{name}.html",
                "dynasty": str(item.get("dynasty") or "").strip(),
                "birth_year": item.get("birth_year"),
                "death_year": item.get("death_year"),
                "aliases": [],
                "domain_tags": [],
            }
        )

    raw_graph = _read_json(_KNOWLEDGE_GRAPH_JSON)
    raw_edges = raw_graph.get("edges") if isinstance(raw_graph.get("edges"), list) else []
    edges: List[Dict[str, Any]] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        a = person_to_idx.get(source)
        b = person_to_idx.get(target)
        if a is None or b is None:
            continue
        edge_type = str(item.get("type") or "").strip().lower()
        try:
            weight = int(item.get("weight") or 0)
        except Exception:
            weight = 0
        if edge_type != "manual" or weight < 2:
            continue
        label = "人工关系"
        confidence = 0.9
        edges.append(
            {
                "a": a,
                "b": b,
                "type": edge_type,
                "label": label,
                "confidence": confidence,
                "weight": weight,
            }
        )
    return {"nodes": nodes, "edges": edges}


def build_home_graph_file_fallback() -> Dict[str, Any]:
    return _build_home_graph_file_fallback()


def invalidate_graph_service_cache() -> None:
    _build_home_graph_file_fallback.cache_clear()
    close_graph_driver()


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        text = str(value).strip()
        if re.search(r"(?:公元前|前)\s*\d{1,4}", text):
            match = re.search(r"(?:公元前|前)\s*(\d{1,4})", text)
            if match:
                return -int(match.group(1))
        match = re.search(r"-?\d{1,4}", text)
        if match:
            return int(match.group(0))
        return int(text)
    except Exception:
        return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).strip())
    except Exception:
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _string_list(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _json_property(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""


def _decode_json_property(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None



def normalize_graph_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    people: List[Dict[str, Any]] = []
    dynasties: Dict[str, Dict[str, str]] = {}
    domains: Dict[str, Dict[str, str]] = {}
    person_domains: List[Dict[str, str]] = []
    relationships: List[Dict[str, Any]] = []
    idx_to_person_id: Dict[int, str] = {}

    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("person") or "").strip()
        if not name:
            continue
        person_id = _person_id(raw)
        idx_to_person_id[idx] = person_id
        dynasty = str(raw.get("dynasty") or "").strip()
        domain_tags = _string_list(raw.get("domain_tags"))
        people.append(
            {
                "id": person_id,
                "name": name,
                "file": str(raw.get("file") or f"{name}.html").strip(),
                "dynasty": dynasty,
                "birth_year": _coerce_int(raw.get("birth_year")),
                "death_year": _coerce_int(raw.get("death_year")),
                "time_year": _coerce_int(raw.get("time_year")),
                "quote": str(raw.get("quote") or "").strip(),
                "review": str(raw.get("review") or "").strip(),
                "aliases": _string_list(raw.get("aliases")),
                "foreign_name": str(raw.get("foreign_name") or "").strip(),
                "domain_tags": domain_tags,
                "main_role_band": str(raw.get("main_role_band") or "").strip(),
                "main_role_label": str(raw.get("main_role_label") or "").strip(),
                "risk_level": str(raw.get("risk_level") or "").strip(),
                "audit_pass": _coerce_bool(raw.get("audit_pass")),
                "audit_uncertain_json": _json_property(raw.get("audit_uncertain")),
                "birthplace": str(raw.get("birthplace") or "").strip(),
                "birthplace_raw": str(raw.get("birthplace_raw") or "").strip(),
                "birthplace_modern": str(raw.get("birthplace_modern") or "").strip(),
                "birth_lat_wgs84": _coerce_float(raw.get("birth_lat_wgs84")),
                "birth_lng_wgs84": _coerce_float(raw.get("birth_lng_wgs84")),
                "birth_lat": _coerce_float(raw.get("birth_lat")),
                "birth_lng": _coerce_float(raw.get("birth_lng")),
                "birth_coord_system": str(raw.get("birth_coord_system") or "").strip(),
                "relations": _string_list(raw.get("relations")),
                "relations_meta_json": _json_property(raw.get("relations_meta")),
                "search_keys": _string_list(raw.get("search_keys")),
                "search_tokens": _string_list(raw.get("search_tokens")),
                "search_pinyin": _string_list(raw.get("search_pinyin")),
                "has_story": bool(raw.get("has_story", True)),
            }
        )
        if dynasty:
            dynasties.setdefault(_dynasty_id(dynasty), {"id": _dynasty_id(dynasty), "name": dynasty})
        for tag in domain_tags:
            domains.setdefault(_domain_id(tag), {"id": _domain_id(tag), "name": tag})
            person_domains.append({"person_id": person_id, "domain_id": _domain_id(tag)})

    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        try:
            a = int(raw.get("a"))
            b = int(raw.get("b"))
        except Exception:
            continue
        source_id = idx_to_person_id.get(a)
        target_id = idx_to_person_id.get(b)
        if not source_id or not target_id or source_id == target_id:
            continue
        source_name = next((item["name"] for item in people if item["id"] == source_id), "")
        target_name = next((item["name"] for item in people if item["id"] == target_id), "")
        pair = sorted([source_id, target_id])
        relation_type = str(raw.get("type") or "graph").strip().lower() or "graph"
        relationships.append(
            {
                "source_id": pair[0],
                "target_id": pair[1],
                "source_name": source_name if source_id == pair[0] else target_name,
                "target_name": target_name if target_id == pair[1] else source_name,
                "relation_type": relation_type,
                "label": str(raw.get("label") or "相关人物").strip() or "相关人物",
                "confidence": _coerce_float(raw.get("confidence")),
                "weight": _coerce_int(raw.get("weight")),
            }
        )

    return {
        "people": people,
        "dynasties": list(dynasties.values()),
        "domains": list(domains.values()),
        "person_domains": person_domains,
        "relationships": relationships,
    }


def write_normalized_graph_json(payload: Dict[str, Any], output_path: Path) -> Path:
    normalized = normalize_graph_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def sync_graph_payload_to_neo4j(payload: Dict[str, Any], *, replace: bool = True) -> bool:
    config = neo4j_config()
    driver = _driver()
    if config is None or driver is None:
        return False

    normalized = normalize_graph_payload(payload)
    people = normalized["people"]
    dynasties = normalized["dynasties"]
    domains = normalized["domains"]
    person_domains = normalized["person_domains"]
    relationships = normalized["relationships"]

    with driver.session(database=config.database) as session:
        if replace:
            session.run("MATCH (n:StoryMap) DETACH DELETE n")
        session.run("CREATE CONSTRAINT storymap_person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE")
        session.run("CREATE CONSTRAINT storymap_dynasty_id IF NOT EXISTS FOR (d:Dynasty) REQUIRE d.id IS UNIQUE")
        session.run("CREATE CONSTRAINT storymap_domain_id IF NOT EXISTS FOR (d:Domain) REQUIRE d.id IS UNIQUE")
        session.run(
            """
            UNWIND $rows AS row
            MERGE (p:StoryMap:Person {id: row.id})
            SET p += row
            """,
            rows=people,
        )
        session.run(
            """
            UNWIND $rows AS row
            MERGE (d:StoryMap:Dynasty {id: row.id})
            SET d.name = row.name
            """,
            rows=dynasties,
        )
        session.run(
            """
            UNWIND $rows AS row
            MERGE (d:StoryMap:Domain {id: row.id})
            SET d.name = row.name
            """,
            rows=domains,
        )
        session.run(
            """
            UNWIND $rows AS row
            MATCH (p:StoryMap:Person {id: row.person_id})
            MATCH (d:StoryMap:Dynasty {id: row.dynasty_id})
            MERGE (p)-[:BELONGS_TO_DYNASTY]->(d)
            """,
            rows=[{"person_id": item["id"], "dynasty_id": _dynasty_id(item["dynasty"])} for item in people if item.get("dynasty")],
        )
        session.run(
            """
            UNWIND $rows AS row
            MATCH (p:StoryMap:Person {id: row.person_id})
            MATCH (d:StoryMap:Domain {id: row.domain_id})
            MERGE (p)-[:HAS_DOMAIN]->(d)
            """,
            rows=person_domains,
        )
        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:StoryMap:Person {id: row.source_id})
            MATCH (b:StoryMap:Person {id: row.target_id})
            MERGE (a)-[r:RELATED_TO {
              source_id: row.source_id,
              target_id: row.target_id,
              relation_type: row.relation_type,
              label: row.label
            }]->(b)
            SET r.confidence = row.confidence,
                r.weight = row.weight,
                r.source_name = row.source_name,
                r.target_name = row.target_name
            """,
            rows=relationships,
        )
    return True


def _build_payload_from_neo4j(*, limit_nodes: int = 4000, limit_edges: int = 12000) -> Dict[str, Any]:
    config = neo4j_config()
    driver = _driver()
    if config is None or driver is None:
        return {}

    with driver.session(database=config.database) as session:
        node_rows = list(
            session.run(
                """
                MATCH (p:StoryMap:Person)
                OPTIONAL MATCH (p)-[:BELONGS_TO_DYNASTY]->(dyn:StoryMap:Dynasty)
                OPTIONAL MATCH (p)-[:HAS_DOMAIN]->(domain:StoryMap:Domain)
                WITH p, dyn, collect(DISTINCT domain.name) AS domain_tags
                RETURN
                  p.id AS id,
                  p.name AS person,
                  p.file AS file,
                  coalesce(dyn.name, p.dynasty, '') AS dynasty,
                  p.birth_year AS birth_year,
                  p.death_year AS death_year,
                  p.time_year AS time_year,
                  p.quote AS quote,
                  p.review AS review,
                  p.aliases AS aliases,
                  p.foreign_name AS foreign_name,
                  domain_tags AS domain_tags,
                  p.main_role_band AS main_role_band,
                  p.main_role_label AS main_role_label,
                  p.risk_level AS risk_level,
                  p.audit_pass AS audit_pass,
                  p.audit_uncertain_json AS audit_uncertain_json,
                  p.birthplace AS birthplace,
                  p.birthplace_raw AS birthplace_raw,
                  p.birthplace_modern AS birthplace_modern,
                  p.birth_lat_wgs84 AS birth_lat_wgs84,
                  p.birth_lng_wgs84 AS birth_lng_wgs84,
                  p.birth_lat AS birth_lat,
                  p.birth_lng AS birth_lng,
                  p.birth_coord_system AS birth_coord_system,
                  p.relations AS relations,
                  p.relations_meta_json AS relations_meta_json,
                  p.search_keys AS search_keys,
                  p.search_tokens AS search_tokens,
                  p.search_pinyin AS search_pinyin,
                  p.has_story AS has_story
                ORDER BY p.name
                LIMIT $limit
                """,
                limit=max(1, limit_nodes),
            )
        )
        nodes: List[Dict[str, Any]] = []
        id_to_idx: Dict[str, int] = {}
        for row in node_rows:
            node = {key: row.get(key) for key in row.keys()}
            person = str(node.get("person") or "").strip()
            if not person:
                continue
            node_id = str(node.pop("id") or "").strip()
            id_to_idx[node_id] = len(nodes)
            node["aliases"] = _string_list(node.get("aliases"))
            node["domain_tags"] = _string_list(node.get("domain_tags"))
            node["relations"] = _string_list(node.get("relations"))
            node["search_keys"] = _string_list(node.get("search_keys"))
            node["search_tokens"] = _string_list(node.get("search_tokens"))
            node["search_pinyin"] = _string_list(node.get("search_pinyin"))
            node["audit_pass"] = _coerce_bool(node.get("audit_pass"))
            node["audit_uncertain"] = _decode_json_property(node.get("audit_uncertain_json"))
            node["relations_meta"] = _decode_json_property(node.get("relations_meta_json")) or []
            node.pop("audit_uncertain_json", None)
            node.pop("relations_meta_json", None)
            nodes.append(node)

        edge_rows = list(
            session.run(
                """
                MATCH (a:StoryMap:Person)-[r:RELATED_TO]->(b:StoryMap:Person)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN
                  a.id AS source_id,
                  b.id AS target_id,
                  r.relation_type AS relation_type,
                  r.label AS label,
                  r.confidence AS confidence,
                  r.weight AS weight
                ORDER BY coalesce(r.weight, 0) DESC, coalesce(r.confidence, 0) DESC
                LIMIT $limit
                """,
                ids=list(id_to_idx.keys()),
                limit=max(1, limit_edges),
            )
        )

    edges: List[Dict[str, Any]] = []
    seen = set()
    for row in edge_rows:
        source_id = str(row.get("source_id") or "").strip()
        target_id = str(row.get("target_id") or "").strip()
        source_idx = id_to_idx.get(source_id)
        target_idx = id_to_idx.get(target_id)
        if source_idx is None or target_idx is None or source_idx == target_idx:
            continue
        a, b = (source_idx, target_idx) if source_idx < target_idx else (target_idx, source_idx)
        key = (
            a,
            b,
            str(row.get("relation_type") or "graph").strip().lower(),
            str(row.get("label") or "相关人物").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            {
                "a": a,
                "b": b,
                "type": key[2] or "graph",
                "label": key[3] or "相关人物",
                "confidence": _coerce_float(row.get("confidence")),
                "weight": _coerce_int(row.get("weight")),
            }
        )
    return {"nodes": nodes, "edges": edges, "kg_edges": []}


def load_home_graph_payload_with_source(
    home_data_path: Optional[Path] = None,
    *,
    backend: Optional[str] = None,
    strict_backend: bool = False,
) -> Tuple[Dict[str, Any], str]:
    if neo4j_enabled(backend):
        try:
            payload = _build_payload_from_neo4j()
        except Exception as exc:
            _LOGGER.warning("Neo4j payload build failed: %s", exc)
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list):
            return payload, "neo4j"
        if strict_backend:
            return {}, ""
    target = Path(home_data_path or _DEFAULT_HOME_DATA_JSON)
    payload = _read_json(target)
    if isinstance(payload, dict) and isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list):
        return payload, "file"
    return _build_home_graph_file_fallback(), "fallback"


def load_home_graph_payload(
    home_data_path: Optional[Path] = None,
    *,
    backend: Optional[str] = None,
    strict_backend: bool = False,
) -> Dict[str, Any]:
    payload, _source = load_home_graph_payload_with_source(
        home_data_path,
        backend=backend,
        strict_backend=strict_backend,
    )
    return payload


def home_graph_person_names(
    home_data_path: Optional[Path] = None,
    *,
    backend: Optional[str] = None,
    strict_backend: bool = False,
) -> List[str]:
    """返回首页图谱中全部人物的名字列表（如 523 个人物）。

    供聊天 @ 提及候选列表等需要全量人物名的场景使用。
    """
    payload = load_home_graph_payload(home_data_path, backend=backend, strict_backend=strict_backend)
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    if not isinstance(nodes, list):
        return []
    out: List[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        name = str(n.get("person") or n.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _coerce_graph_person_row(row: Dict[str, Any], *, override_name: Optional[str] = None) -> Dict[str, Any]:
    name = str(override_name or row.get("person") or row.get("name") or "").strip()
    aliases = [item for item in _string_list(row.get("aliases")) if item != name][:4]
    return {
        "id": name,
        "name": name,
        "file": str(row.get("file") or f"{name}.html").strip(),
        "dynasty": str(row.get("dynasty") or "").strip(),
        "aliases": aliases,
        "birth_year": _coerce_int(row.get("birth_year")),
        "death_year": _coerce_int(row.get("death_year")),
        "quote": str(row.get("quote") or "").strip(),
        "review": str(row.get("review") or "").strip(),
        "foreign_name": str(row.get("foreign_name") or "").strip(),
        "main_role_label": str(row.get("main_role_label") or "").strip(),
        "birthplace": str(row.get("birthplace") or "").strip(),
        "birthplace_modern": str(row.get("birthplace_modern") or "").strip(),
        "domain_tags": _string_list(row.get("domain_tags"))[:4],
        "has_story": bool(row.get("has_story", True)),
    }


def _person_id(node: Dict[str, Any]) -> str:
    name = str(node.get("person") or "").strip()
    if name:
        return f"person:{name}"
    fallback = str(node.get("file") or "").strip()
    return f"person:{fallback or 'unknown'}"


def _dynasty_id(name: str) -> str:
    return f"dynasty:{name}"


def _domain_id(name: str) -> str:
    return f"domain:{name}"




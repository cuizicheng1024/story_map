import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from neo4j import GraphDatabase  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    GraphDatabase = None

try:
    from .env_utils import apply_story_map_env_aliases, env_flag
    from .person_registry import canonical_person_name
    from .project_paths import project_root_path, story_artifacts_dir_path
except ImportError:
    from env_utils import apply_story_map_env_aliases, env_flag
    from person_registry import canonical_person_name
    from project_paths import project_root_path, story_artifacts_dir_path


apply_story_map_env_aliases()

_REPO_ROOT = project_root_path()
_DEFAULT_HOME_DATA_JSON = story_artifacts_dir_path() / "stellar_home_data.json"
_PEOPLE_MASTER_JSON = _REPO_ROOT / "data" / "people_master.json"
_KNOWLEDGE_GRAPH_JSON = _REPO_ROOT / "data" / "people_knowledge_graph.json"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


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
    except Exception:
        pass
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
        if edge_type not in {"manual", "same_book"} or weight < 2:
            continue
        if edge_type == "manual":
            label = "人工关系"
            confidence = 0.9
        else:
            label = "同册共现"
            confidence = max(0.15, min(0.60, 0.15 + 0.07 * max(0, weight - 2)))
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
        return int(str(value).strip())
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


def _pick_year_range(person: Dict[str, Any], node: Optional[Dict[str, Any]] = None) -> Tuple[Optional[int], Optional[int]]:
    node = node or {}
    birth = _coerce_int(((person.get("birth") or {}) if isinstance(person.get("birth"), dict) else {}).get("date"))
    death = _coerce_int(((person.get("death") or {}) if isinstance(person.get("death"), dict) else {}).get("date"))
    if birth is None:
        birth = _coerce_int(node.get("birth_year"))
    if death is None:
        death = _coerce_int(node.get("death_year"))
    if birth is None:
        birth = _coerce_int(node.get("time_year"))
    if death is None and birth is not None:
        life_raw = str(person.get("lifespan") or "").strip()
        life_years = _coerce_int(life_raw)
        if life_years and 0 < life_years < 130:
            death = birth + life_years
    return birth, death


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
    if re.search(r"拥立|废.*立|立.*为帝|挟天子|奉天子|迎.*至|迎.*都|控制|挟持|辅佐|主公|君臣|幕僚|部下|麾下|丞相", text):
        return "君臣"
    if re.search(r"政敌|对手|征讨|讨伐|反对|攻打|兵败|作乱", text):
        return "对手"
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
            elif re.search(r"迎|挟持|控制|辅佐|拥立|废|立|奉天子|挟天子", prefix + suffix):
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
        except Exception:
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
    except Exception:
        return {}

    center = _coerce_graph_person_row(center_row, override_name=display_name)
    center["relationLabel"] = "中心人物"
    center["isCenter"] = True

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
        node["relationLabel"] = str(row.get("relation_label") or "相关人物").strip() or "相关人物"
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
    available_person_names = [str(node.get("person") or "").strip() for node in nodes if str(node.get("person") or "").strip()]

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
        for canonical in (canonical_person_name(name, available_names=available_person_names) for name in seen_names)
        if canonical
    }

    def add_candidate(node: Dict[str, Any], relation_label: str, score: float, source_type: str, confidence: Optional[float] = None) -> None:
        name = str(node.get("person") or "").strip()
        canonical_name = canonical_person_name(name, available_names=available_person_names)
        if not name or name in seen_names or (canonical_name and canonical_name in seen_canonical_names):
            return
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

    deferred_same_book_edges: List[Tuple[int, Dict[str, Any]]] = []
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
                deferred_same_book_edges.append((other_idx, edge))
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
        for score, label, node, confidence in _extract_markdown_relation_candidates(markdown, alias_to_idx, nodes, current_aliases):
            add_candidate(node, label, score, "markdown", confidence)
            if len(selected) >= limit:
                break

    if current_idx is not None and len(selected) < limit:
        for other_idx, edge in deferred_same_book_edges:
            other = nodes[other_idx]
            label = str(edge.get("label") or "相关人物").strip() or "相关人物"
            try:
                confidence = float(edge.get("confidence"))
            except Exception:
                confidence = None
            score = 78.0 + (confidence or 0.0) * 10.0
            try:
                score += float(edge.get("weight") or 0)
            except Exception:
                pass
            add_candidate(other, label, score, "same_book", confidence)
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
    center = {
        "id": display_name,
        "name": display_name,
        "file": center_file,
        "dynasty": current_dynasty,
        "aliases": [x for x in _collect_node_aliases(current_node) if str(x or "").strip() and str(x).strip() != display_name][:4],
        "birth_year": current_birth,
        "death_year": current_death,
        "quote": str(current_node.get("quote") or person.get("quote") or "").strip(),
        "review": str(current_node.get("review") or person.get("shortReview") or "").strip(),
        "foreign_name": str(current_node.get("foreign_name") or "").strip(),
        "main_role_label": str(current_node.get("main_role_label") or person.get("title") or "").strip(),
        "birthplace": str(current_node.get("birthplace") or person.get("birthplace") or "").strip(),
        "birthplace_modern": str(current_node.get("birthplace_modern") or "").strip(),
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

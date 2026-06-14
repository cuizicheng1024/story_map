import json
from pathlib import Path

from storymap.script import graph_service


def test_normalize_graph_payload_emits_people_domains_and_relationships():
    payload = {
        "nodes": [
            {
                "person": "张骞",
                "file": "张骞.html",
                "dynasty": "西汉",
                "birth_year": -164,
                "death_year": -114,
                "aliases": ["博望侯"],
                "domain_tags": ["外交", "军事"],
                "main_role_label": "外交家",
            },
            {
                "person": "汉武帝",
                "file": "汉武帝.html",
                "dynasty": "西汉",
                "birth_year": -156,
                "death_year": -87,
                "domain_tags": ["政治"],
            },
        ],
        "edges": [
            {"a": 0, "b": 1, "type": "bio", "label": "君臣", "confidence": 0.88, "weight": 3},
        ],
    }

    normalized = graph_service.normalize_graph_payload(payload)

    assert {item["name"] for item in normalized["people"]} == {"张骞", "汉武帝"}
    assert {item["name"] for item in normalized["dynasties"]} == {"西汉"}
    assert {item["name"] for item in normalized["domains"]} == {"外交", "军事", "政治"}
    assert normalized["relationships"] == [
        {
            "source_id": "person:张骞",
            "target_id": "person:汉武帝",
            "source_name": "张骞",
            "target_name": "汉武帝",
            "relation_type": "bio",
            "label": "君臣",
            "confidence": 0.88,
            "weight": 3,
        }
    ]


def test_load_home_graph_payload_falls_back_to_json_file(tmp_path: Path, monkeypatch):
    data_path = tmp_path / "stellar_home_data.json"
    payload = {"nodes": [{"person": "张骞"}], "edges": []}
    data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(graph_service, "neo4j_enabled", lambda _backend=None: False)

    loaded = graph_service.load_home_graph_payload(data_path)

    assert loaded == payload


def test_load_home_graph_payload_strict_neo4j_does_not_silently_fallback(tmp_path: Path, monkeypatch):
    data_path = tmp_path / "stellar_home_data.json"
    fallback_payload = {"nodes": [{"person": "文件版张骞"}], "edges": []}
    data_path.write_text(json.dumps(fallback_payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(graph_service, "neo4j_enabled", lambda _backend=None: True)
    monkeypatch.setattr(graph_service, "_build_payload_from_neo4j", lambda: (_ for _ in ()).throw(RuntimeError("neo4j down")))

    loaded, source = graph_service.load_home_graph_payload_with_source(
        data_path,
        backend="neo4j",
        strict_backend=True,
    )

    assert loaded == {}
    assert source == ""


def test_load_home_graph_payload_non_strict_neo4j_can_fallback_to_json_file(tmp_path: Path, monkeypatch):
    data_path = tmp_path / "stellar_home_data.json"
    fallback_payload = {"nodes": [{"person": "文件版张骞"}], "edges": []}
    data_path.write_text(json.dumps(fallback_payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(graph_service, "neo4j_enabled", lambda _backend=None: True)
    monkeypatch.setattr(graph_service, "_build_payload_from_neo4j", lambda: (_ for _ in ()).throw(RuntimeError("neo4j down")))

    loaded, source = graph_service.load_home_graph_payload_with_source(
        data_path,
        backend="neo4j",
        strict_backend=False,
    )

    assert loaded == fallback_payload
    assert source == "file"


def test_write_normalized_graph_json_creates_snapshot(tmp_path: Path):
    payload = {"nodes": [{"person": "张骞", "domain_tags": ["外交"]}], "edges": []}
    out_path = tmp_path / "graph" / "normalized_graph.json"

    result = graph_service.write_normalized_graph_json(payload, out_path)

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert result == out_path
    assert written["people"][0]["name"] == "张骞"
    assert written["domains"][0]["name"] == "外交"


def test_normalize_graph_payload_preserves_homepage_search_and_audit_fields():
    payload = {
        "nodes": [
            {
                "person": "张骞",
                "file": "张骞.html",
                "dynasty": "西汉",
                "risk_level": "low",
                "audit_pass": True,
                "audit_uncertain": {"birthplace": False},
                "birthplace": "城固",
                "birthplace_raw": "汉中郡城固",
                "birthplace_modern": "陕西城固",
                "birth_lat_wgs84": 33.156,
                "birth_lng_wgs84": 107.329,
                "birth_lat": 33.156,
                "birth_lng": 107.329,
                "birth_coord_system": "WGS84",
                "relations": ["汉武帝"],
                "relations_meta": [{"name": "汉武帝", "label": "君臣"}],
                "search_keys": ["张骞", "博望侯"],
                "search_tokens": ["zhangqian"],
                "search_pinyin": ["zhangqian"],
            }
        ],
        "edges": [],
    }

    normalized = graph_service.normalize_graph_payload(payload)
    person = normalized["people"][0]

    assert person["risk_level"] == "low"
    assert person["audit_pass"] is True
    assert json.loads(person["audit_uncertain_json"]) == {"birthplace": False}
    assert person["birthplace_raw"] == "汉中郡城固"
    assert person["birth_lat_wgs84"] == 33.156
    assert person["birth_coord_system"] == "WGS84"
    assert person["relations"] == ["汉武帝"]
    assert json.loads(person["relations_meta_json"]) == [{"name": "汉武帝", "label": "君臣"}]
    assert person["search_keys"] == ["张骞", "博望侯"]
    assert person["search_tokens"] == ["zhangqian"]
    assert person["search_pinyin"] == ["zhangqian"]


class _FakeRow(dict):
    def keys(self):
        return super().keys()


class _FakeSession:
    def __init__(self, center_rows, neighbor_rows):
        self._center_rows = center_rows
        self._neighbor_rows = neighbor_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **_kwargs):
        if "LIMIT 1" in query and "MATCH (p:StoryMap:Person)" in query:
            return [_FakeRow(item) for item in self._center_rows]
        return [_FakeRow(item) for item in self._neighbor_rows]


class _FakeDriver:
    def __init__(self, center_rows, neighbor_rows):
        self._center_rows = center_rows
        self._neighbor_rows = neighbor_rows

    def session(self, database=None):
        _ = database
        return _FakeSession(self._center_rows, self._neighbor_rows)


class _FakePayloadSession:
    def __init__(self, node_rows, edge_rows):
        self._node_rows = node_rows
        self._edge_rows = edge_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **_kwargs):
        if "RETURN\n                  p.id AS id" in query:
            return [_FakeRow(item) for item in self._node_rows]
        return [_FakeRow(item) for item in self._edge_rows]


class _FakePayloadDriver:
    def __init__(self, node_rows, edge_rows):
        self._node_rows = node_rows
        self._edge_rows = edge_rows

    def session(self, database=None):
        _ = database
        return _FakePayloadSession(self._node_rows, self._edge_rows)


def test_get_related_people_graph_reads_neighbors_from_neo4j(monkeypatch):
    center_rows = [
        {
            "id": "person:张骞",
            "person": "张骞",
            "file": "张骞.html",
            "dynasty": "西汉",
            "birth_year": -164,
            "death_year": -114,
            "quote": "",
            "review": "",
            "aliases": ["博望侯"],
            "foreign_name": "",
            "domain_tags": ["外交"],
            "main_role_label": "外交家",
            "birthplace": "城固",
            "birthplace_modern": "陕西城固",
            "has_story": True,
        }
    ]
    neighbor_rows = [
        {
            "id": "person:汉武帝",
            "person": "汉武帝",
            "file": "汉武帝.html",
            "dynasty": "西汉",
            "birth_year": -156,
            "death_year": -87,
            "quote": "",
            "review": "",
            "aliases": [],
            "foreign_name": "",
            "domain_tags": ["政治"],
            "main_role_label": "皇帝",
            "birthplace": "长安",
            "birthplace_modern": "西安",
            "has_story": True,
            "relation_label": "君臣",
            "relation_type": "bio",
            "confidence": 0.88,
        }
    ]
    monkeypatch.setattr(graph_service, "neo4j_enabled", lambda _backend=None: True)
    monkeypatch.setattr(
        graph_service,
        "neo4j_config",
        lambda: graph_service.Neo4jConfig(uri="bolt://local", user="neo4j", password="pw", database="neo4j"),
    )
    monkeypatch.setattr(graph_service, "_driver", lambda: _FakeDriver(center_rows, neighbor_rows))

    related = graph_service.get_related_people_graph({"name": "张骞"}, markdown="# 张骞")

    assert (related.get("center") or {}).get("name") == "张骞"
    assert any(str(node.get("name") or "") == "汉武帝" for node in (related.get("nodes") or []))
    assert any(str(link.get("label") or "") == "君臣" for link in (related.get("links") or []))


def test_build_payload_from_neo4j_preserves_homepage_search_and_audit_fields(monkeypatch):
    node_rows = [
        {
            "id": "person:张骞",
            "person": "张骞",
            "file": "张骞.html",
            "dynasty": "西汉",
            "birth_year": -164,
            "death_year": -114,
            "time_year": -139,
            "quote": "",
            "review": "",
            "aliases": ["博望侯"],
            "foreign_name": "",
            "domain_tags": ["外交"],
            "main_role_band": "politics",
            "main_role_label": "外交家",
            "risk_level": "low",
            "audit_pass": True,
            "audit_uncertain_json": "{\"birthplace\":false}",
            "birthplace": "城固",
            "birthplace_raw": "汉中郡城固",
            "birthplace_modern": "陕西城固",
            "birth_lat_wgs84": 33.156,
            "birth_lng_wgs84": 107.329,
            "birth_lat": 33.156,
            "birth_lng": 107.329,
            "birth_coord_system": "WGS84",
            "relations": ["汉武帝"],
            "relations_meta_json": "[{\"name\":\"汉武帝\",\"label\":\"君臣\"}]",
            "search_keys": ["张骞", "博望侯"],
            "search_tokens": ["zhangqian"],
            "search_pinyin": ["zhangqian"],
            "has_story": True,
        }
    ]
    edge_rows = []
    monkeypatch.setattr(
        graph_service,
        "neo4j_config",
        lambda: graph_service.Neo4jConfig(uri="bolt://local", user="neo4j", password="pw", database="neo4j"),
    )
    monkeypatch.setattr(graph_service, "_driver", lambda: _FakePayloadDriver(node_rows, edge_rows))

    payload = graph_service._build_payload_from_neo4j()
    node = payload["nodes"][0]

    assert node["risk_level"] == "low"
    assert node["audit_pass"] is True
    assert node["audit_uncertain"] == {"birthplace": False}
    assert node["birthplace_raw"] == "汉中郡城固"
    assert node["birth_coord_system"] == "WGS84"
    assert node["relations"] == ["汉武帝"]
    assert node["relations_meta"] == [{"name": "汉武帝", "label": "君臣"}]
    assert node["search_keys"] == ["张骞", "博望侯"]
    assert node["search_tokens"] == ["zhangqian"]
    assert node["search_pinyin"] == ["zhangqian"]


def test_get_related_people_graph_returns_empty_on_neo4j_failure(monkeypatch):
    monkeypatch.setattr(graph_service, "neo4j_enabled", lambda _backend=None: True)
    monkeypatch.setattr(
        graph_service,
        "neo4j_config",
        lambda: graph_service.Neo4jConfig(uri="bolt://local", user="neo4j", password="pw", database="neo4j"),
    )

    class _BrokenDriver:
        def session(self, database=None):
            _ = database
            raise RuntimeError("neo4j unavailable")

    monkeypatch.setattr(graph_service, "_driver", lambda: _BrokenDriver())

    related = graph_service.get_related_people_graph({"name": "张骞"}, markdown="# 张骞")

    assert related == {}


def test_get_related_people_graph_from_payload_preserves_story_alias_pages():
    payload = {
        "nodes": [
            {"person": "王安石", "file": "王安石.html", "dynasty": "北宋", "birth_year": 1021, "death_year": 1086, "domain_tags": ["文学"]},
            {"person": "苏轼", "file": "苏轼.html", "dynasty": "北宋", "birth_year": 1037, "death_year": 1101, "domain_tags": ["文学"]},
            {"person": "苏东坡", "file": "苏东坡.html", "dynasty": "北宋", "birth_year": 1037, "death_year": 1101, "domain_tags": ["文学"]},
        ],
        "edges": [
            {"a": 0, "b": 1, "type": "manual", "label": "政坛交游", "confidence": 0.9, "weight": 3},
            {"a": 0, "b": 2, "type": "manual", "label": "别名关系", "confidence": 0.9, "weight": 3},
        ],
    }

    related = graph_service.get_related_people_graph_from_payload(
        {"name": "王安石", "dynasty": "北宋"},
        payload,
        markdown="# 王安石\n\n王安石与苏轼同朝。",
    )

    names = [str(node.get("name") or "") for node in (related.get("nodes") or [])]
    assert names.count("苏轼") == 1
    assert names.count("苏东坡") == 1

"""锁住 person_registry 的 idempotent + summary-fill 行为。

跑: ``python3 -m pytest storymap/tests/test_person_registry.py -v``
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from storymap.script.agent.person_registry import (
    _parse_llm_summary_json,
    register_new_person,
    update_birth_coords,
    update_people_master,
    update_people_summary,
)


def _write_minimal_md(person: str) -> str:
    """生成一份最小可用的 markdown,用于 registry 测试 (跳过 LLM 调用)。"""
    return (
        f"# {person}\n\n"
        f"## 人物档案\n"
        f"{person}-test 生于1234年5月,籍贯: 江南苏州府。普通人。\n\n"
        f"## 简介\n"
        f"测试任务:{person} 是虚拟人物。\n"
    )


def _tmp_corpus():
    """临时抽 corpus 用临时目录,测试完就丢。"""
    tmp = tempfile.mkdtemp(prefix="person-registry-test-")
    base = Path(tmp)
    paths = {
        "master": base / "people_master.json",
        "summary": base / "people_summary_index.json",
        "birth_coords": base / "people_birth_coords_wgs84.json",
    }
    return tmp, paths


# ---------------------------------------------------------------------------
# _parse_llm_summary_json (LLM 输出容错)
# ---------------------------------------------------------------------------

class TestParseLlmSummaryJson:
    def test_plain_json(self):
        raw = '{"status": "a", "short_review": "b"}'
        out = _parse_llm_summary_json(raw)
        assert out is not None
        assert out["status"] == "a"

    def test_markdown_fenced(self):
        raw = '```json\n{"identities": "i", "works": ["a", "b"]}\n```'
        out = _parse_llm_summary_json(raw)
        assert out is not None
        assert out["works"] == ["a", "b"]

    def test_no_json_block(self):
        assert _parse_llm_summary_json("这里是随便的文字") is None
        assert _parse_llm_summary_json("") is None
        assert _parse_llm_summary_json(None) is None

    def test_unclosed_json(self):
        # 没有 } -> None
        assert _parse_llm_summary_json('{"a": 1') is None


# ---------------------------------------------------------------------------
# idempotent register
# ---------------------------------------------------------------------------

class TestIdempotentRegistry:
    def test_update_people_summary_twice_is_idempotent(self, tmp_path: Path):
        # 直接调内部函数,跳过 LLM
        path = tmp_path / "summary.json"
        from storymap.script.agent.person_registry import _PEOPLE_SUMMARY_PATH
        # 临时改 module 全局指向 tmp
        from storymap.script.agent import person_registry as pr
        pr._PEOPLE_SUMMARY_PATH = path
        try:
            ok1, d1 = update_people_summary("测试X", "md")
            assert ok1 and d1 == "added"
            ok2, d2 = update_people_summary("测试X", "md")
            assert ok2 is False and d2 == "already-present"
        finally:
            pr._PEOPLE_SUMMARY_PATH = _PEOPLE_SUMMARY_PATH

    def test_update_people_master_appends(self, tmp_path: Path):
        path = tmp_path / "master.json"
        from storymap.script.agent import person_registry as pr
        from storymap.script.agent.person_registry import _PEOPLE_MASTER_PATH
        pr._PEOPLE_MASTER_PATH = path
        try:
            md = _write_minimal_md("曹丞-test")
            ok, detail = update_people_master("曹丞-test", md)
            assert ok and detail == "added"
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert any(p.get("person") == "曹丞-test" for p in payload["people"])
        finally:
            pr._PEOPLE_MASTER_PATH = _PEOPLE_MASTER_PATH

    def test_register_is_idempotent(self, tmp_path: Path, monkeypatch):
        # 把 corpus 路径重定向到 tmp
        from storymap.script.agent import person_registry as pr
        paths = {
            "master": tmp_path / "people_master.json",
            "summary": tmp_path / "people_summary_index.json",
            "birth_coords": tmp_path / "people_birth_coords_wgs84.json",
        }
        for p in paths.values():
            p.write_text("{}", encoding="utf-8")

        md_text = _write_minimal_md("司马懿-test")

        # 第一次注册:master/summary/birth_coords 都应当 added
        out1 = register_new_person(
            "司马懿-test",
            md_text=md_text,
            rebuild_homepage=False,
            llm_fill_summary=False,  # 跳过 LLM 防风
            paths=paths,
        )
        assert out1["master"] == (True, "added")
        assert out1["summary"] == (True, "added")
        assert out1["birth_coords"] == (True, "added")
        assert out1["summary_fill"][0] is False  # 跳过了

        # 第二次:应当全部 already-present
        out2 = register_new_person(
            "司马懿-test",
            md_text=md_text,
            rebuild_homepage=False,
            llm_fill_summary=False,
            paths=paths,
        )
        assert out2["master"][0] is False
        assert out2["summary"][0] is False
        assert out2["birth_coords"][0] is False

    def test_dry_run_does_not_write(self, tmp_path: Path):
        from storymap.script.agent import person_registry as pr
        paths = {
            "master": tmp_path / "m.json",
            "summary": tmp_path / "s.json",
            "birth_coords": tmp_path / "b.json",
        }
        for p in paths.values():
            p.write_text("{}", encoding="utf-8")

        out = register_new_person(
            "杜甫-dryrun-test",
            md_text=_write_minimal_md("杜甫-dryrun-test"),
            rebuild_homepage=False,
            llm_fill_summary=False,
            paths=paths,
            dry_run=True,
        )
        for k in ("master", "summary", "birth_coords"):
            assert out[k] == (False, "dry-run")
        # 文件不应被改写
        for p in paths.values():
            assert p.read_text(encoding="utf-8") == "{}"


# ---------------------------------------------------------------------------
# LLM-fill summary (P1-5)
# ---------------------------------------------------------------------------

class TestWriteSummaryFields:
    def test_only_acceptable_keys_persist(self, tmp_path: Path):
        from storymap.script.agent import person_registry as pr
        from storymap.script.agent.person_registry import (
            _PEOPLE_SUMMARY_PATH,
            _write_summary_fields,
        )
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"items": {"李四": {"status": "old"}}}), encoding="utf-8")
        pr._PEOPLE_SUMMARY_PATH = path
        try:
            ok, detail = _write_summary_fields(
                "李四",
                {
                    "status": "新",
                    "identities": "新身份",
                    "works": ["w1"],
                    "intro": "新介绍",
                    "evil_injected": "BAD",  # 应被丢弃
                    "summary_fill": "BAD",
                },
            )
            assert ok
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = payload["items"]["李四"]
            assert entry["status"] == "新"   # 覆盖
            assert entry["identities"] == "新身份"
            assert entry["works"] == ["w1"]
            assert entry["intro"] == "新介绍"
            assert "evil_injected" not in entry
            assert "summary_fill" not in entry
        finally:
            pr._PEOPLE_SUMMARY_PATH = _PEOPLE_SUMMARY_PATH

    def test_empty_fields_returns_false(self, tmp_path: Path):
        from storymap.script.agent import person_registry as pr
        from storymap.script.agent.person_registry import (
            _PEOPLE_SUMMARY_PATH,
            _write_summary_fields,
        )
        path = tmp_path / "s.json"
        path.write_text("{}", encoding="utf-8")
        pr._PEOPLE_SUMMARY_PATH = path
        try:
            ok, detail = _write_summary_fields("李四", {"evil_key": "x"})
            assert ok is False
            assert "empty-fields" in detail or detail == "empty-fields"
        finally:
            pr._PEOPLE_SUMMARY_PATH = _PEOPLE_SUMMARY_PATH

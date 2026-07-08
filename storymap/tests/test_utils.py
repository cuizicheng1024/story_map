"""锁住 text_utils / persistence / star_office 等工具模块行为。

跑: ``python3 -m pytest storymap/tests/test_utils.py -v``
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from storymap.script.core.text_utils import strip_reasoning_blocks
from storymap.script.core.persistence import SafeJSONStore
from storymap.script.api.star_office import star_office_copy, star_office_lang


class TestStripReasoningBlocks:
    def test_removes_think_tags(self):
        # thinking block 用全角斜杠（<\uff0fthink>），需匹配实际模型输出格式
        result = strip_reasoning_blocks("<think>这是思考过程<\uff0fthink>这是正文")
        assert result == "这是正文"

    def test_removes_chinese_think_markers(self):
        result = strip_reasoning_blocks("思考过程这是一段推理/思考正文内容")
        assert "正文内容" in result

    def test_handles_empty(self):
        assert strip_reasoning_blocks("") == ""
        assert strip_reasoning_blocks(None) == ""  # type: ignore[arg-type]

    def test_handles_no_think_blocks(self):
        plain = "这是一段普通的 JSON 文本"
        assert strip_reasoning_blocks(plain) == plain


class TestSafeJSONStore:
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            store = SafeJSONStore(path)
            store._save({"key": "value", "nested": {"a": 1}})
            loaded = store._load()
            assert loaded == {"key": "value", "nested": {"a": 1}}

    def test_load_nonexistent_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nonexistent.json"
            store = SafeJSONStore(path)
            assert store._load() == {}

    def test_load_corrupted_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "corrupt.json"
            path.write_text("not valid json {{{{{{", encoding="utf-8")
            store = SafeJSONStore(path)
            assert store._load() == {}


class TestStarOfficeCopy:
    def test_resolves_known_key(self):
        result = star_office_copy("status_idle", lang="zh")
        assert result and "待命" in result

    def test_falls_back_to_key_for_unknown(self):
        result = star_office_copy("nonexistent_key", lang="zh")
        assert result == "nonexistent_key"

    def test_formats_with_kwargs(self):
        result = star_office_copy("status_running", lang="zh", label="苏轼")
        assert "苏轼" in result

    def test_lang_always_zh(self):
        assert star_office_lang("en") == "zh"
        assert star_office_lang("ja") == "zh"
        assert star_office_lang("zh") == "zh"
        assert star_office_lang("") == "zh"

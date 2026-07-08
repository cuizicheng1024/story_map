"""单元测试：LLM 人物名称校验器 — 解析逻辑。"""

from __future__ import annotations

import pytest

from storymap.script.agent.person_validator import (
    PersonValidationResult,
    _parse_llm_response,
)


class TestParseLLMResponse:
    """测试 _parse_llm_response 对各种 LLM 返回格式的容错解析。"""

    def test_parse_valid_historical(self):
        result = _parse_llm_response(
            '{"status": "valid", "reason": "唐代著名诗人", "candidates": []}',
            "李白",
        )
        assert result.status == "valid"
        assert result.is_valid
        assert not result.is_blocked
        assert not result.needs_disambiguation
        assert result.reason == "唐代著名诗人"

    def test_parse_fictional_novel_character(self):
        result = _parse_llm_response(
            '{"status": "fictional", "reason": "金庸小说《射雕英雄传》虚构人物", "candidates": []}',
            "郭靖",
        )
        assert result.status == "fictional"
        assert result.is_blocked
        assert not result.is_valid

    def test_parse_inappropriate(self):
        result = _parse_llm_response(
            '{"status": "inappropriate", "reason": "涉黄内容", "candidates": []}',
            "xxx",
        )
        assert result.status == "inappropriate"
        assert result.is_blocked

    def test_parse_ambiguous_with_candidates(self):
        result = _parse_llm_response(
            '{"status": "ambiguous", "reason": "可能指多位历史人物", "candidates": ['
            '{"name": "张良", "dynasty": "西汉", "identity": "谋士", "suggested_question": "是西汉的张良吗？"},'
            '{"name": "张良", "dynasty": "现代", "identity": "学者", "suggested_question": "是现代学者张良吗？"}'
            "]}",
            "张良",
        )
        assert result.status == "ambiguous"
        assert result.needs_disambiguation
        assert len(result.candidates) == 2
        assert result.candidates[0]["dynasty"] == "西汉"

    def test_parse_markdown_wrapped_json(self):
        result = _parse_llm_response(
            '```json\n{"status": "valid", "reason": "ok", "candidates": []}\n```',
            "苏轼",
        )
        assert result.status == "valid"

    def test_parse_extra_text_around_json(self):
        result = _parse_llm_response(
            '根据规则判断：\n{"status": "fictional", "reason": "神话人物", "candidates": []}\n以上是判断结果。',
            "孙悟空",
        )
        assert result.status == "fictional"

    def test_parse_unknown_status_falls_back_to_ambiguous(self):
        result = _parse_llm_response(
            '{"status": "unknown", "reason": "不确定", "candidates": []}',
            "某人物",
        )
        assert result.status == "ambiguous"

    def test_parse_empty_response(self):
        result = _parse_llm_response("", "某人物")
        # 无法解析时降级放行，不阻断流程
        assert result.status == "valid"
        assert "解析失败" in result.reason

    def test_parse_invalid_json(self):
        result = _parse_llm_response("not json at all", "某人物")
        assert result.status == "valid"
        assert "解析失败" in result.reason

    def test_parse_ambiguous_no_candidates_adds_default(self):
        result = _parse_llm_response(
            '{"status": "ambiguous", "reason": "名称过于模糊", "candidates": []}',
            "李",
        )
        assert result.status == "ambiguous"
        assert len(result.candidates) == 1
        assert "补充朝代" in result.candidates[0]["suggested_question"]

    def test_person_validation_result_properties(self):
        r = PersonValidationResult("valid")
        assert r.is_valid
        assert not r.is_blocked
        assert not r.needs_disambiguation

        r = PersonValidationResult("fictional")
        assert not r.is_valid
        assert r.is_blocked
        assert not r.needs_disambiguation

        r = PersonValidationResult("inappropriate")
        assert r.is_blocked

        r = PersonValidationResult("ambiguous")
        assert r.needs_disambiguation
        assert not r.is_blocked

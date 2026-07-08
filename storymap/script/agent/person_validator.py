"""
============================================================================
  agent.person_validator — 基于 LLM 的历史人物名称语义校验器
============================================================================
  在静态校验（黑名单、格式检查）通过后，调用 LLM 对人物名称做语义级判定，
  拦截虚构人物、不当内容，并对模糊名称返回消歧候选信息。

  返回类型：PersonValidationResult
    - status: "valid" | "fictional" | "inappropriate" | "ambiguous"
    - reason: 简短说明
    - candidates: ambiguous 时列出可能候选人及其朝代/身份信息

  使用示例：
    from storymap.script.agent.person_validator import validate_person_name
    result = validate_person_name(llm, "张良")
    if result.status == "ambiguous":
        print(f"请补充信息：{result.candidates}")
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .llm_client import StoryAgentLLM

_LOGGER = logging.getLogger("storymap.agent.person_validator")

# ── LLM 校验系统提示词 ──
_VALIDATOR_SYSTEM_PROMPT = """你是严谨的历史人物名称校验器。判断输入的人物名称属于以下哪类：

1. valid — 真实历史人物，有可靠史料记载（正史、考古、学术研究）
2. fictional — 虚构人物（小说、影视、游戏、漫画、民间传说、神话中的人物，无可靠史料证实其历史存在）
3. inappropriate — 不当内容（涉黄、涉暴、极端敏感政治、侮辱性称呼）
4. ambiguous — 名称模糊：可能指代多位历史人物，或名称过于小众/冷僻，需要用户补充更多上下文（朝代、身份、成就等）才能确定

规则：
- 只返回 JSON，禁止输出任何其它文字
- 不确定时倾向 ambiguous，不随意判定为 fictional
- 民间传说人物（孟姜女、梁山伯与祝英台、白蛇传人物等）归为 fictional
- 神话人物（孙悟空、哪吒、玉皇大帝等）归为 fictional
- 明确的历史人物（李白、杜甫、苏轼、秦始皇、拿破仑、莎士比亚等）直接返回 valid
- 若名称可能指代多位历史人物（如"张良"可指西汉张良或现代同名者），标记为 ambiguous 并列出可能的候选人
- 名称过于简短或冷僻（单字名、生僻名），标记为 ambiguous 并建议补充信息
- 外国历史人物同样适用以上规则

输出 JSON 格式：
{
  "status": "valid|fictional|inappropriate|ambiguous",
  "reason": "简短说明（10-30字）",
  "candidates": []
}

candidates 格式（仅 ambiguous 时填写，最多 5 个）：
[
  {"name": "人物名", "dynasty": "朝代/时代", "identity": "身份/成就", "suggested_question": "建议向用户追问的问题"}
]"""

# ── 用户提示词模板 ──
_USER_PROMPT_TEMPLATE = "请校验以下人物名称：{person_name}"


@dataclass
class PersonValidationResult:
    """LLM 人物名称校验结果。

    Attributes:
        status: 校验状态 — valid / fictional / inappropriate / ambiguous
        reason: 简短说明
        candidates: ambiguous 时的候选人列表
        raw_response: LLM 原始返回文本（调试用）
    """

    status: str
    reason: str = ""
    candidates: List[Dict[str, str]] = field(default_factory=list)
    raw_response: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"

    @property
    def is_blocked(self) -> bool:
        return self.status in ("fictional", "inappropriate")

    @property
    def needs_disambiguation(self) -> bool:
        return self.status == "ambiguous"


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从可能包含额外文字的文本中提取 JSON 对象（支持嵌套大括号）。

    通过大括号计数找到第一个完整的 JSON 对象边界，避免简单正则
    无法处理 candidates 数组中嵌套对象的问题。

    Args:
        text: 可能包含额外文字的原始文本

    Returns:
        解析成功返回 dict，失败返回 None
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


def _parse_llm_response(text: str, person_name: str) -> PersonValidationResult:
    """解析 LLM 返回的 JSON 文本为 PersonValidationResult。

    对 LLM 输出的常见格式问题（包裹在 ```json 中、多余文字等）做容错处理。

    Args:
        text: LLM 原始返回文本
        person_name: 校验的人物名称

    Returns:
        PersonValidationResult 实例；解析失败时降级放行（status="valid"），不阻断流程
    """
    cleaned = (text or "").strip()
    # 去除 markdown 代码块包裹
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # 尝试直接解析整个文本
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        obj = None
    # 若直接解析失败，尝试从文本中提取 JSON 对象（支持嵌套）
    if obj is None:
        obj = _extract_json_object(cleaned)
    if obj is None:
        _LOGGER.warning("LLM 返回中未找到有效 JSON: %s", text[:200])
        # 无法解析 JSON 时降级放行，避免因 LLM 格式问题阻断正常用户
        return PersonValidationResult(
            status="valid",
            reason="校验结果解析失败，跳过语义校验",
            raw_response=text,
        )
    status = str(obj.get("status") or "").strip().lower()
    if status not in ("valid", "fictional", "inappropriate", "ambiguous"):
        status = "ambiguous"
    reason = str(obj.get("reason") or "").strip()
    candidates: List[Dict[str, str]] = []
    raw_candidates = obj.get("candidates") or []
    if isinstance(raw_candidates, list):
        for c in raw_candidates:
            if isinstance(c, dict):
                candidates.append(
                    {
                        "name": str(c.get("name") or "").strip(),
                        "dynasty": str(c.get("dynasty") or "").strip(),
                        "identity": str(c.get("identity") or "").strip(),
                        "suggested_question": str(c.get("suggested_question") or "").strip(),
                    }
                )
    # 兜底：如果 LLM 返回 ambiguous 但没有候选人，补充默认追问
    if status == "ambiguous" and not candidates:
        candidates.append(
            {
                "name": person_name,
                "dynasty": "",
                "identity": "",
                "suggested_question": f"「{person_name}」可能指代多位人物，请补充朝代、身份或代表作品以便精确定位",
            }
        )
    return PersonValidationResult(
        status=status,
        reason=reason,
        candidates=candidates,
        raw_response=text,
    )


def validate_person_name(llm: "StoryAgentLLM", person_name: str) -> PersonValidationResult:
    """调用 LLM 对人物名称做语义级校验。

    在静态校验（黑名单、格式）通过后调用，作为深层语义防线。
    LLM 调用失败时降级为 ambiguous 状态（不阻断流程，交由上游处理）。

    Args:
        llm: StoryAgentLLM 实例，用于调用大模型
        person_name: 待校验的人物名称

    Returns:
        PersonValidationResult 实例

    Raises:
        不抛出异常 — LLM 调用失败时降级放行（status="valid"），不阻断流程
    """
    messages = [
        {"role": "system", "content": _VALIDATOR_SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(person_name=person_name)},
    ]
    try:
        raw = llm.think(messages, temperature=0.0, timeout=30, max_retries=1)
    except Exception as exc:
        _LOGGER.warning("LLM 人物校验调用失败: %s", exc)
        # LLM 不可用时降级放行，避免阻断正常用户
        return PersonValidationResult(
            status="valid",
            reason="校验服务暂不可用，跳过语义校验",
        )
    if not raw:
        _LOGGER.warning("LLM 人物校验返回空结果: %s", person_name)
        return PersonValidationResult(
            status="valid",
            reason="校验服务返回空结果，跳过语义校验",
        )
    return _parse_llm_response(raw, person_name)

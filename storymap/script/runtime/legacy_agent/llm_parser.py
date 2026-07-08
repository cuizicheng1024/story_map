"""
===============================================================================
LLM 输出解析模块 — LLM Parser
===============================================================================
提供 LLM 原始输出文本的解析与规范化工具，将非结构化的 LLM 响应转换为
类型安全的 Python 数据结构。

核心功能：
  - strip_code_fences:  去除 LLM 输出中的 Markdown 代码围栏（```json ... ```）
  - parse_json_payload: 从 LLM 文本中提取并解析 JSON 对象
  - coerce_issue:       将原始字典强制转换为类型安全的 AgentIssue
  - coerce_issue_list:  将 LLM 返回的问题列表规范化

典型用法：
    from .llm_parser import parse_json_payload, coerce_issue_list
    raw = llm_response.text
    data = parse_json_payload(raw)
    issues = coerce_issue_list(data.get("issues", []))
===============================================================================
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .state import AgentIssue


# ============================================================================
# 1. 代码围栏处理
# ============================================================================

def strip_code_fences(text: str) -> str:
    """去除 LLM 输出中的 Markdown 代码围栏标记。

    LLM 经常将 JSON 输出包裹在 ```json ... ``` 或 ``` ... ``` 中，
    本函数移除这些标记并返回纯文本内容。

    Args:
        text: LLM 的原始输出文本，可能包含 Markdown 代码围栏。

    Returns:
        str: 去除围栏标记后的纯文本内容，首尾空白已清除。
    """
    body = str(text or "").strip()
    if body.startswith("```"):
        # 去除开头的 ```（可能带有语言标识如 json、python 等）
        body = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", body)
        # 去除结尾的 ```
        body = re.sub(r"\n?```$", "", body)
    return body.strip()


# ============================================================================
# 2. JSON 解析
# ============================================================================

def parse_json_payload(text: str) -> Optional[Dict[str, object]]:
    """从 LLM 输出文本中提取并解析 JSON 对象。

    采用多种策略尝试解析：
      1. 先去除代码围栏
      2. 对整个文本尝试 JSON 解析
      3. 若失败，用正则提取最外层 { ... } 后再尝试解析

    Args:
        text: LLM 的原始输出文本。

    Returns:
        Optional[Dict[str, object]]: 解析成功返回字典对象，失败返回 None。
    """
    body = strip_code_fences(text)
    if not body:
        return None

    # 候选解析文本列表：完整文本 + 正则提取的 JSON 块
    candidates = [body]
    match = re.search(r"(\{[\s\S]*\})", body)
    if match:
        candidates.append(match.group(1))

    # 逐个尝试 JSON 解析
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj

    return None


# ============================================================================
# 3. 数据结构规范化
# ============================================================================

def coerce_issue(
    *,
    field: str,
    claim: str,
    correction: str,
    confidence: float,
    reason: str,
) -> AgentIssue:
    """将原始字段值强制转换为类型安全的 AgentIssue 字典。

    所有参数均为 keyword-only，防止调用时参数顺序错误。

    Args:
        field:      问题所属字段名（如 "quote"、"location"、"identity"）。
        claim:      原始声明文本。
        correction: 建议的纠正方案。
        confidence: 问题置信度（0.0 ~ 1.0）。
        reason:     问题原因说明。

    Returns:
        AgentIssue: 规范化后的问题字典，confidence 已四舍五入到 3 位小数。
    """
    return {
        "field": field,
        "claim": claim,
        "correction": correction,
        "confidence": round(float(confidence), 3),
        "reason": reason,
    }


def coerce_issue_list(raw_issues: object) -> List[AgentIssue]:
    """将 LLM 返回的原始问题列表规范化为 AgentIssue 列表。

    对每个元素进行类型检查和字段默认值填充，确保返回的数据结构一致可靠。
    非列表或非字典元素会被静默跳过。

    Args:
        raw_issues: LLM 返回的原始问题数据，预期为 list[dict]。

    Returns:
        List[AgentIssue]: 规范化后的 AgentIssue 列表。
            若 raw_issues 不是列表，返回空列表。
    """
    issues: List[AgentIssue] = []
    if not isinstance(raw_issues, list):
        return issues

    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(
            coerce_issue(
                field=str(item.get("field") or "other"),
                claim=str(item.get("claim") or ""),
                correction=str(item.get("correction") or ""),
                confidence=float(item.get("confidence") or 0.0),
                reason=str(item.get("reason") or ""),
            )
        )
    return issues


__all__ = [
    "coerce_issue",
    "coerce_issue_list",
    "parse_json_payload",
    "strip_code_fences",
]

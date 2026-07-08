"""降级回退模块 — Agent 工具调用失败时的兜底策略。

本模块为管线 A 的三个核心工具提供确定性降级实现，
确保即使 LLM 或外部 API 完全不可用，管线仍能产出可用结果。

降级策略：
  1. fallback_search_result()      — 检索失败 → 返回最小人物资料
  2. fallback_generate_markdown()  — 生成失败 → 确定性 Markdown 组装
  3. fallback_validation()         — 校验失败 → 基础规则校验

设计原则：
  - 降级结果质量低于正常结果，但保证管线不崩溃
  - 所有降级函数都是纯 Python 实现，不依赖 LLM 或外部 API
  - 降级原因会记录到 state["degraded_reasons"]
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .state import StoryAgentState
from .validation_rules import default_validate_markdown


# ═══════════════════════════════════════════════════════════════════
#  降级 1：检索回退 — 最小人物资料
# ═══════════════════════════════════════════════════════════════════

def fallback_search_result(
    person: str,
    state: StoryAgentState,
) -> Dict[str, object]:
    """检索工具失败时的最小降级结果。

    返回一个仅包含人物名和降级标记的最小检索结果，
    确保后续 Agent 至少有一个可用的基础结构。

    内容：
      - summary: 仅包含人物名
      - timeline: 空列表
      - places: 空列表
      - identities: 空列表
      - sources: [{"source": "fallback", ...}]
      - cautions: ["检索工具不可用，以下内容由降级流程生成"]

    Args:
        person: 人物名
        state:  共享状态

    Returns:
        Dict: 最小检索结果
    """
    return {
        "person": str(person or "").strip(),
        "summary": f"{str(person or '').strip()}（检索工具不可用，以下内容由降级流程生成）",
        "timeline": [],
        "places": [],
        "identities": [],
        "achievements": [],
        "sources": [
            {
                "source": "fallback",
                "title": f"{str(person or '').strip()} 降级检索",
                "summary": "检索工具不可用，以下内容由降级流程生成",
                "url": "",
            }
        ],
        "cautions": ["检索工具不可用，以下内容由降级流程生成"],
        "short_review_candidate": "",
    }


# ═══════════════════════════════════════════════════════════════════
#  降级 2：生成回退 — 确定性 Markdown 组装
# ═══════════════════════════════════════════════════════════════════

def fallback_generate_markdown(
    editor_structure: Dict[str, object],
    *,
    infer_dynasty: Optional[Callable[[Dict[str, object]], str]] = None,
) -> str:
    """生成工具失败时的确定性 Markdown 组装。

    不依赖 LLM，直接从 editor_structure 中提取数据拼接 Markdown。
    产出格式与正常 LLM 生成的一致，但内容更简略。

    组装结构：
      1. short_review（从 search_result.summary 或 person 名生成）
      2. 生平时间线（从 search_result.timeline 拼接）
      3. 足迹地点（从 place_maps 拼接，含坐标）

    Args:
        editor_structure: EditorAgent 的输入结构
                          {"person", "search_result", "place_maps", ...}
        infer_dynasty:    可选朝代推断函数（用于 short_review）

    Returns:
        str: 降级 Markdown 文本
    """
    search_result = dict(editor_structure.get("search_result") or {})
    place_maps = list(editor_structure.get("place_maps") or [])
    person = str(editor_structure.get("person") or "").strip()

    # ── 确定 short_review ──
    summary = str(search_result.get("summary") or search_result.get("short_review_candidate") or "").strip()
    if not summary:
        summary = f"{person}，历史人物。"

    # ── 朝代信息 ──
    dynasty = ""
    if callable(infer_dynasty):
        try:
            dynasty = infer_dynasty(search_result)
        except Exception:
            pass
    if dynasty:
        summary = f"{dynasty}{summary}" if dynasty not in summary else summary

    # ── 组装 Markdown ──
    lines: List[str] = [
        f"## {person}",
        "",
        summary,
        "",
    ]

    # 生平时间线
    timeline = search_result.get("timeline")
    if isinstance(timeline, list) and timeline:
        lines.append("### 生平")
        lines.append("")
        for item in timeline:
            if not isinstance(item, dict):
                continue
            year = str(item.get("year") or "").strip()
            desc = str(item.get("event") or item.get("description") or "").strip()
            place = str(item.get("place") or item.get("name") or "").strip()
            if year or desc:
                entry = f"- "
                if year:
                    entry += f"**{year}**"
                if desc:
                    entry += f"：{desc}"
                if place:
                    entry += f"（{place}）"
                lines.append(entry)
        lines.append("")

    # 足迹地点
    if place_maps:
        lines.append("### 足迹")
        lines.append("")
        for item in place_maps:
            if not isinstance(item, dict):
                continue
            ancient = str(item.get("ancient_name") or item.get("query") or "").strip()
            modern = str(item.get("modern_name") or "").strip()
            lat = item.get("lat")
            lng = item.get("lng")
            if not ancient:
                continue
            entry = f"- {ancient}"
            if modern and modern != ancient:
                entry += f"（今{modern}）"
            if lat is not None and lng is not None:
                entry += f" `[{lat},{lng}]`"
            lines.append(entry)
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  降级 3：校验回退 — 基础规则校验
# ═══════════════════════════════════════════════════════════════════

def fallback_validation(
    markdown: str,
    *,
    person: str = "",
    validate_fn: Optional[Callable[[str], Dict[str, object]]] = None,
) -> Dict[str, object]:
    """校验工具失败时的降级校验。

    使用纯规则校验（default_validate_markdown）替代 LLM 校验，
    仅做格式层面的基础检查，不做语义分析。

    Args:
        markdown:    待校验的 Markdown 文本
        person:      人物名
        validate_fn: 校验函数（默认 default_validate_markdown）

    Returns:
        Dict: {"pass": bool, "risk_level": str, "issues": list, "notes": str}
    """
    fn = validate_fn or default_validate_markdown
    try:
        result = fn(markdown or "")
        if not isinstance(result, dict):
            return {
                "pass": False,
                "risk_level": "low",
                "issues": [],
                "notes": "校验降级：校验器未返回有效结果",
            }
        result["notes"] = str(result.get("notes") or "") + "（校验工具不可用，已降级为基础规则校验）"
        return result
    except Exception as exc:
        return {
            "pass": True,  # 降级校验失败时保守通过
            "risk_level": "low",
            "issues": [],
            "notes": f"校验降级：{exc}",
        }


__all__ = [
    "fallback_generate_markdown",
    "fallback_search_result",
    "fallback_validation",
]

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

try:
    from langgraph.graph import END, START, StateGraph

    _LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False

try:
    from ...agent import generation_service as generation_service_utils
    from ... import parsers as parser_utils
    from ...project_paths import classify_story_person_authenticity
    from .llm_parser import coerce_issue, coerce_issue_list, parse_json_payload
    from .memory import StoryAgentMemoryStore, get_default_memory_store
    from .fallbacks import (
        fallback_generate_markdown,
        fallback_search_result,
        fallback_validation,
    )
    from .runtime import build_runtime_reflection, build_runtime_reflection_prompt
    from .router import build_supervisor_update, resolve_next_step
    from .state import (
        AgentIssue,
        SearchSource,
        StoryAgentState,
        append_trace,
        create_initial_state,
        max_revisions_limit,
        merge_state,
        record_degraded_reason,
    )
    from .telemetry import copy_memory_counters, set_memory_access, update_memory_counters
    from .tool_runner import ToolCallError, call_tool
    from ...story_tooling import tool
except ImportError:
    import generation_service as generation_service_utils
    import parsers as parser_utils
    from project_paths import classify_story_person_authenticity
    from story_agent_llm_parser import coerce_issue, coerce_issue_list, parse_json_payload
    from story_agent_memory import StoryAgentMemoryStore, get_default_memory_store
    from story_agent_fallbacks import fallback_generate_markdown, fallback_search_result, fallback_validation
    from story_agent_runtime import build_runtime_reflection, build_runtime_reflection_prompt
    from story_agent_router import build_supervisor_update, resolve_next_step
    from story_agent_state import (
        AgentIssue,
        SearchSource,
        StoryAgentState,
        append_trace,
        create_initial_state,
        max_revisions_limit,
        merge_state,
        record_degraded_reason,
    )
    from story_agent_telemetry import copy_memory_counters, set_memory_access, update_memory_counters
    from story_agent_tool_runner import ToolCallError, call_tool
    from story_tooling import tool


_DYNASTY_TOKENS = (
    "夏朝",
    "商朝",
    "西周",
    "东周",
    "春秋",
    "战国",
    "秦朝",
    "西汉",
    "东汉",
    "三国",
    "西晋",
    "东晋",
    "南北朝",
    "隋朝",
    "唐朝",
    "唐代",
    "五代",
    "北宋",
    "南宋",
    "辽朝",
    "金朝",
    "元朝",
    "明朝",
    "清朝",
    "近代",
    "现代",
)

_QUOTE_LABEL_HINT_RE = re.compile(r"^\s*-\s*\*\*名篇名句\*\*：\s*(.+?)\s*$", re.MULTILINE)
_TRUTH_QUOTE = "吾爱吾师，吾更爱真理"
_APPROXIMATE_MARKERS = ("约", "约公元", "大约", "约于", "传为", "一说", "说法不一", "生年不详", "卒年不详")
_SEARCH_LLM_TIMEOUT_SECONDS = 60
_EDITOR_LLM_TIMEOUT_SECONDS = 60
_FACT_CHECK_LLM_TIMEOUT_SECONDS = 18
_TOOL_MANAGED_LLM_MAX_RETRIES = 2
_BROAD_ANCIENT_REGION_TOKENS = frozenset(
    {
        "河西",
        "河西走廊",
        "陇西",
        "漠北",
        "平阳",
        "关中",
        "中原",
        "江南",
        "西域",
    }
)
_NON_SINGLE_CITY_HINT_RE = re.compile(r"(一带|地区|沿线|流域|走廊|高原|草原|半岛|遗址|附近|周边|南部|北部|中部)")
_UNCERTAINTY_MARKERS = ("存疑", "说法不一", "一说", "另说", "或说", "不详", "约", "可能", "疑为", "未详")
_CHINESE_DIGIT_MAP = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_IDENTITY_TOKEN_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("original_name", re.compile(r"(原名|本名|原姓)")),
    ("alias", re.compile(r"(别名|别称|又名|曾用名)")),
    ("courtesy_name", re.compile(r"(字|表字)")),
    ("art_name", re.compile(r"(号|别号|自号)")),
)
_HIGH_RISK_CLAIM_RULES = (
    {
        "person": "亚里士多德",
        "pattern": re.compile(r"《形而上学》[^。\n]*吾爱吾师，吾更爱真理"),
        "field": "quote",
        "correction": "将该句改写为后世概括语，不要直接标成《形而上学》的逐字原文。",
        "confidence": 0.95,
        "reason": "这句话常用于概括亚里士多德重真理的立场，但通常不宜直接写成《形而上学》的严格逐字引文。",
    },
    {
        "person": "郑和",
        "pattern": re.compile(r"(姓名|事件|原名)[^。\n]*原名[：:\s]*马三保"),
        "field": "identity",
        "correction": "改为“原姓马，小字三保；后世常见马三保等称谓”一类更稳妥的表述。",
        "confidence": 0.9,
        "reason": "“原名马三保”表述过于绝对，更稳妥的写法应保留姓马、小字三保与后世称谓之间的区分。",
    },
    {
        "person": "霍去病",
        "pattern": re.compile(r"(平阳[^\n]*今山西省临汾市|陇西[^\n]*今甘肃省定西市|河西(?:地区|走廊)?[^\n]*今甘肃省张掖市|漠北[^\n]*今内蒙古自治区呼和浩特市)"),
        "field": "location",
        "correction": "将古地名改写成“今某地区/一带/走廊沿线”等更稳妥的现代参照，不要压成单一现代城市。",
        "confidence": 0.92,
        "reason": "这类古地理范围通常大于单一现代城市，直接一一等同会造成知识性误导。",
    },
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _geocode_service_utils():
    try:
        from ... import geocode_service as geocode_service_utils
    except ImportError:
        import geocode_service as geocode_service_utils
    return geocode_service_utils


def _geocode_api_utils():
    try:
        from ... import story_geocode_api as story_geocode_api_utils
    except ImportError:
        import story_geocode_api as story_geocode_api_utils
    return story_geocode_api_utils


def _read_prompt(relpath: str) -> str:
    prompt_path = _project_root() / "storymap" / "docs" / relpath
    return prompt_path.read_text(encoding="utf-8")


def _emit(llm: object, message: str) -> None:
    if llm is None:
        return
    callback = getattr(llm, "_emit", None)
    if not callable(callback):
        return
    try:
        callback(message)
    except Exception:
        return


def _issue_field_from_text(text: str) -> str:
    content = str(text or "")
    if "坐标" in content or "地名" in content or "地点" in content:
        return "location"
    if "年份表" in content or "时间" in content or "顺序" in content:
        return "timeline"
    if "身份" in content:
        return "identity"
    if "享年" in content:
        return "age"
    return "other"


def _dedupe_issues(issues: List[AgentIssue]) -> List[AgentIssue]:
    out: List[AgentIssue] = []
    seen = set()
    for item in issues:
        key = (
            str(item.get("field") or ""),
            str(item.get("claim") or ""),
            str(item.get("correction") or ""),
            str(item.get("reason") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _extract_year(text: str) -> Optional[int]:
    content = str(text or "")
    # 优先识别"公元前/前 XXX 年"形式，统一转换为负数年份，
    # 避免春秋战国等公元前人物在寿命/时间线一致性校验中被算成正数年份，
    # 导致生卒差与享年不自洽的误报或漏报。
    bce_match = re.search(r"(?:公元前|前)\s*(\d{1,4})\s*年", content)
    if bce_match:
        try:
            return -int(bce_match.group(1))
        except Exception:
            return None
    match = re.search(r"(-?\d{1,4})\s*年", content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_age(text: str) -> Optional[int]:
    content = str(text or "")
    match = re.search(r"(\d{1,3})\s*(?:周)?岁", content)
    if not match:
        cn_match = re.search(r"([零〇一二两三四五六七八九十百廿卅]{1,6})\s*(?:周)?岁", content)
        if not cn_match:
            return None
        return _parse_chinese_number(cn_match.group(1))
    try:
        return int(match.group(1))
    except Exception:
        return None


def _parse_chinese_number(text: str) -> Optional[int]:
    raw = str(text or "").strip()
    if not raw:
        return None
    normalized = raw.replace("廿", "二十").replace("卅", "三十").replace("两", "二")
    total = 0
    current = 0
    for ch in normalized:
        if ch in _CHINESE_DIGIT_MAP:
            current = _CHINESE_DIGIT_MAP[ch]
            total += current
            continue
        if ch == "十":
            if current == 0:
                total += 10
            else:
                total += current * 9
            current = 0
            continue
        if ch == "百":
            if current == 0:
                total = max(total, 1) * 100
            else:
                total += current * 99
            current = 0
            continue
        return None
    return total or None


def _needs_modern_hint(text: str) -> bool:
    content = str(text or "").strip()
    if not content:
        return False
    if "今" in content:
        return False
    if re.search(r"(省|市|县|区|州|郡|自治区|特别行政区)", content):
        return False
    return True


def _is_vague_location(text: str) -> bool:
    content = str(text or "").strip()
    if not content:
        return False
    return bool(re.search(r"(境内|诸地|各地|一带|附近|周边|沿线|流域|地区|北方|南方|中原|关中|江南)$", content))


def _looks_like_single_modern_city(text: str) -> bool:
    content = str(text or "").strip()
    if not content:
        return False
    if _NON_SINGLE_CITY_HINT_RE.search(content):
        return False
    return bool(re.search(r"(省)?[^，。、；;]{1,20}(市|县|区)$", content))


def _timeline_order_issues(parsed_doc: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    years: List[Tuple[int, List[str]]] = []
    for row in rows:
        if not row:
            continue
        year = _extract_year(row[0])
        if year is None:
            continue
        years.append((year, row))
    for idx in range(1, len(years)):
        prev_year, _ = years[idx - 1]
        current_year, row = years[idx]
        if current_year < prev_year:
            issues.append(
                coerce_issue(
                    field="timeline",
                    claim=" | ".join(str(cell or "") for cell in row),
                    correction="按时间从早到晚重新排序时间线表",
                    confidence=0.82,
                    reason="时间线年份顺序出现倒序",
                )
            )
            break
    return issues


def _location_precision_issues(parsed_doc: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    basic_info = getattr(parsed_doc, "basic_info", None)
    if basic_info is not None:
        birth_text = str(getattr(basic_info, "birth_text", "") or "")
        death_text = str(getattr(basic_info, "death_text", "") or "")
        if birth_text and _needs_modern_hint(birth_text):
            issues.append(
                coerce_issue(
                    field="location",
                    claim=birth_text,
                    correction="补充出生地对应的现代地名",
                    confidence=0.68,
                    reason="出生地缺少现代地名提示，后续地图定位容易不稳定",
                )
            )
        if death_text and _needs_modern_hint(death_text):
            issues.append(
                coerce_issue(
                    field="location",
                    claim=death_text,
                    correction="补充去世地对应的现代地名",
                    confidence=0.68,
                    reason="去世地缺少现代地名提示，后续地图定位容易不稳定",
                )
            )
    header = list(getattr(parsed_doc, "timeline_header", []) or [])
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    modern_idx = None
    for idx, cell in enumerate(header):
        if "现称" in str(cell or ""):
            modern_idx = idx
            break
    if modern_idx is not None:
        for row in rows:
            if modern_idx >= len(row):
                continue
            modern_name = str(row[modern_idx] or "").strip()
            ancient_name = str(row[modern_idx - 1] or "").strip() if modern_idx > 0 and modern_idx - 1 < len(row) else ""
            if ancient_name and not modern_name:
                issues.append(
                    coerce_issue(
                        field="location",
                        claim=" | ".join(str(cell or "") for cell in row),
                        correction="为该时间线条目补充现代地名",
                        confidence=0.73,
                        reason="时间线存在古称但缺少现称",
                    )
                )
                break
            if modern_name and _is_vague_location(modern_name):
                issues.append(
                    coerce_issue(
                        field="location",
                        claim=" | ".join(str(cell or "") for cell in row),
                        correction="将泛地名替换为可落点的现代城市、区县或明确遗址",
                        confidence=0.9,
                        reason="时间线现称仍是泛区域表述，无法保证地图定位精度",
                    )
                )
                break
    return issues


def _ancient_modern_overmapping_issues(parsed_doc: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    header = list(getattr(parsed_doc, "timeline_header", []) or [])
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    ancient_idx = None
    modern_idx = None
    for idx, cell in enumerate(header):
        label = str(cell or "")
        if "古称" in label and ancient_idx is None:
            ancient_idx = idx
        if "现称" in label and modern_idx is None:
            modern_idx = idx
    if ancient_idx is None or modern_idx is None:
        return issues
    for row in rows:
        if ancient_idx >= len(row) or modern_idx >= len(row):
            continue
        ancient_name = str(row[ancient_idx] or "").strip()
        modern_name = str(row[modern_idx] or "").strip()
        if not ancient_name or not modern_name:
            continue
        if ancient_name not in _BROAD_ANCIENT_REGION_TOKENS:
            continue
        if not _looks_like_single_modern_city(modern_name):
            continue
        issues.append(
            coerce_issue(
                field="location",
                claim=" | ".join(str(cell or "") for cell in row),
                correction="把这类古地理范围改成“今某地区/一带/走廊沿线”等更稳妥的现代参照，不要直接压成单一现代城市。",
                confidence=0.86,
                reason="古地理范围明显大于单一现代城市，存在过度一对一映射风险。",
            )
        )
        break
    return issues


def _lifespan_issues(parsed_doc: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    basic_info = getattr(parsed_doc, "basic_info", None)
    if basic_info is None:
        return issues
    birth_year = _extract_year(getattr(basic_info, "birth_text", ""))
    death_year = _extract_year(getattr(basic_info, "death_text", ""))
    lifespan = _extract_age(getattr(basic_info, "lifespan", ""))
    if birth_year is None or death_year is None or lifespan is None:
        return issues
    estimated = death_year - birth_year
    if abs(estimated - lifespan) > 1:
        issues.append(
            coerce_issue(
                field="age",
                claim=f"出生 {birth_year} 年，去世 {death_year} 年，享年 {lifespan} 岁",
                correction=f"核对享年是否应为 {estimated} 岁左右",
                confidence=0.88,
                reason="生卒年与享年不自洽",
            )
        )
    birth_text = str(getattr(basic_info, "birth_text", "") or "")
    death_text = str(getattr(basic_info, "death_text", "") or "")
    lifespan_text = str(getattr(basic_info, "lifespan", "") or "")
    if lifespan is not None and any(marker in birth_text or marker in death_text for marker in _APPROXIMATE_MARKERS):
        if "约" not in lifespan_text and "左右" not in lifespan_text and "余" not in lifespan_text:
            issues.append(
                coerce_issue(
                    field="age",
                    claim=f"出生：{birth_text}；去世：{death_text}；享年：{lifespan_text}",
                    correction="如果生卒年份本身带有“约/一说/不详”等不确定性，享年也应改为“约 XX 岁”或补充说法来源。",
                    confidence=0.84,
                    reason="生卒信息存在不确定性时，享年不宜写成完全确定的绝对结论。",
                )
            )
    return issues


def _quote_label_issues(content: str, *, person: str) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    for match in _QUOTE_LABEL_HINT_RE.finditer(str(content or "")):
        claim = str(match.group(1) or "").strip()
        if not claim:
            continue
        if "《" in claim and "》" in claim and "“" not in claim and '"' not in claim:
            issues.append(
                coerce_issue(
                    field="quote",
                    claim=claim,
                    correction="如果这里是在介绍作品或思想，请改成“代表作品”“代表著作”或“相关思想”，不要挂在“名篇名句”下。",
                    confidence=0.78,
                    reason="该条更像作品说明或思想概括，不像可核对的直接引文。",
                )
            )
            continue
        if "后世" in claim or "概括" in claim or "不宜" in claim or "非" in claim and "原文" in claim:
            issues.append(
                coerce_issue(
                    field="quote",
                    claim=claim,
                    correction="该条已承认并非严格原文，建议从“名篇名句”改到“相关思想”或说明性条目。",
                    confidence=0.72,
                    reason="该条明确属于后世概括或非严格原文，不适合作为“名篇名句”展示。",
                )
            )
    if person != "亚里士多德" and _TRUTH_QUOTE in str(content or ""):
        issues.append(
            coerce_issue(
                field="quote",
                claim=_TRUTH_QUOTE,
                correction="不要把这句话当作当前人物本人的名言；若确需保留，应说明它是后世概括亚里士多德学派精神的常见说法。",
                confidence=0.9,
                reason="该句不应被移作其他人物本人的名言或原话。",
            )
        )
    return issues


def _identity_alias_issues(content: str) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    text = str(content or "")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        categories = {
            category
            for category, pattern in _IDENTITY_TOKEN_PATTERNS
            if pattern.search(line)
        }
        if ("姓名" in line or "人物" in line or "身份" in line) and len(categories) >= 2:
            issues.append(
                coerce_issue(
                    field="identity",
                    claim=line,
                    correction="把原名、别名、字、号拆开表述，并补上“常见称谓/后世称法/早年姓氏”等限定，避免读者误解成唯一结论。",
                    confidence=0.74,
                    reason="原名/别名/字/号混写在同一结论里，容易把不同性质的称谓误读成同一种确定身份信息。",
                )
            )
            break
    return issues


def _non_authentic_agent_result(person: str, reason: str, *, max_revisions: int, llm_calls_limit: int) -> Dict[str, object]:
    issue = coerce_issue(
        field="authenticity",
        claim=str(person or ""),
        correction="改成人物库中可核实的真实人物，或先补齐可靠史料依据后再生成。",
        confidence=0.99,
        reason=f"人物真实性过滤拦截：{reason or 'non_authentic'}",
    )
    state = create_initial_state(person, max_revisions=max_revisions, llm_calls_limit=llm_calls_limit)
    state["validation"] = {
        "pass": False,
        "risk_level": "high",
        "issues": [issue],
        "notes": "人物真实性过滤拦截",
        "metrics": {},
    }
    state["critic_feedback"] = [issue]
    state["degraded_reasons"] = record_degraded_reason(state.get("degraded_reasons"), f"authenticity_filter:{reason or 'non_authentic'}")
    state["execution_trace"] = ["finish_agent"]
    state["final_markdown"] = ""
    return {"markdown": "", "state": state}


def _high_risk_claim_issues(content: str, *, person: str) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    text = str(content or "")
    for rule in _HIGH_RISK_CLAIM_RULES:
        if str(rule.get("person") or "") != str(person or ""):
            continue
        pattern = rule.get("pattern")
        if not isinstance(pattern, re.Pattern):
            continue
        match = pattern.search(text)
        if not match:
            continue
        issues.append(
            coerce_issue(
                field=str(rule.get("field") or "other"),
                claim=str(match.group(0) or "").strip(),
                correction=str(rule.get("correction") or "").strip(),
                confidence=float(rule.get("confidence") or 0.0),
                reason=str(rule.get("reason") or "").strip(),
            )
        )
    return issues


def _risk_level_from_issues(issues: List[AgentIssue]) -> str:
    if not issues:
        return "low"
    max_conf = max(float(item.get("confidence") or 0.0) for item in issues)
    if max_conf >= 0.8:
        return "high"
    if max_conf >= 0.5:
        return "medium"
    return "low"


def _llm_fact_check(
    llm: object,
    *,
    person: str,
    content: str,
) -> List[AgentIssue]:
    if not _fact_check_llm_enabled(llm):
        return []
    try:
        parsed_doc = parser_utils.parse_story_document(content)
    except Exception:
        return []
    prompt = _read_prompt("fact_check_prompt.md").format(
        person=person,
        basic_info=json.dumps(parsed_doc.basic_info.raw, ensure_ascii=False),
        summary_excerpt=(parsed_doc.overview or "")[:400],
        timeline_excerpt=json.dumps(parsed_doc.timeline_rows[:8], ensure_ascii=False),
    )
    raw = _llm_think(
        llm,
        [{"role": "system", "content": prompt}],
        temperature=0,
        timeout_seconds=_FACT_CHECK_LLM_TIMEOUT_SECONDS,
    )
    payload = parse_json_payload(raw or "")
    if not payload:
        return []
    return coerce_issue_list(payload.get("issues") or [])


def _llm_supports_runtime_overrides(llm: object) -> bool:
    think = getattr(llm, "think", None)
    if not callable(think):
        return False
    try:
        signature = inspect.signature(think)
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters.values()
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters):
        return True
    names = set(signature.parameters)
    return "timeout" in names and "max_retries" in names


def _llm_think(
    llm: object,
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0,
    timeout_seconds: Optional[int] = None,
    max_retries: int = _TOOL_MANAGED_LLM_MAX_RETRIES,
) -> object:
    if llm is None:
        return ""
    think = getattr(llm, "think", None)
    if not callable(think):
        return ""
    if _llm_supports_runtime_overrides(llm):
        return think(
            messages,
            temperature=temperature,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
    return think(messages, temperature=temperature)


def _clean_short_review_candidate(text: object, *, limit: int = 60) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)
    while True:
        normalized = re.sub(r"^\s*(?:人物)?短评[：:]\s*", "", cleaned)
        if normalized == cleaned:
            break
        cleaned = normalized.strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _fact_check_llm_enabled(llm: object = None) -> bool:
    if llm is None:
        return False
    enabled = (os.getenv("STORY_AGENT_ENABLE_FACT_CHECK_LLM") or "").strip().lower()
    return enabled in {"1", "true", "yes", "on"}


def _tool_uses_llm(custom_impl: object, *, default_uses_llm: bool) -> bool:
    if custom_impl is None:
        return bool(default_uses_llm)
    marker = getattr(custom_impl, "__story_agent_uses_llm__", None)
    if marker is None:
        return False
    return bool(marker)


def _ensure_short_review_in_markdown(markdown: str, candidate: object) -> str:
    body = str(markdown or "")
    review = _clean_short_review_candidate(candidate)
    if not body.strip() or not review:
        return body
    if review in body:
        return body
    lines = body.splitlines()
    history_idx = None
    impact_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## 五、历史影响":
            impact_idx = idx
        if stripped == "### 历史评价":
            history_idx = idx
            break
    bullet = f"- 短评：{review}"
    if history_idx is not None:
        insert_at = history_idx + 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        lines.insert(insert_at, bullet)
        return "\n".join(lines)
    if impact_idx is not None:
        insert_at = impact_idx + 1
        while insert_at < len(lines):
            stripped = lines[insert_at].strip()
            if stripped.startswith("## "):
                break
            insert_at += 1
        block = ["", "### 历史评价", bullet]
        lines[insert_at:insert_at] = block
        return "\n".join(lines)
    return body


def _caution_consistency_issues(content: str, cautions: object) -> List[AgentIssue]:
    issues: List[AgentIssue] = []
    caution_list = [str(item).strip() for item in list(cautions or []) if str(item).strip()]
    if not caution_list:
        return issues
    body = str(content or "")
    if any(marker in body for marker in _UNCERTAINTY_MARKERS):
        return issues
    caution_preview = "；".join(caution_list[:2])
    issues.append(
        coerce_issue(
            field="caution",
            claim=caution_preview,
            correction="把对应表述改成“存疑/说法不一/一说”等不确定表达，避免把检索阶段已标记的存疑点写成唯一结论。",
            confidence=0.8,
            reason="search_result 已标注存疑点，但当前正文没有体现不确定性表述。",
        )
    )
    return issues


def default_validate_markdown(
    content: str,
    *,
    person: str = "",
    llm: object = None,
) -> Dict[str, object]:
    metrics = generation_service_utils.collect_quality_metrics(content)
    text_issues = generation_service_utils.validate_data_quality(content)
    issues: List[AgentIssue] = [
        coerce_issue(
            field=_issue_field_from_text(item),
            claim=item,
            correction="",
            confidence=0.62,
            reason=item,
        )
        for item in text_issues
    ]
    try:
        parsed_doc = parser_utils.parse_story_document(content)
    except Exception:
        parsed_doc = None
    if parsed_doc is not None:
        if not person:
            person = str(getattr(getattr(parsed_doc, "basic_info", None), "name", "") or "")
        issues.extend(_timeline_order_issues(parsed_doc))
        issues.extend(_location_precision_issues(parsed_doc))
        issues.extend(_ancient_modern_overmapping_issues(parsed_doc))
        issues.extend(_lifespan_issues(parsed_doc))
    issues.extend(_quote_label_issues(content, person=person))
    issues.extend(_identity_alias_issues(content))
    issues.extend(_high_risk_claim_issues(content, person=person))
    issues.extend(_llm_fact_check(llm, person=person, content=content))
    issues = _dedupe_issues(issues)
    risk_level = _risk_level_from_issues(issues)
    hard_fail = any(float(item.get("confidence") or 0.0) >= 0.7 for item in issues)
    return {
        "pass": (not hard_fail),
        "risk_level": risk_level,
        "issues": issues,
        "notes": "" if not issues else f"共发现 {len(issues)} 个待核查点",
        "metrics": metrics,
    }


def _wikipedia_summary(person_name: str, timeout: int = 8) -> Optional[SearchSource]:
    url = f"https://zh.wikipedia.org/api/rest_v1/page/summary/{quote(person_name)}"
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "storymap-agent/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    summary = str(data.get("extract") or "").strip()
    if not summary:
        return None
    return {
        "source": "wikipedia",
        "title": str(data.get("title") or person_name),
        "summary": summary,
        "url": str(data.get("content_urls", {}).get("desktop", {}).get("page") or ""),
    }


def _baidu_baike_summary(person_name: str, timeout: int = 8) -> Optional[SearchSource]:
    url = f"https://baike.baidu.com/item/{quote(person_name)}"
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        resp.raise_for_status()
    except Exception:
        return None
    html = resp.text
    match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.I)
    if not match:
        match = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html, re.I)
    if not match:
        return None
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    if not summary:
        return None
    return {
        "source": "baidu_baike",
        "title": person_name,
        "summary": summary,
        "url": url,
    }


def _normalize_places(raw_places: object) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if isinstance(raw_places, list):
        for item in raw_places:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    items.append({"name": name, "context": ""})
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("place") or "").strip()
                context = str(item.get("context") or item.get("event") or "").strip()
                if name:
                    items.append({"name": name, "context": context})
    return items


def default_search_person_info(
    person_name: str,
    *,
    llm: object = None,
) -> Dict[str, object]:
    enable_web = (os.getenv("STORY_AGENT_ENABLE_WEB_RESEARCH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    sources: List[SearchSource] = []
    if enable_web:
        wiki = _wikipedia_summary(person_name)
        if wiki:
            sources.append(wiki)
        baike = _baidu_baike_summary(person_name)
        if baike:
            sources.append(baike)
    snippets = "\n\n".join(
        f"[{item.get('source')}] {item.get('title')}\n{item.get('summary')}" for item in sources if item.get("summary")
    )
    result: Dict[str, object] = {
        "person": person_name,
        "sources": sources,
        "source_names": [str(item.get("source") or "") for item in sources],
        "dynasty": "",
        "summary": "",
        "short_review_candidate": "",
        "identities": [],
        "achievements": [],
        "timeline": [],
        "places": [],
        "cautions": [],
    }
    if llm is None:
        if sources:
            result["summary"] = " ".join(str(item.get("summary") or "") for item in sources[:2]).strip()
            result["dynasty"] = _infer_dynasty(result["summary"])
        return result
    search_prompt = (
        "你是 SearchAgent，只负责把人物资料整理成结构化 JSON，不要输出 Markdown。\n"
        "请输出 JSON，schema 为：\n"
        "{\n"
        '  "dynasty": "所处时代/朝代",\n'
        '  "summary": "120字内摘要",\n'
        '  "short_review_candidate": "适合放在人物名下的一句短评、史家评价或代表作品短句，尽量简短",\n'
        '  "identities": ["主要身份"],\n'
        '  "achievements": ["主要成就"],\n'
        '  "timeline": [{"year": "年份", "event": "事件", "place": "地点"}],\n'
        '  "places": [{"name": "地名", "context": "与人物关系"}],\n'
        '  "cautions": ["存疑点"]\n'
        "}\n"
        "有外部资料片段时优先基于片段整理；没有片段时可依据常识谨慎整理，但不确定信息必须写入 cautions。"
    )
    user_prompt = f"人物：{person_name}\n\n外部资料片段：\n{snippets or '暂无外部资料片段，请谨慎整理。'}"
    raw = _llm_think(
        llm,
        [
            {"role": "system", "content": search_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        timeout_seconds=_SEARCH_LLM_TIMEOUT_SECONDS,
    )
    payload = parse_json_payload(raw or "")
    if not payload:
        result["dynasty"] = _infer_dynasty(snippets, raw)
        result["summary"] = (raw or "").strip()
        return result
    result["dynasty"] = str(payload.get("dynasty") or "").strip() or _infer_dynasty(payload.get("summary"), snippets, raw)
    result["summary"] = str(payload.get("summary") or "").strip()
    result["short_review_candidate"] = str(payload.get("short_review_candidate") or "").strip()
    result["identities"] = [str(item).strip() for item in payload.get("identities") or [] if str(item).strip()]
    result["achievements"] = [str(item).strip() for item in payload.get("achievements") or [] if str(item).strip()]
    result["timeline"] = [item for item in payload.get("timeline") or [] if isinstance(item, dict)]
    result["places"] = _normalize_places(payload.get("places"))
    result["cautions"] = [str(item).strip() for item in payload.get("cautions") or [] if str(item).strip()]
    return result


def default_queue_hard_place_review(payload: Dict[str, object]) -> Dict[str, object]:
    geocode_service_utils = _geocode_service_utils()
    geocode_api_utils = _geocode_api_utils()
    return geocode_api_utils.submit_hard_place_for_review(
        payload,
        geocode_service_utils=geocode_service_utils,
    )


def default_fetch_ancient_place_map(
    place_name: str,
    *,
    queue_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
) -> Dict[str, object]:
    geocode_service_utils = _geocode_service_utils()
    query = str(place_name or "").strip()
    ancient_name, modern_name = geocode_service_utils.split_ancient_modern(query, event_callback=None)
    search_name = parser_utils._pick_geocode_name(modern_name or query)
    coord = geocode_service_utils.lookup_coords_from_historical_index(query, ancient_name, modern_name, search_name)
    source = "historical_index"
    if not coord and search_name:
        coord = geocode_service_utils.resolve_place_coord(search_name, None, query, ancient_name, modern_name)
        source = "geocode"
    review_result: Dict[str, object] = {}
    if not coord and callable(queue_review_fn) and query:
        try:
            review_result = queue_review_fn(
                {
                    "place_name": query,
                    "reason": "geocode_failed",
                }
            )
        except Exception:
            review_result = {}
    return {
        "query": query,
        "ancient_name": ancient_name or query,
        "modern_name": modern_name or search_name or query,
        "lat": coord[0] if coord else None,
        "lng": coord[1] if coord else None,
        "source": source if coord else "",
        "review_queued": bool(review_result.get("queued")),
        "review_status": str(review_result.get("status") or ""),
        "review_item_id": str(review_result.get("review_item_id") or ""),
        "review_target": str(review_result.get("queue_path") or ""),
        "review_reason": str(review_result.get("reason") or ""),
    }


def default_generate_markdown(structure: Dict[str, object], *, llm: object = None) -> str:
    if llm is None:
        return str(structure.get("previous_draft") or "")
    system_prompt = _read_prompt("story_system_prompt.md")
    research = json.dumps(structure.get("search_result") or {}, ensure_ascii=False, indent=2)
    place_maps = json.dumps(structure.get("place_maps") or [], ensure_ascii=False, indent=2)
    critic_feedback = json.dumps(structure.get("critic_feedback") or [], ensure_ascii=False, indent=2)
    runtime_reflection = str(structure.get("runtime_reflection_prompt") or "").strip()
    reflection = runtime_reflection or "运行时反思：\n- 当前状态：stable"
    user_prompt = (
        f"请根据以下结构化资料生成历史人物「{structure.get('person') or ''}」的最终 Markdown。\n\n"
        f"检索资料：\n{research}\n\n"
        f"古今地名映射：\n{place_maps}\n\n"
        f"Critic 反馈（若为空则代表首稿）：\n{critic_feedback}\n\n"
        f"{reflection}\n\n"
        "要求：\n"
        "1. 严格遵守系统提示词版式；\n"
        "2. 如果 Critic 提示某个地点不够精确，要在正文和时间线里补出现代地名；\n"
        "3. 如果资料有存疑点，用“存疑/说法不一”表达，不要编造；\n"
        "4. 如果 Critic 指出误引、张冠李戴，或把作品说明误写成“名篇名句”，要改成更准确的栏目和措辞；\n"
        "5. 如果检索资料里有 short_review_candidate，优先把它放入“### 历史评价”的第一条，保持一句话短评风格；\n"
        "6. 优先吸收运行时反思里的瓶颈与下一步动作，避免重复上一轮失败模式。"
    )
    markdown = _llm_think(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        timeout_seconds=_EDITOR_LLM_TIMEOUT_SECONDS,
    ) or ""
    candidate = dict(structure.get("search_result") or {}).get("short_review_candidate")
    return _ensure_short_review_in_markdown(markdown, candidate)


def create_agent_tools(
    *,
    llm: object = None,
    search_person_info_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    fetch_ancient_place_map_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    queue_hard_place_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
    generate_markdown_fn: Optional[Callable[[Dict[str, object]], str]] = None,
    validate_markdown_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    memory_store: Optional[StoryAgentMemoryStore] = None,
) -> Dict[str, Callable[..., object]]:
    store = memory_store
    search_impl = search_person_info_fn or (lambda person_name: default_search_person_info(person_name, llm=llm))
    queue_impl = queue_hard_place_review_fn or default_queue_hard_place_review
    map_impl = fetch_ancient_place_map_fn or (lambda place_name: default_fetch_ancient_place_map(place_name, queue_review_fn=queue_impl))
    editor_impl = generate_markdown_fn or (lambda structure: default_generate_markdown(structure, llm=llm))
    critic_impl = validate_markdown_fn or (lambda content: default_validate_markdown(content, person="", llm=llm))
    search_uses_llm = _tool_uses_llm(search_person_info_fn, default_uses_llm=llm is not None)
    editor_uses_llm = _tool_uses_llm(generate_markdown_fn, default_uses_llm=llm is not None)
    critic_uses_llm = validate_markdown_fn is None and _fact_check_llm_enabled(llm)
    search_tags = ["research"]
    if search_uses_llm:
        search_tags.append("llm")
    editor_permission = "model_call" if editor_uses_llm else "read"
    editor_tags = ["editor"]
    if editor_uses_llm:
        editor_tags.append("llm")
    critic_permission = "model_call" if critic_uses_llm else "read"
    critic_tags = ["critic", "quality"]
    if critic_uses_llm:
        critic_tags.append("llm_optional")

    @tool(
        name="search_person_info",
        description="检索人物资料，并整理为结构化信息片段",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": ["person", "summary", "identities", "achievements", "timeline", "places", "cautions"],
        },
        timeout_seconds=float(_SEARCH_LLM_TIMEOUT_SECONDS),
        retry_count=2,
        cost_tier="medium",
        permission="network_read",
        tags=search_tags,
    )
    def search_person_info(person_name: str) -> Dict[str, object]:
        if store is not None:
            cached = store.get_person_search(person_name)
            if isinstance(cached, dict) and cached.get("person"):
                set_memory_access(search_person_info, bucket="search", hit=True)
                return cached
        set_memory_access(search_person_info, bucket="search", hit=False)
        result = search_impl(person_name)
        if store is not None and isinstance(result, dict) and result.get("person"):
            store.set_person_search(person_name, result)
        return result

    @tool(
        name="fetch_ancient_place_map",
        description="查询古今地名映射与现代坐标",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": ["query", "ancient_name", "modern_name", "lat", "lng", "source"],
        },
        timeout_seconds=15.0,
        retry_count=1,
        cost_tier="low",
        permission="network_read",
        tags=["map", "geocode"],
    )
    def fetch_ancient_place_map(place_name: str) -> Dict[str, object]:
        if store is not None:
            cached = store.get_place_map(place_name)
            if isinstance(cached, dict) and cached.get("query"):
                set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=True)
                return cached
        set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=False)
        result = map_impl(place_name)
        if store is not None and isinstance(result, dict) and result.get("query"):
            store.set_place_map(place_name, result)
        return result

    @tool(
        name="queue_hard_place_review",
        description="将无法稳定解析坐标的地点投递到人工审核队列",
        input_schema={
            "type": "object",
            "required": ["place_name"],
            "properties": {
                "place_name": {"type": "string"},
                "person": {"type": "string"},
                "context": {"type": "string"},
                "reason": {"type": "string"},
                "queue_json_path": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["status", "queued", "raw_place", "normalized_place_key", "recommended_search_name", "review_item_id", "queue_path", "reason"],
        },
        timeout_seconds=8.0,
        retry_count=0,
        cost_tier="low",
        permission="write",
        tags=["map", "review_queue"],
    )
    def queue_hard_place_review(payload: Dict[str, object]) -> Dict[str, object]:
        return queue_impl(payload)

    @tool(
        name="generate_markdown",
        description="根据结构化资料与反馈生成最终 Markdown",
        input_schema={
            "type": "object",
            "required": ["person", "plan", "search_result", "place_maps", "critic_feedback", "previous_draft"],
        },
        output_schema={"type": "string"},
        timeout_seconds=float(_EDITOR_LLM_TIMEOUT_SECONDS),
        retry_count=0,
        cost_tier="high",
        permission=editor_permission,
        tags=editor_tags,
    )
    def generate_markdown(structure: Dict[str, object]) -> str:
        return editor_impl(structure)

    @tool(
        name="validate_markdown",
        description="检查 Markdown 的完整性、一致性与地名精度",
        input_schema={"type": "string"},
        output_schema={"type": "object", "required": ["pass", "risk_level", "issues", "notes"]},
        timeout_seconds=20.0,
        retry_count=0,
        cost_tier="low",
        permission=critic_permission,
        tags=critic_tags,
    )
    def validate_markdown(content: str) -> Dict[str, object]:
        return critic_impl(content)

    return {
        "search_person_info": search_person_info,
        "fetch_ancient_place_map": fetch_ancient_place_map,
        "queue_hard_place_review": queue_hard_place_review,
        "generate_markdown": generate_markdown,
        "validate_markdown": validate_markdown,
    }


def list_agent_tools(tools: Dict[str, Callable[..., object]]) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for key, func in tools.items():
        meta = getattr(func, "__tool__", None)
        if meta is None:
            continue
        items.append(
            {
                "key": key,
                "name": meta.name,
                "description": meta.description,
                "timeout_seconds": meta.timeout_seconds,
                "retry_count": meta.retry_count,
                "cost_tier": meta.cost_tier,
                "permission": meta.permission,
                "tags": list(meta.tags),
            }
        )
    return items


def _infer_dynasty(*texts: object) -> str:
    for value in texts:
        content = str(value or "").strip()
        if not content:
            continue
        for token in _DYNASTY_TOKENS:
            if token in content:
                return token
    return ""


def _extract_places_for_mapping(state: StoryAgentState) -> List[str]:
    search_result = state.get("search_result") or {}
    places_raw = search_result.get("places") if isinstance(search_result, dict) else []
    timeline_raw = search_result.get("timeline") if isinstance(search_result, dict) else []
    places: List[str] = []
    for item in _normalize_places(places_raw):
        name = str(item.get("name") or "").strip()
        if name:
            places.append(name)
    if isinstance(timeline_raw, list):
        for item in timeline_raw:
            if not isinstance(item, dict):
                continue
            place_name = str(item.get("place") or item.get("name") or item.get("location") or "").strip()
            if place_name:
                places.append(place_name)
    for issue in state.get("critic_feedback") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("field") or "").strip() not in {"location", "timeline"}:
            continue
        claim = str(issue.get("claim") or "").strip()
        if not claim:
            continue
        segments = re.split(r"[|｜/、；;，,\n]", claim)
        for segment in segments:
            candidate = re.split(r"[（(]", segment, maxsplit=1)[0].strip()
            if not candidate:
                continue
            if len(candidate) < 2 or len(candidate) > 30:
                continue
            if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{2,30}", candidate):
                continue
            if re.search(r"\d", candidate):
                continue
            if any(
                marker in candidate
                for marker in (
                    "补充",
                    "对应",
                    "改成",
                    "改为",
                    "替换",
                    "不要",
                    "现代地名",
                    "古地理",
                    "现代参照",
                    "单一现代城市",
                    "时间线",
                    "地点",
                    "地名",
                    "出生地",
                    "去世地",
                    "事件",
                    "条目",
                    "范围",
                )
            ):
                continue
            places.append(candidate)
    deduped: List[str] = []
    seen = set()
    for place in places:
        if place in seen:
            continue
        seen.add(place)
        deduped.append(place)
    return deduped


def _build_editor_structure(state: StoryAgentState) -> Dict[str, object]:
    runtime_reflection = build_runtime_reflection(state)
    return {
        "person": state.get("person") or "",
        "plan": state.get("plan") or [],
        "search_result": state.get("search_result") or {},
        "place_maps": state.get("place_maps") or [],
        "critic_feedback": state.get("critic_feedback") or [],
        "previous_draft": state.get("draft_markdown") or "",
        "runtime_reflection": runtime_reflection,
        "runtime_reflection_prompt": build_runtime_reflection_prompt(state),
    }


def _supervisor_node_factory(llm: object) -> Callable[[StoryAgentState], StoryAgentState]:
    def supervisor_node(state: StoryAgentState) -> StoryAgentState:
        return build_supervisor_update(state, emit=lambda message: _emit(llm, message))

    return supervisor_node


def _search_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    def search_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "search_agent")
        _emit(llm, f"🔎 SearchAgent：检索 {state.get('person') or ''} 的资料")
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)
        try:
            tool_run = call_tool(
                state,
                tools["search_person_info"],
                str(state.get("person") or ""),
                agent_step="search_agent",
            )
            search_result = tool_run["result"]
            tool_traces = tool_run["tool_traces"]
            llm_calls_used = tool_run["llm_calls_used"]
            memory_access = tool_run["memory_access"]
            memory_hits, memory_misses = update_memory_counters(state, memory_access)
        except ToolCallError as exc:
            degraded_reasons = record_degraded_reason(degraded_reasons, f"search_agent:{exc}")
            tool_traces = list(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            search_result = fallback_search_result(str(state.get("person") or ""), state)
            _emit(llm, "⚠️ SearchAgent 失败，已回退为最小检索结果")
        return {
            "search_result": search_result if isinstance(search_result, dict) else {},
            "needs_redraft": bool(state.get("draft_markdown")),
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return search_agent_node


def _map_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    def map_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "map_agent")
        places = _extract_places_for_mapping(state)
        _emit(llm, f"🗺️ MapAgent：校正 {len(places)} 个地点")
        place_maps: List[Dict[str, object]] = []
        tool_traces = list(state.get("tool_traces") or [])
        degraded_reasons = list(state.get("degraded_reasons") or [])
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        memory_hits, memory_misses = copy_memory_counters(state)
        working_state: StoryAgentState = dict(state)
        working_state["tool_traces"] = tool_traces
        working_state["llm_calls_used"] = llm_calls_used
        for place in places:
            try:
                tool_run = call_tool(
                    working_state,
                    tools["fetch_ancient_place_map"],
                    place,
                    agent_step="map_agent",
                )
                info = tool_run["result"]
                tool_traces = tool_run["tool_traces"]
                llm_calls_used = tool_run["llm_calls_used"]
                memory_access = tool_run["memory_access"]
                working_state["tool_traces"] = tool_traces
                working_state["llm_calls_used"] = llm_calls_used
                memory_hits, memory_misses = update_memory_counters(
                    {"memory_hits": memory_hits, "memory_misses": memory_misses},
                    memory_access,
                )
            except ToolCallError as exc:
                tool_traces = list(exc.tool_traces or [])
                llm_calls_used = int(exc.llm_calls_used)
                working_state["tool_traces"] = tool_traces
                working_state["llm_calls_used"] = llm_calls_used
                degraded_reasons = record_degraded_reason(degraded_reasons, f"map_agent:{place}:{exc}")
                info = {
                    "query": place,
                    "ancient_name": place,
                    "modern_name": place,
                    "lat": None,
                    "lng": None,
                    "source": "",
                }
            except Exception as exc:
                degraded_reasons = record_degraded_reason(degraded_reasons, f"map_agent:{place}:{exc}")
                info = {
                    "query": place,
                    "ancient_name": place,
                    "modern_name": place,
                    "lat": None,
                    "lng": None,
                    "source": "",
                }
            if isinstance(info, dict):
                place_maps.append(info)
        return {
            "place_maps": place_maps,
            "needs_redraft": bool(state.get("draft_markdown")),
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "degraded_reasons": degraded_reasons,
            "llm_calls_used": llm_calls_used,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return map_agent_node


def _editor_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    def editor_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "editor_agent")
        _emit(llm, "📝 EditorAgent：生成或修订 Markdown")
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)
        try:
            tool_run = call_tool(
                state,
                tools["generate_markdown"],
                _build_editor_structure(state),
                agent_step="editor_agent",
            )
            draft_markdown = tool_run["result"]
            tool_traces = tool_run["tool_traces"]
            llm_calls_used = tool_run["llm_calls_used"]
        except ToolCallError as exc:
            degraded_reasons = record_degraded_reason(degraded_reasons, f"editor_agent:{exc}")
            tool_traces = list(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            draft_markdown = fallback_generate_markdown(_build_editor_structure(state), infer_dynasty=_infer_dynasty)
            _emit(llm, "⚠️ EditorAgent 失败，已回退为确定性 Markdown 组装")
        draft_markdown = _ensure_short_review_in_markdown(
            str(draft_markdown or ""),
            dict(state.get("search_result") or {}).get("short_review_candidate"),
        )
        return {
            "draft_markdown": str(draft_markdown or ""),
            "validation": {},
            "needs_redraft": False,
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }

    return editor_agent_node


def _critic_agent_node_factory(
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[StoryAgentState], StoryAgentState]:
    def critic_agent_node(state: StoryAgentState) -> StoryAgentState:
        trace = append_trace(state, "critic_agent")
        _emit(llm, "🧪 CriticAgent：检查时间、地点和结构一致性")
        llm_calls_used = int(state.get("llm_calls_used") or 0)
        degraded_reasons = list(state.get("degraded_reasons") or [])
        memory_hits, memory_misses = copy_memory_counters(state)
        try:
            tool_run = call_tool(
                state,
                tools["validate_markdown"],
                str(state.get("draft_markdown") or ""),
                agent_step="critic_agent",
            )
            validation = tool_run["result"]
            tool_traces = tool_run["tool_traces"]
            llm_calls_used = tool_run["llm_calls_used"]
        except ToolCallError as exc:
            degraded_reasons = record_degraded_reason(degraded_reasons, f"critic_agent:{exc}")
            tool_traces = list(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            validation = fallback_validation(
                str(state.get("draft_markdown") or ""),
                person=str(state.get("person") or ""),
                validate_fn=default_validate_markdown,
            )
            _emit(llm, "⚠️ CriticAgent 失败，已回退为确定性校验")
        if not isinstance(validation, dict):
            validation = {"pass": False, "risk_level": "high", "issues": [], "notes": "校验器未返回字典"}
        merged_issues = [item for item in list(validation.get("issues") or []) if isinstance(item, dict)]
        merged_issues.extend(_caution_consistency_issues(str(state.get("draft_markdown") or ""), dict(state.get("search_result") or {}).get("cautions") or []))
        merged_issues = _dedupe_issues(merged_issues)
        validation["issues"] = merged_issues
        validation["risk_level"] = _risk_level_from_issues(merged_issues)
        validation["pass"] = not any(float(item.get("confidence") or 0.0) >= 0.7 for item in merged_issues)
        validation["notes"] = "" if not merged_issues else f"共发现 {len(merged_issues)} 个待核查点"
        feedback = validation.get("issues") or []
        if not isinstance(feedback, list):
            feedback = []
        updates: StoryAgentState = {
            "validation": validation,
            "critic_feedback": [item for item in feedback if isinstance(item, dict)],
            "execution_trace": trace,
            "tool_traces": tool_traces,
            "llm_calls_used": llm_calls_used,
            "degraded_reasons": degraded_reasons,
            "memory_hits": memory_hits,
            "memory_misses": memory_misses,
        }
        if validation.get("pass"):
            updates["final_markdown"] = str(state.get("draft_markdown") or "")
            updates["needs_revision"] = False
            return updates
        if int(state.get("revision_count") or 0) < max_revisions_limit(state):
            updates["revision_count"] = int(state.get("revision_count") or 0) + 1
            updates["needs_revision"] = True
            updates["needs_redraft"] = False
        else:
            updates["needs_revision"] = False
            updates["needs_redraft"] = False
        return updates

    return critic_agent_node


def _finish_agent_node(state: StoryAgentState) -> StoryAgentState:
    trace = append_trace(state, "finish_agent")
    return {
        "final_markdown": str(state.get("final_markdown") or state.get("draft_markdown") or ""),
        "execution_trace": trace,
        "degraded_reasons": list(state.get("degraded_reasons") or []),
        "memory_hits": dict(state.get("memory_hits") or {}),
        "memory_misses": dict(state.get("memory_misses") or {}),
    }


def _next_step_router(state: StoryAgentState) -> str:
    return resolve_next_step(state)


def _build_langgraph_runner(
    *,
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[str, int], Dict[str, object]]:
    workflow = StateGraph(StoryAgentState)
    workflow.add_node("supervisor", _supervisor_node_factory(llm))
    workflow.add_node("search_agent", _search_agent_node_factory(tools, llm))
    workflow.add_node("map_agent", _map_agent_node_factory(tools, llm))
    workflow.add_node("editor_agent", _editor_agent_node_factory(tools, llm))
    workflow.add_node("critic_agent", _critic_agent_node_factory(tools, llm))
    workflow.add_node("finish_agent", _finish_agent_node)
    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _next_step_router,
        {
            "search_agent": "search_agent",
            "map_agent": "map_agent",
            "editor_agent": "editor_agent",
            "critic_agent": "critic_agent",
            "finish_agent": "finish_agent",
        },
    )
    workflow.add_edge("search_agent", "supervisor")
    workflow.add_edge("map_agent", "supervisor")
    workflow.add_edge("editor_agent", "supervisor")
    workflow.add_edge("critic_agent", "supervisor")
    workflow.add_edge("finish_agent", END)
    graph = workflow.compile()

    def run(person: str, max_revisions: int = 1, llm_calls_limit: int = 0) -> Dict[str, object]:
        initial_state = create_initial_state(
            person,
            max_revisions=max_revisions,
            llm_calls_limit=llm_calls_limit,
        )
        final_state = graph.invoke(initial_state)
        if not isinstance(final_state, dict):
            final_state = dict(initial_state)
        return {
            "markdown": str(final_state.get("final_markdown") or final_state.get("draft_markdown") or ""),
            "state": final_state,
        }

    return run


def _build_manual_runner(
    *,
    tools: Dict[str, Callable[..., object]],
    llm: object,
) -> Callable[[str, int], Dict[str, object]]:
    supervisor = _supervisor_node_factory(llm)
    search_agent = _search_agent_node_factory(tools, llm)
    map_agent = _map_agent_node_factory(tools, llm)
    editor_agent = _editor_agent_node_factory(tools, llm)
    critic_agent = _critic_agent_node_factory(tools, llm)

    def run(person: str, max_revisions: int = 1, llm_calls_limit: int = 0) -> Dict[str, object]:
        state = create_initial_state(
            person,
            max_revisions=max_revisions,
            llm_calls_limit=llm_calls_limit,
        )
        # Manual fallback needs enough room for:
        # search -> map -> edit -> critic -> (map/edit/critic * revisions) -> finish.
        max_iterations = max(16, 8 + max(0, int(max_revisions)) * 4)
        finished = False
        for _ in range(max_iterations):
            state = merge_state(state, supervisor(state))
            step = _next_step_router(state)
            if step == "finish_agent":
                state = merge_state(state, _finish_agent_node(state))
                finished = True
                break
            if step == "search_agent":
                state = merge_state(state, search_agent(state))
                continue
            if step == "map_agent":
                state = merge_state(state, map_agent(state))
                continue
            if step == "editor_agent":
                state = merge_state(state, editor_agent(state))
                continue
            if step == "critic_agent":
                state = merge_state(state, critic_agent(state))
                continue
            break
        if not finished:
            state = merge_state(
                state,
                {
                    "degraded_reasons": record_degraded_reason(
                        state.get("degraded_reasons"),
                        f"manual_runner:max_iterations_exceeded:{max_iterations}",
                    )
                },
            )
            state = merge_state(state, _finish_agent_node(state))
        return {
            "markdown": str(state.get("final_markdown") or state.get("draft_markdown") or ""),
            "state": state,
        }

    return run


def create_story_markdown_agent(
    *,
    llm: object = None,
    search_person_info_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    fetch_ancient_place_map_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    queue_hard_place_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
    generate_markdown_fn: Optional[Callable[[Dict[str, object]], str]] = None,
    validate_markdown_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    max_llm_calls: Optional[int] = None,
    memory_store: Optional[StoryAgentMemoryStore] = None,
) -> Dict[str, object]:
    resolved_memory_store = memory_store
    if resolved_memory_store is None:
        memory_enabled = (os.getenv("STORY_AGENT_ENABLE_MEMORY") or "").strip().lower() in {"1", "true", "yes", "on"}
        if memory_enabled:
            resolved_memory_store = get_default_memory_store()
    tools = create_agent_tools(
        llm=llm,
        search_person_info_fn=search_person_info_fn,
        fetch_ancient_place_map_fn=fetch_ancient_place_map_fn,
        queue_hard_place_review_fn=queue_hard_place_review_fn,
        generate_markdown_fn=generate_markdown_fn,
        validate_markdown_fn=validate_markdown_fn,
        memory_store=resolved_memory_store,
    )
    runner = (
        _build_langgraph_runner(tools=tools, llm=llm)
        if _LANGGRAPH_AVAILABLE and StateGraph is not None
        else _build_manual_runner(tools=tools, llm=llm)
    )
    resolved_max_llm_calls = max_llm_calls
    if resolved_max_llm_calls is None:
        resolved_max_llm_calls = int(os.getenv("STORY_AGENT_MAX_LLM_CALLS", "4") or "4")
    def bound_run(person: str, max_revisions: int = 1, llm_calls_limit: Optional[int] = None) -> Dict[str, object]:
        resolved_limit = resolved_max_llm_calls if llm_calls_limit is None else int(llm_calls_limit)
        accepted, reason = classify_story_person_authenticity(person, allow_unknown=True)
        if not accepted:
            return _non_authentic_agent_result(
                str(person or "").strip(),
                str(reason or "").strip(),
                max_revisions=max_revisions,
                llm_calls_limit=resolved_limit,
            )
        return runner(person, max_revisions, resolved_limit)

    return {
        "tools": tools,
        "tool_specs": list_agent_tools(tools),
        "run": bound_run,
        "langgraph_available": _LANGGRAPH_AVAILABLE,
        "max_llm_calls": max(0, int(resolved_max_llm_calls)),
    }


def generate_markdown_with_agents(
    llm: object,
    person: str,
    *,
    max_revisions: Optional[int] = None,
    max_llm_calls: Optional[int] = None,
) -> Dict[str, object]:
    agent = create_story_markdown_agent(llm=llm, max_llm_calls=max_llm_calls)
    resolved_max_revisions = max_revisions
    if resolved_max_revisions is None:
        resolved_max_revisions = int(os.getenv("STORY_AGENT_MAX_REVISIONS", "1") or "1")
    result = agent["run"](person, resolved_max_revisions, agent["max_llm_calls"])
    if not isinstance(result, dict):
        return {"markdown": "", "state": {}, "tool_specs": agent["tool_specs"]}
    result["tool_specs"] = agent["tool_specs"]
    result["langgraph_available"] = agent["langgraph_available"]
    result["max_llm_calls"] = agent["max_llm_calls"]
    return result


__all__ = [
    "create_agent_tools",
    "create_story_markdown_agent",
    "default_fetch_ancient_place_map",
    "default_queue_hard_place_review",
    "default_generate_markdown",
    "default_search_person_info",
    "default_validate_markdown",
    "generate_markdown_with_agents",
    "list_agent_tools",
]

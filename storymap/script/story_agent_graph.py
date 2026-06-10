from __future__ import annotations

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
    from . import generation_service as generation_service_utils
    from . import parsers as parser_utils
    from .story_agent_memory import StoryAgentMemoryStore, get_default_memory_store
    from .story_agent_fallbacks import (
        fallback_generate_markdown,
        fallback_search_result,
        fallback_validation,
    )
    from .story_agent_router import build_supervisor_update, resolve_next_step
    from .story_agent_state import (
        AgentIssue,
        SearchSource,
        StoryAgentState,
        append_trace,
        create_initial_state,
        max_revisions_limit,
        merge_state,
        record_degraded_reason,
    )
    from .story_tooling import invoke_tool, tool
except ImportError:
    import generation_service as generation_service_utils
    import parsers as parser_utils
    from story_agent_memory import StoryAgentMemoryStore, get_default_memory_store
    from story_agent_fallbacks import fallback_generate_markdown, fallback_search_result, fallback_validation
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
    from story_tooling import invoke_tool, tool


class ToolCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        tool_traces: List[Dict[str, object]],
        llm_calls_used: int,
        original: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.tool_traces = list(tool_traces or [])
        self.llm_calls_used = int(llm_calls_used)
        self.original = original


def _set_memory_access(func: Callable[..., object], *, bucket: str, hit: bool) -> None:
    try:
        setattr(func, "__memory_last_access__", {"bucket": str(bucket or "").strip(), "hit": bool(hit)})
    except Exception:
        return


def _consume_memory_access(func: Callable[..., object]) -> Dict[str, object]:
    access = getattr(func, "__memory_last_access__", None)
    try:
        setattr(func, "__memory_last_access__", None)
    except Exception:
        pass
    return dict(access) if isinstance(access, dict) else {}


def _update_memory_counters(
    state: StoryAgentState,
    access: Dict[str, object],
) -> tuple[Dict[str, int], Dict[str, int]]:
    hits = dict(state.get("memory_hits") or {})
    misses = dict(state.get("memory_misses") or {})
    bucket = str(access.get("bucket") or "").strip()
    if not bucket:
        return hits, misses
    if bool(access.get("hit")):
        hits[bucket] = int(hits.get(bucket) or 0) + 1
    else:
        misses[bucket] = int(misses.get(bucket) or 0) + 1
    return hits, misses


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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _geocode_service_utils():
    try:
        from . import geocode_service as geocode_service_utils
    except ImportError:
        import geocode_service as geocode_service_utils
    return geocode_service_utils


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


def _strip_code_fences(text: str) -> str:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", body)
        body = re.sub(r"\n?```$", "", body)
    return body.strip()


def _parse_json_payload(text: str) -> Optional[Dict[str, object]]:
    body = _strip_code_fences(text)
    if not body:
        return None
    candidates = [body]
    match = re.search(r"(\{[\s\S]*\})", body)
    if match:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _coerce_issue(
    *,
    field: str,
    claim: str,
    correction: str,
    confidence: float,
    reason: str,
) -> AgentIssue:
    return {
        "field": field,
        "claim": claim,
        "correction": correction,
        "confidence": round(float(confidence), 3),
        "reason": reason,
    }


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
    match = re.search(r"(-?\d{1,4})\s*年", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_age(text: str) -> Optional[int]:
    match = re.search(r"(\d{1,3})\s*岁", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _needs_modern_hint(text: str) -> bool:
    content = str(text or "").strip()
    if not content:
        return False
    if "今" in content:
        return False
    if re.search(r"(省|市|县|区|州|郡|自治区|特别行政区)", content):
        return False
    return True


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
                _coerce_issue(
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
                _coerce_issue(
                    field="location",
                    claim=birth_text,
                    correction="补充出生地对应的现代地名",
                    confidence=0.68,
                    reason="出生地缺少现代地名提示，后续地图定位容易不稳定",
                )
            )
        if death_text and _needs_modern_hint(death_text):
            issues.append(
                _coerce_issue(
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
                    _coerce_issue(
                        field="location",
                        claim=" | ".join(str(cell or "") for cell in row),
                        correction="为该时间线条目补充现代地名",
                        confidence=0.73,
                        reason="时间线存在古称但缺少现称",
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
            _coerce_issue(
                field="age",
                claim=f"出生 {birth_year} 年，去世 {death_year} 年，享年 {lifespan} 岁",
                correction=f"核对享年是否应为 {estimated} 岁左右",
                confidence=0.88,
                reason="生卒年与享年不自洽",
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
    if llm is None:
        return []
    enabled = (os.getenv("STORY_AGENT_ENABLE_FACT_CHECK_LLM") or "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
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
    raw = llm.think([{"role": "system", "content": prompt}], temperature=0)
    payload = _parse_json_payload(raw or "")
    if not payload:
        return []
    raw_issues = payload.get("issues") or []
    if not isinstance(raw_issues, list):
        return []
    issues: List[AgentIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(
            _coerce_issue(
                field=str(item.get("field") or "other"),
                claim=str(item.get("claim") or ""),
                correction=str(item.get("correction") or ""),
                confidence=float(item.get("confidence") or 0.0),
                reason=str(item.get("reason") or ""),
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
        _coerce_issue(
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
        issues.extend(_lifespan_issues(parsed_doc))
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
        '  "identities": ["主要身份"],\n'
        '  "achievements": ["主要成就"],\n'
        '  "timeline": [{"year": "年份", "event": "事件", "place": "地点"}],\n'
        '  "places": [{"name": "地名", "context": "与人物关系"}],\n'
        '  "cautions": ["存疑点"]\n'
        "}\n"
        "有外部资料片段时优先基于片段整理；没有片段时可依据常识谨慎整理，但不确定信息必须写入 cautions。"
    )
    user_prompt = f"人物：{person_name}\n\n外部资料片段：\n{snippets or '暂无外部资料片段，请谨慎整理。'}"
    raw = llm.think(
        [
            {"role": "system", "content": search_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    payload = _parse_json_payload(raw or "")
    if not payload:
        result["dynasty"] = _infer_dynasty(snippets, raw)
        result["summary"] = (raw or "").strip()
        return result
    result["dynasty"] = str(payload.get("dynasty") or "").strip() or _infer_dynasty(payload.get("summary"), snippets, raw)
    result["summary"] = str(payload.get("summary") or "").strip()
    result["identities"] = [str(item).strip() for item in payload.get("identities") or [] if str(item).strip()]
    result["achievements"] = [str(item).strip() for item in payload.get("achievements") or [] if str(item).strip()]
    result["timeline"] = [item for item in payload.get("timeline") or [] if isinstance(item, dict)]
    result["places"] = _normalize_places(payload.get("places"))
    result["cautions"] = [str(item).strip() for item in payload.get("cautions") or [] if str(item).strip()]
    return result


def default_fetch_ancient_place_map(place_name: str) -> Dict[str, object]:
    geocode_service_utils = _geocode_service_utils()
    query = str(place_name or "").strip()
    ancient_name, modern_name = geocode_service_utils.split_ancient_modern(query, event_callback=None)
    search_name = parser_utils._pick_geocode_name(modern_name or query)
    coord = geocode_service_utils.lookup_coords_from_historical_index(query, ancient_name, modern_name, search_name)
    source = "historical_index"
    if not coord and search_name:
        coord = geocode_service_utils.resolve_place_coord(search_name, None, query, ancient_name, modern_name)
        source = "geocode"
    return {
        "query": query,
        "ancient_name": ancient_name or query,
        "modern_name": modern_name or search_name or query,
        "lat": coord[0] if coord else None,
        "lng": coord[1] if coord else None,
        "source": source if coord else "",
    }


def default_generate_markdown(structure: Dict[str, object], *, llm: object = None) -> str:
    if llm is None:
        return str(structure.get("previous_draft") or "")
    system_prompt = _read_prompt("story_system_prompt.md")
    research = json.dumps(structure.get("search_result") or {}, ensure_ascii=False, indent=2)
    place_maps = json.dumps(structure.get("place_maps") or [], ensure_ascii=False, indent=2)
    critic_feedback = json.dumps(structure.get("critic_feedback") or [], ensure_ascii=False, indent=2)
    user_prompt = (
        f"请根据以下结构化资料生成历史人物「{structure.get('person') or ''}」的最终 Markdown。\n\n"
        f"检索资料：\n{research}\n\n"
        f"古今地名映射：\n{place_maps}\n\n"
        f"Critic 反馈（若为空则代表首稿）：\n{critic_feedback}\n\n"
        "要求：\n"
        "1. 严格遵守系统提示词版式；\n"
        "2. 如果 Critic 提示某个地点不够精确，要在正文和时间线里补出现代地名；\n"
        "3. 如果资料有存疑点，用“存疑/说法不一”表达，不要编造。"
    )
    return llm.think(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    ) or ""


def create_agent_tools(
    *,
    llm: object = None,
    search_person_info_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    fetch_ancient_place_map_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    generate_markdown_fn: Optional[Callable[[Dict[str, object]], str]] = None,
    validate_markdown_fn: Optional[Callable[[str], Dict[str, object]]] = None,
    memory_store: Optional[StoryAgentMemoryStore] = None,
) -> Dict[str, Callable[..., object]]:
    store = memory_store
    search_impl = search_person_info_fn or (lambda person_name: default_search_person_info(person_name, llm=llm))
    map_impl = fetch_ancient_place_map_fn or default_fetch_ancient_place_map
    editor_impl = generate_markdown_fn or (lambda structure: default_generate_markdown(structure, llm=llm))
    critic_impl = validate_markdown_fn or (lambda content: default_validate_markdown(content, person="", llm=llm))

    @tool(
        name="search_person_info",
        description="检索人物资料，并整理为结构化信息片段",
        input_schema={"type": "string"},
        output_schema={
            "type": "object",
            "required": ["person", "summary", "identities", "achievements", "timeline", "places", "cautions"],
        },
        timeout_seconds=25.0,
        retry_count=2,
        cost_tier="medium",
        permission="network_read",
        tags=["research", "llm"],
    )
    def search_person_info(person_name: str) -> Dict[str, object]:
        if store is not None:
            cached = store.get_person_search(person_name)
            if isinstance(cached, dict) and cached.get("person"):
                _set_memory_access(search_person_info, bucket="search", hit=True)
                return cached
        _set_memory_access(search_person_info, bucket="search", hit=False)
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
                _set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=True)
                return cached
        _set_memory_access(fetch_ancient_place_map, bucket="place_map", hit=False)
        result = map_impl(place_name)
        if store is not None and isinstance(result, dict) and result.get("query"):
            store.set_place_map(place_name, result)
        return result

    @tool(
        name="generate_markdown",
        description="根据结构化资料与反馈生成最终 Markdown",
        input_schema={
            "type": "object",
            "required": ["person", "plan", "search_result", "place_maps", "critic_feedback", "previous_draft"],
        },
        output_schema={"type": "string"},
        timeout_seconds=60.0,
        retry_count=1,
        cost_tier="high",
        permission="model_call",
        tags=["editor", "llm"],
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
        permission="read",
        tags=["critic", "quality"],
    )
    def validate_markdown(content: str) -> Dict[str, object]:
        return critic_impl(content)

    return {
        "search_person_info": search_person_info,
        "fetch_ancient_place_map": fetch_ancient_place_map,
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


def _tool_meta(func: Callable[..., object]) -> object:
    return getattr(func, "__tool__", None)


def _tool_tags(func: Callable[..., object]) -> set[str]:
    meta = _tool_meta(func)
    raw = getattr(meta, "tags", ()) if meta is not None else ()
    return {str(item).strip() for item in raw if str(item).strip()}


def _is_llm_tool(func: Callable[..., object]) -> bool:
    tags = _tool_tags(func)
    return bool({"llm", "llm_optional"} & tags)


def _check_and_consume_llm_budget(
    state: StoryAgentState,
    func: Callable[..., object],
) -> int:
    if not _is_llm_tool(func):
        return int(state.get("llm_calls_used") or 0)
    used = int(state.get("llm_calls_used") or 0)
    limit = max(0, int(state.get("llm_calls_limit") or 0))
    if used >= limit:
        raise RuntimeError(f"LLM_CALL_BUDGET_EXCEEDED:{used}/{limit}")
    return used + 1


def _call_tool(
    state: StoryAgentState,
    func: Callable[..., object],
    payload: object,
) -> tuple[object, List[Dict[str, object]], int, Dict[str, object]]:
    tool_traces = list(state.get("tool_traces") or [])
    llm_calls_used = int(state.get("llm_calls_used") or 0)
    previous_trace_count = len(tool_traces)
    try:
        llm_calls_used = _check_and_consume_llm_budget(state, func)
        result = invoke_tool(func, payload, trace_collector=tool_traces)
    except Exception as exc:
        raise ToolCallError(
            str(exc),
            tool_traces=tool_traces,
            llm_calls_used=llm_calls_used,
            original=exc if isinstance(exc, Exception) else None,
        ) from exc
    memory_access = _consume_memory_access(func)
    if memory_access and len(tool_traces) > previous_trace_count and isinstance(tool_traces[-1], dict):
        tool_traces[-1]["memory_bucket"] = str(memory_access.get("bucket") or "")
        tool_traces[-1]["memory_hit"] = bool(memory_access.get("hit"))
    return result, tool_traces, llm_calls_used, memory_access


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
    places: List[str] = []
    for item in _normalize_places(places_raw):
        name = str(item.get("name") or "").strip()
        if name:
            places.append(name)
    for issue in state.get("critic_feedback") or []:
        for key in ("correction", "claim"):
            text = str(issue.get(key) or "").strip()
            if not text:
                continue
            match = re.search(r"([\u4e00-\u9fffA-Za-z·]{2,30})", text)
            if match:
                places.append(match.group(1))
    deduped: List[str] = []
    seen = set()
    for place in places:
        if place in seen:
            continue
        seen.add(place)
        deduped.append(place)
    return deduped[:10]


def _build_editor_structure(state: StoryAgentState) -> Dict[str, object]:
    return {
        "person": state.get("person") or "",
        "plan": state.get("plan") or [],
        "search_result": state.get("search_result") or {},
        "place_maps": state.get("place_maps") or [],
        "critic_feedback": state.get("critic_feedback") or [],
        "previous_draft": state.get("draft_markdown") or "",
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
        memory_hits = dict(state.get("memory_hits") or {})
        memory_misses = dict(state.get("memory_misses") or {})
        try:
            search_result, tool_traces, llm_calls_used, memory_access = _call_tool(
                state,
                tools["search_person_info"],
                str(state.get("person") or ""),
            )
            memory_hits, memory_misses = _update_memory_counters(state, memory_access)
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
        memory_hits = dict(state.get("memory_hits") or {})
        memory_misses = dict(state.get("memory_misses") or {})
        working_state: StoryAgentState = dict(state)
        working_state["tool_traces"] = tool_traces
        working_state["llm_calls_used"] = llm_calls_used
        for place in places:
            try:
                info, tool_traces, llm_calls_used, memory_access = _call_tool(working_state, tools["fetch_ancient_place_map"], place)
                working_state["tool_traces"] = tool_traces
                working_state["llm_calls_used"] = llm_calls_used
                memory_hits, memory_misses = _update_memory_counters(
                    {"memory_hits": memory_hits, "memory_misses": memory_misses},
                    memory_access,
                )
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
        memory_hits = dict(state.get("memory_hits") or {})
        memory_misses = dict(state.get("memory_misses") or {})
        try:
            draft_markdown, tool_traces, llm_calls_used, _memory_access = _call_tool(
                state,
                tools["generate_markdown"],
                _build_editor_structure(state),
            )
        except ToolCallError as exc:
            degraded_reasons = record_degraded_reason(degraded_reasons, f"editor_agent:{exc}")
            tool_traces = list(exc.tool_traces or [])
            llm_calls_used = int(exc.llm_calls_used)
            draft_markdown = fallback_generate_markdown(_build_editor_structure(state), infer_dynasty=_infer_dynasty)
            _emit(llm, "⚠️ EditorAgent 失败，已回退为确定性 Markdown 组装")
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
        memory_hits = dict(state.get("memory_hits") or {})
        memory_misses = dict(state.get("memory_misses") or {})
        try:
            validation, tool_traces, llm_calls_used, _memory_access = _call_tool(
                state,
                tools["validate_markdown"],
                str(state.get("draft_markdown") or ""),
            )
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
        for _ in range(16):
            state = merge_state(state, supervisor(state))
            step = _next_step_router(state)
            if step == "finish_agent":
                state = merge_state(state, _finish_agent_node(state))
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
    "default_generate_markdown",
    "default_search_person_info",
    "default_validate_markdown",
    "generate_markdown_with_agents",
    "list_agent_tools",
]

"""
storymap 历史人物生成管线的默认工具集。

本模块提供 legacy_agent 管线中使用的各项默认工具函数，包括：
- 短评候选文本的清洗与 Markdown 注入
- 外部知识源（维基百科、百度百科）的摘要拉取
- 古今地名映射与坐标解析
- 基于 LLM 的人物结构化信息搜索
- 基于 LLM 的 Markdown 传记生成
- 朝代推断辅助逻辑

所有工具函数均设计为可被外部调用方替换或组合使用。
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

import requests

from ...core import parsers as parser_utils
from .common import _llm_think, _read_prompt
from .constants import _DYNASTY_TOKENS, _EDITOR_LLM_TIMEOUT_SECONDS, _SEARCH_LLM_TIMEOUT_SECONDS


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：短评候选文本的清洗
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_short_review_candidate(text: object, *, limit: int = 60) -> str:
    """清洗 LLM 输出的短评候选文本，去除前缀标记和多余空白。

    处理以下清洗步骤：
    1. 去除首尾空白
    2. 去除行首的列表标记（- * •）
    3. 循环去除「人物短评：」或「短评：」前缀
    4. 合并连续空白为单个空格
    5. 截断超长文本，在末尾加「…」

    Args:
        text: 待清洗的原始文本，可以是任意类型（会转为字符串处理）。
        limit: 最大字符数限制，超过则截断并追加省略号。默认 60。

    Returns:
        清洗后的短评字符串。如果清洗后为空，则返回空字符串。
    """
    # ── 步骤 1：基础清洗 —— 转字符串、去首尾空白、去列表标记 ──
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)

    # ── 步骤 2：循环去除「短评」前缀 ──
    # LLM 可能输出 "短评：xxx" 或 "人物短评：xxx" 格式，需递归剥离
    while True:
        normalized = re.sub(r"^\s*(?:人物)?短评[：:]\s*", "", cleaned)
        if normalized == cleaned:
            break
        cleaned = normalized.strip()

    # ── 步骤 3：空白合并与长度截断 ──
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：将短评注入 Markdown 传记
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_short_review_in_markdown(markdown: str, candidate: object) -> str:
    """确保短评已注入到 Markdown 传记的「历史评价」小节中。

    优先在「### 历史评价」标题后插入；若该标题不存在，则在「## 五、历史影响」
    章节末尾追加「### 历史评价」子标题并插入短评。

    Args:
        markdown: 完整的 Markdown 传记正文。
        candidate: 短评候选文本（会先经 _clean_short_review_candidate 清洗）。

    Returns:
        已注入短评的 Markdown 字符串。若短评为空或已存在于正文中则原样返回。
    """
    body = str(markdown or "")
    review = _clean_short_review_candidate(candidate)
    if not body.strip() or not review:
        return body
    if review in body:
        return body

    # ── 步骤 1：定位关键章节标题 ──
    lines = body.splitlines()
    history_idx = None  # 「### 历史评价」所在行号
    impact_idx = None   # 「## 五、历史影响」所在行号
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## 五、历史影响":
            impact_idx = idx
        if stripped == "### 历史评价":
            history_idx = idx
            break

    bullet = f"- 短评：{review}"

    # ── 步骤 2：在「历史评价」标题后插入 ──
    if history_idx is not None:
        # 跳过标题行后的空行，将短评插入到第一个有效内容行之前
        insert_at = history_idx + 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        lines.insert(insert_at, bullet)
        return "\n".join(lines)

    # ── 步骤 3：「历史评价」不存在时，在「历史影响」章节末尾追加 ──
    if impact_idx is not None:
        # 找到该章节结束位置（下一个 ## 标题之前）
        insert_at = impact_idx + 1
        while insert_at < len(lines):
            stripped = lines[insert_at].strip()
            if stripped.startswith("## "):
                break
            insert_at += 1
        # 在章节末尾插入「### 历史评价」子标题和短评
        block = ["", "### 历史评价", bullet]
        lines[insert_at:insert_at] = block
        return "\n".join(lines)

    # 两个定位标题都不存在，不做修改
    return body


from .llm_parser import parse_json_payload
from .state import SearchSource


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：延迟导入地图相关模块（避免循环依赖）
# ═══════════════════════════════════════════════════════════════════════════════

def _geocode_service_utils():
    """延迟导入 geocode_service 工具模块。

    Returns:
        geocode_service 模块对象。
    """
    from ...map import geocode_service as geocode_service_utils
    return geocode_service_utils


def _geocode_api_utils():
    """延迟导入 geocode_api 工具模块。

    Returns:
        geocode_api 模块对象。
    """
    from ...map import geocode_api as story_geocode_api_utils
    return story_geocode_api_utils


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：短评候选文本的清洗（重复定义，覆盖前文同名函数）
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_short_review_candidate(text: object, *, limit: int = 60) -> str:
    """清洗 LLM 输出的短评候选文本（与前文同名函数逻辑一致，此处为重复定义）。

    由于 Python 按定义顺序覆盖，此定义会覆盖前文的同名函数。

    Args:
        text: 待清洗的原始文本。
        limit: 最大字符数限制，默认 60。

    Returns:
        清洗后的短评字符串。
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：外部知识源摘要拉取
# ═══════════════════════════════════════════════════════════════════════════════

def _wikipedia_summary(person_name: str, timeout: int = 8) -> Optional[SearchSource]:
    """从中文维基百科 API 拉取人物摘要。

    使用 REST API 的 /page/summary 端点获取页面的 extract（摘要文本）。

    Args:
        person_name: 人物姓名，用于构造 API URL。
        timeout: 请求超时时间（秒），默认 8。

    Returns:
        包含 source / title / summary / url 字段的字典，若请求失败或摘要为空则返回 None。
    """
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
    """从百度百科页面拉取人物摘要。

    通过解析 HTML 中的 meta description 标签提取摘要文本。

    Args:
        person_name: 人物姓名，用于构造百科 URL。
        timeout: 请求超时时间（秒），默认 8。

    Returns:
        包含 source / title / summary / url 字段的字典，若请求失败或摘要为空则返回 None。
    """
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

    # ── 步骤 1：从 HTML meta 标签提取描述 ──
    html = resp.text
    # 优先匹配标准 meta description
    match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.I)
    if not match:
        # 回退匹配 Open Graph description
        match = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html, re.I)
    if not match:
        return None

    # ── 步骤 2：清洗摘要文本 ──
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    if not summary:
        return None
    return {
        "source": "baidu_baike",
        "title": person_name,
        "summary": summary,
        "url": url,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：地名数据结构归一化
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_places(raw_places: object) -> List[Dict[str, str]]:
    """将 LLM 输出的地点数据归一化为统一格式。

    支持两种输入格式：
    - 字符串列表：["长安", "洛阳"] → [{"name": "长安", "context": ""}]
    - 字典列表：[{"name": "长安", "context": "建都"}] → 原样保留

    Args:
        raw_places: 原始地点数据，可为列表或任意类型。

    Returns:
        归一化后的地点字典列表，每个元素包含 name 和 context 字段。
    """
    items: List[Dict[str, str]] = []
    if isinstance(raw_places, list):
        for item in raw_places:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    items.append({"name": name, "context": ""})
            elif isinstance(item, dict):
                # 兼容 name / place 两种键名，以及 context / event 两种键名
                name = str(item.get("name") or item.get("place") or "").strip()
                context = str(item.get("context") or item.get("event") or "").strip()
                if name:
                    items.append({"name": name, "context": context})
    return items


# ═══════════════════════════════════════════════════════════════════════════════
# 默认工具：人物信息搜索
# ═══════════════════════════════════════════════════════════════════════════════

def default_search_person_info(
    person_name: str,
    *,
    llm: object = None,
) -> Dict[str, object]:
    """搜索人物结构化信息——默认实现。

    搜索流程：
    1. 根据环境变量 STORY_AGENT_ENABLE_WEB_RESEARCH 决定是否启用网络搜索。
    2. 若启用，依次从维基百科和百度百科拉取摘要。
    3. 若传入 LLM 实例，调用 LLM 将摘要整理为结构化 JSON（含朝代、摘要、
       短评候选、身份、成就、时间线、地点、存疑点）。
    4. 若未传入 LLM，仅做基础的摘要拼接和朝代推断。

    Args:
        person_name: 要搜索的人物姓名。
        llm: 可选的 LLM 调用对象，用于结构化信息提取。为 None 时仅做基础整理。

    Returns:
        包含以下字段的字典：
        - person: 人物姓名
        - sources: 外部搜索源列表
        - source_names: 搜索源名称列表
        - dynasty: 朝代
        - summary: 摘要
        - short_review_candidate: 短评候选文本
        - identities: 身份列表
        - achievements: 成就列表
        - timeline: 时间线列表
        - places: 地点列表
        - cautions: 存疑点列表
    """
    # ── 步骤 1：检查网络搜索是否启用 ──
    enable_web = (os.getenv("STORY_AGENT_ENABLE_WEB_RESEARCH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # ── 步骤 2：拉取外部搜索源摘要 ──
    sources: List[SearchSource] = []
    if enable_web:
        wiki = _wikipedia_summary(person_name)
        if wiki:
            sources.append(wiki)
        baike = _baidu_baike_summary(person_name)
        if baike:
            sources.append(baike)

    # ── 步骤 3：拼接搜索摘要片段 ──
    snippets = "\n\n".join(
        f"[{item.get('source')}] {item.get('title')}\n{item.get('summary')}"
        for item in sources
        if item.get("summary")
    )

    # ── 步骤 4：构建初始结果字典 ──
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

    # ── 步骤 5：无 LLM 时的降级处理 ──
    if llm is None:
        if sources:
            result["summary"] = " ".join(str(item.get("summary") or "") for item in sources[:2]).strip()
            result["dynasty"] = _infer_dynasty(result["summary"])
        return result

    # ── 步骤 6：构建 LLM 提示词并调用 ──
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

    # ── 步骤 7：解析 LLM 返回的 JSON 并填充结果 ──
    payload = parse_json_payload(raw or "")
    if not payload:
        # JSON 解析失败时的降级处理
        result["dynasty"] = _infer_dynasty(snippets, raw)
        result["summary"] = (raw or "").strip()
        return result

    # dynasty 优先取 JSON 中的值，为空时回退到从摘要推断
    result["dynasty"] = str(payload.get("dynasty") or "").strip() or _infer_dynasty(payload.get("summary"), snippets, raw)
    result["summary"] = str(payload.get("summary") or "").strip()
    result["short_review_candidate"] = str(payload.get("short_review_candidate") or "").strip()
    result["identities"] = [str(item).strip() for item in payload.get("identities") or [] if str(item).strip()]
    result["achievements"] = [str(item).strip() for item in payload.get("achievements") or [] if str(item).strip()]
    result["timeline"] = [item for item in payload.get("timeline") or [] if isinstance(item, dict)]
    result["places"] = _normalize_places(payload.get("places"))
    result["cautions"] = [str(item).strip() for item in payload.get("cautions") or [] if str(item).strip()]
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 默认工具：疑难地点人工审核入队
# ═══════════════════════════════════════════════════════════════════════════════

def default_queue_hard_place_review(payload: Dict[str, object]) -> Dict[str, object]:
    """将无法自动解析的疑难地点提交至人工审核队列。

    该方法封装了 geocode_api 的 submit_hard_place_for_review 接口，
    用于地理编码失败时提交审核工单。

    Args:
        payload: 包含地点信息的字典，通常包含 place_name、reason 等字段。

    Returns:
        submit_hard_place_for_review 的返回结果，通常包含 queued、status、
        review_item_id 等字段。
    """
    geocode_service_utils = _geocode_service_utils()
    geocode_api_utils = _geocode_api_utils()
    return geocode_api_utils.submit_hard_place_for_review(
        payload,
        geocode_service_utils=geocode_service_utils,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 默认工具：古今地名坐标解析
# ═══════════════════════════════════════════════════════════════════════════════

def default_fetch_ancient_place_map(
    place_name: str,
    *,
    dynasty: Optional[str] = None,
    queue_review_fn: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
) -> Dict[str, object]:
    """解析古今地名映射并获取坐标——默认实现。

    解析流程：
    1. 拆分古地名与现代地名。
    2. 从历史地名索引中查找坐标（支持朝代消歧）。
    3. 索引未命中时通过地理编码服务解析。
    4. 两次均失败且传入了审核入队回调时，将地点提交人工审核。

    Args:
        place_name: 待解析的地名（可能为古地名）。
        dynasty: 可选，人物朝代，用于消歧（如 "宋" 的 "东京" → 开封）。
        queue_review_fn: 可选回调，用于将解析失败的地点提交人工审核队列。
            接收包含 place_name 和 reason 的字典，返回审核结果。

    Returns:
        包含以下字段的字典：
        - query: 原始查询地名
        - ancient_name: 古地名
        - modern_name: 现代地名
        - lat: 纬度（解析失败时为 None）
        - lng: 经度（解析失败时为 None）
        - source: 坐标来源（"historical_index" / "geocode" / ""）
        - review_queued: 是否已入队审核
        - review_status: 审核状态
        - review_item_id: 审核工单 ID
        - review_target: 审核队列路径
        - review_reason: 审核原因
    """
    geocode_service_utils = _geocode_service_utils()

    # ── 步骤 1：拆分古今地名 ──
    query = str(place_name or "").strip()
    ancient_name, modern_name = geocode_service_utils.split_ancient_modern(query, event_callback=None)

    # ── 步骤 2：确定用于地理编码的搜索名 ──
    search_name = parser_utils.pick_geocode_name(modern_name or query)

    # ── 步骤 3：从历史地名索引查找坐标（朝代感知）──
    coord = geocode_service_utils.lookup_coords_from_historical_index(
        query, ancient_name, modern_name, search_name, dynasty=dynasty,
    )
    source = "historical_index"

    # ── 步骤 4：索引未命中时通过地理编码服务解析 ──
    if not coord and search_name:
        coord = geocode_service_utils.resolve_place_coord(
            search_name, None, query, ancient_name, modern_name, dynasty=dynasty,
        )
        source = "geocode"

    # ── 步骤 5：两次均失败时提交人工审核 ──
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


# ═══════════════════════════════════════════════════════════════════════════════
# 默认工具：Markdown 传记生成
# ═══════════════════════════════════════════════════════════════════════════════

def default_generate_markdown(structure: Dict[str, object], *, llm: object = None) -> str:
    """根据结构化资料生成人物 Markdown 传记——默认实现。

    生成流程：
    1. 若未传入 LLM，直接返回上一轮草稿。
    2. 加载系统提示词模板。
    3. 将检索结果、地名映射、Critic 反馈、运行时反思组装为用户提示词。
    4. 调用 LLM 生成 Markdown。
    5. 确保短评候选已注入到生成的 Markdown 中。

    Args:
        structure: 包含人物结构化资料的字典，预期包含以下键：
            - person: 人物姓名
            - search_result: 检索结果
            - place_maps: 古今地名映射列表
            - critic_feedback: Critic 反馈列表
            - runtime_reflection_prompt: 运行时反思提示词
            - previous_draft: 上一轮草稿（LLM 不可用时返回此值）
        llm: 可选的 LLM 调用对象。为 None 时返回上一轮草稿。

    Returns:
        生成的 Markdown 传记字符串。
    """
    # ── 步骤 1：无 LLM 时的降级处理 ──
    if llm is None:
        return str(structure.get("previous_draft") or "")

    # ── 步骤 2：加载系统提示词 ──
    system_prompt = _read_prompt("story_system_prompt.md")

    # ── 步骤 3：序列化各类结构化数据 ──
    research = json.dumps(structure.get("search_result") or {}, ensure_ascii=False, indent=2)
    place_maps = json.dumps(structure.get("place_maps") or [], ensure_ascii=False, indent=2)
    critic_feedback = json.dumps(structure.get("critic_feedback") or [], ensure_ascii=False, indent=2)

    # ── 步骤 4：构建运行时反思提示词 ──
    runtime_reflection = str(structure.get("runtime_reflection_prompt") or "").strip()
    reflection = runtime_reflection or "运行时反思：\n- 当前状态：stable"

    # ── 步骤 5：组装用户提示词 ──
    user_prompt = (
        f"请根据以下结构化资料生成历史人物「{structure.get('person') or ''}」的最终 Markdown。\n\n"
        f"检索资料：\n{research}\n\n"
        f"古今地名映射：\n{place_maps}\n\n"
        f"Critic 反馈（若为空则代表首稿）：\n{critic_feedback}\n\n"
        f"{reflection}\n\n"
        "要求：\n"
        "1. 严格遵守系统提示词版式；\n"
        "2. 如果 Critic 提示某个地点不够精确，要在正文和时间线里补出现代地名；\n"
        "3. 如果资料有存疑点，用\u201c存疑/说法不一\u201d表达，不要编造；\n"
        "4. 如果 Critic 指出误引、张冠李戴，或把作品说明误写成\u201c名篇名句\u201d，要改成更准确的栏目和措辞；\n"
        "5. 如果检索资料里有 short_review_candidate，优先把它放入\u201c### 历史评价\u201d的第一条，保持一句话短评风格；\n"
        "6. 优先吸收运行时反思里的瓶颈与下一步动作，避免重复上一轮失败模式。"
    )

    # ── 步骤 6：调用 LLM 生成 Markdown ──
    markdown = _llm_think(
        llm,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        timeout_seconds=_EDITOR_LLM_TIMEOUT_SECONDS,
    ) or ""

    # ── 步骤 7：确保短评已注入 ──
    candidate = dict(structure.get("search_result") or {}).get("short_review_candidate")
    return _ensure_short_review_in_markdown(markdown, candidate)


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：朝代推断
# ═══════════════════════════════════════════════════════════════════════════════

def _infer_dynasty(*texts: object) -> str:
    """从给定文本中推断朝代。

    遍历所有传入的文本，在 _DYNASTY_TOKENS 中查找匹配的朝代关键词，
    返回第一个匹配到的朝代名。

    Args:
        *texts: 可变数量的文本参数，每个参数会转为字符串后匹配。

    Returns:
        匹配到的朝代名称字符串。若所有文本均未匹配到，返回空字符串。
    """
    for value in texts:
        content = str(value or "").strip()
        if not content:
            continue
        for token in _DYNASTY_TOKENS:
            if token in content:
                return token
    return ""

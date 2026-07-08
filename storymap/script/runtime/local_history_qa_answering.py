from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence


_QUERY_STOPWORDS = {
    "什么",
    "为何",
    "为什么",
    "怎么",
    "如何",
    "哪个",
    "哪些",
    "哪里",
    "哪儿",
    "一下",
    "请问",
    "介绍",
    "说说",
    "讲讲",
    "一下子",
    "一下下",
}


@dataclass(frozen=True)
class LocalHistoryQADocument:
    info: Dict[str, str]
    overview: str
    locations: List[Dict[str, str]]
    timeline_header: List[str]
    timeline_rows: List[Sequence[str]]
    works: List[str]
    reviews: List[str]


def build_local_history_answer(person_name: str, question: str, markdown: str, parsed_doc: object) -> str:
    qa_doc = build_local_history_document(markdown, parsed_doc)
    normalized_question = normalize_text(question)

    if is_intro_question(normalized_question):
        return answer_intro(person_name, qa_doc.info, qa_doc.overview, qa_doc.works)
    if contains_any(normalized_question, ("出生", "生于", "籍贯", "家乡", "哪里人")):
        return answer_birth(person_name, qa_doc.info)
    if contains_any(normalized_question, ("去世", "卒于", "死于", "晚年", "终老")):
        return answer_death(person_name, qa_doc.info)
    if contains_any(normalized_question, ("作品", "著作", "写了", "诗", "词", "文章", "名句")):
        return answer_works(person_name, qa_doc.info, qa_doc.works, markdown)
    if contains_any(normalized_question, ("足迹", "行迹", "行程", "轨迹", "去过", "到过", "到哪", "哪里", "在哪", "迁徙", "贬到")):
        return answer_locations(person_name, qa_doc.locations, qa_doc.timeline_header, qa_doc.timeline_rows)
    if contains_any(normalized_question, ("评价", "地位", "成就", "贡献", "影响")):
        return answer_achievements(person_name, qa_doc.info, qa_doc.overview, qa_doc.reviews)

    return answer_by_retrieval(
        question=question,
        info=qa_doc.info,
        overview=qa_doc.overview,
        locations=qa_doc.locations,
        timeline_header=qa_doc.timeline_header,
        timeline_rows=qa_doc.timeline_rows,
        reviews=qa_doc.reviews,
    )


def build_local_history_document(markdown: str, parsed_doc: object) -> LocalHistoryQADocument:
    return LocalHistoryQADocument(
        info=dict(getattr(parsed_doc, "basic_info_map", None) or {}),
        overview=str(getattr(parsed_doc, "overview", "") or "").strip(),
        locations=[item.to_legacy_dict() for item in (getattr(parsed_doc, "location_sections", None) or [])],
        timeline_header=list(getattr(parsed_doc, "timeline_header", None) or []),
        timeline_rows=list(getattr(parsed_doc, "timeline_rows", None) or []),
        works=extract_work_titles(markdown),
        reviews=[
            str(item).strip()
            for item in (getattr(parsed_doc, "historical_reviews", None) or [])
            if str(item).strip()
        ],
    )


def answer_intro(person_name: str, info: Dict[str, str], overview: str, works: Sequence[str]) -> str:
    parts: List[str] = []
    dynasty = (info.get("时代") or info.get("朝代") or "").strip()
    identity = (info.get("主要身份") or "").strip()
    status = (info.get("历史地位") or "").strip()
    achievements = (info.get("主要成就") or "").strip()
    if dynasty or identity:
        parts.append("、".join([item for item in [dynasty, identity] if item]))
    if status:
        parts.append(status)
    elif achievements:
        parts.append(achievements)
    if works:
        parts.append("代表作品有：" + "、".join(list(works)[:5]))
    if overview and overview not in parts:
        parts.append(overview[:160].strip())
    if not parts:
        return f"根据本地人物档案，{person_name}的详细介绍暂不完整。"
    return f"根据本地人物档案，{person_name}可概括为：\n- " + "\n- ".join(parts[:4])


def answer_birth(person_name: str, info: Dict[str, str]) -> str:
    birth = (info.get("出生") or "").strip()
    if not birth:
        birthplace = (info.get("籍贯") or "").strip()
        if birthplace:
            birth = birthplace
    if not birth:
        return f"本地人物档案里没有明确写出{person_name}的出生信息。"
    return f"根据本地人物档案，{person_name}的出生信息是：{birth}"


def answer_death(person_name: str, info: Dict[str, str]) -> str:
    death = (info.get("去世") or "").strip()
    if not death:
        return f"本地人物档案里没有明确写出{person_name}的去世信息。"
    return f"根据本地人物档案，{person_name}的去世信息是：{death}"


def answer_works(
    person_name: str,
    info: Dict[str, str],
    works: Sequence[str],
    markdown: str,
) -> str:
    achievements = (info.get("主要成就") or "").strip()
    quote_lines: List[str] = []
    for line in markdown.splitlines():
        text = line.strip().lstrip("-").strip()
        if not text:
            continue
        if "《" in text and "》" in text:
            continue
        if len(text) <= 30 and any(ch in text for ch in ("，", "。", "？", "！")):
            quote_lines.append(text)
    parts: List[str] = []
    if works:
        parts.append("代表作品：" + "、".join(list(works)[:8]))
    if achievements:
        parts.append("相关成就：" + achievements[:120])
    if quote_lines:
        parts.append("可见名句：" + " / ".join(quote_lines[:3]))
    if not parts:
        return f"本地人物档案中没有整理出{person_name}的作品信息。"
    return f"根据本地人物档案，{person_name}的作品相关信息如下：\n- " + "\n- ".join(parts)


def answer_locations(
    person_name: str,
    locations: List[Dict[str, str]],
    timeline_header: Sequence[str],
    timeline_rows: Sequence[Sequence[str]],
) -> str:
    lines: List[str] = []
    for loc in locations[:6]:
        time_text = str(loc.get("time") or "").strip()
        place_text = str(loc.get("location") or loc.get("name") or "").strip()
        event_text = str(loc.get("event") or "").strip()
        meaning_text = str(loc.get("significance") or "").strip()
        if not place_text:
            continue
        detail = "；".join([item for item in [event_text, meaning_text] if item])
        prefix = f"{time_text}：{place_text}" if time_text else place_text
        lines.append(f"{prefix}{('；' + detail) if detail else ''}")
    if not lines:
        lines.extend(timeline_briefs(timeline_header, timeline_rows, limit=6))
    if not lines:
        return f"本地人物档案中暂未整理出{person_name}的足迹信息。"
    return f"根据本地人物档案，{person_name}的主要足迹包括：\n- " + "\n- ".join(lines[:6])


def answer_achievements(
    person_name: str,
    info: Dict[str, str],
    overview: str,
    reviews: Sequence[str],
) -> str:
    parts: List[str] = []
    for key in ("历史地位", "主要成就", "主要身份"):
        value = str(info.get(key) or "").strip()
        if value:
            parts.append(value)
    if overview:
        parts.append(overview[:160].strip())
    parts.extend(list(reviews[:2]))
    if not parts:
        return f"本地人物档案中暂未整理出{person_name}的评价与成就信息。"
    deduped: List[str] = []
    seen = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            deduped.append(part)
    return f"根据本地人物档案，{person_name}的评价与成就可以概括为：\n- " + "\n- ".join(deduped[:4])


def answer_by_retrieval(
    *,
    question: str,
    info: Dict[str, str],
    overview: str,
    locations: Sequence[Dict[str, str]],
    timeline_header: Sequence[str],
    timeline_rows: Sequence[Sequence[str]],
    reviews: Sequence[str],
) -> str:
    evidences = build_retrieval_evidences(
        info=info,
        overview=overview,
        locations=locations,
        timeline_header=timeline_header,
        timeline_rows=timeline_rows,
        reviews=reviews,
    )
    scored: List[tuple[int, str, str]] = []
    keywords = extract_keywords(question)
    for label, text in evidences:
        score = score_text(question, keywords, text)
        if score > 0:
            scored.append((score, label, text))
    scored.sort(key=lambda item: (-item[0], len(item[2])))
    if not scored:
        return ""
    hits = [f"{label}：{text}" for _, label, text in scored[:4]]
    return "根据本地人物档案，和你问题最相关的信息是：\n- " + "\n- ".join(hits)


def build_retrieval_evidences(
    *,
    info: Dict[str, str],
    overview: str,
    locations: Sequence[Dict[str, str]],
    timeline_header: Sequence[str],
    timeline_rows: Sequence[Sequence[str]],
    reviews: Sequence[str],
) -> List[tuple[str, str]]:
    evidences: List[tuple[str, str]] = []
    if overview:
        evidences.append(("概述", overview))
    for key in ("历史地位", "主要成就", "主要身份", "出生", "去世"):
        value = str(info.get(key) or "").strip()
        if value:
            evidences.append((key, value))
    for loc in locations[:10]:
        parts = [
            str(loc.get("time") or "").strip(),
            str(loc.get("location") or loc.get("name") or "").strip(),
            str(loc.get("event") or "").strip(),
            str(loc.get("significance") or "").strip(),
        ]
        text = "；".join([part for part in parts if part])
        if text:
            evidences.append(("足迹", text))
    for line in timeline_briefs(timeline_header, timeline_rows, limit=10):
        evidences.append(("时间线", line))
    for review in reviews[:5]:
        evidences.append(("评价", review))
    return evidences


def contains_any(text: str, tokens: Sequence[str]) -> bool:
    return any(token in text for token in tokens)


def is_intro_question(text: str) -> bool:
    return contains_any(text, ("你是谁", "是谁", "介绍", "简介", "何人", "什么人", "生平"))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def extract_keywords(question: str) -> List[str]:
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", str(question or ""))
    keywords: List[str] = []
    seen = set()
    for token in tokens:
        token = token.strip()
        if not token or token in _QUERY_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            keywords.append(token)
    return keywords


def score_text(question: str, keywords: Sequence[str], text: str) -> int:
    haystack = normalize_text(text)
    if not haystack:
        return 0
    score = 0
    for keyword in keywords:
        if keyword in haystack:
            score += max(3, len(keyword))
    compact_question = normalize_text(question)
    shared_chars = {ch for ch in compact_question if ch in haystack and "\u4e00" <= ch <= "\u9fff"}
    score += len(shared_chars)
    return score


def timeline_briefs(
    timeline_header: Sequence[str],
    timeline_rows: Sequence[Sequence[str]],
    *,
    limit: int,
) -> List[str]:
    if not timeline_rows:
        return []
    time_idx = find_header_index(timeline_header, ("时间", "年份", "年表", "年代", "时期", "时间段"))
    place_idx = find_header_index(timeline_header, ("地点", "地名", "现称", "今地", "今名"))
    event_idx = find_header_index(timeline_header, ("事件", "经历", "大事", "作品", "活动"))
    briefs: List[str] = []
    for row in timeline_rows:
        time_text = cell(row, time_idx)
        place_text = cell(row, place_idx)
        event_text = cell(row, event_idx)
        if not any([time_text, place_text, event_text]):
            continue
        parts: List[str] = []
        if time_text:
            parts.append(time_text)
        if place_text:
            parts.append(place_text)
        if event_text:
            parts.append(event_text)
        text = "；".join(parts)
        if text:
            briefs.append(text)
        if len(briefs) >= limit:
            break
    return briefs


def find_header_index(headers: Sequence[str], candidates: Sequence[str]) -> int:
    for idx, header in enumerate(headers):
        header_text = str(header or "").strip()
        if any(candidate in header_text for candidate in candidates):
            return idx
    return -1


def cell(row: Sequence[str], idx: int) -> str:
    if idx < 0 or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()


def extract_work_titles(markdown: str) -> List[str]:
    titles = re.findall(r"《([^》]{1,40})》", str(markdown or ""))
    deduped: List[str] = []
    seen = set()
    for title in titles:
        clean = title.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped

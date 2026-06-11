from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence

try:
    from . import parsers as parser_utils
    from .person_registry import canonical_person_name
    from .project_paths import classify_story_person_authenticity, story_person_names
except ImportError:
    import parsers as parser_utils
    from person_registry import canonical_person_name
    from project_paths import classify_story_person_authenticity, story_person_names


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


@dataclass(slots=True)
class QAResult:
    handled: bool
    content: str = ""
    person_name: str = ""
    reason: str = ""


class LocalHistoryQAAgent:
    def __init__(self, *, project_root: Callable[[], str]) -> None:
        self._project_root = project_root

    def answer(self, data: object) -> QAResult:
        if not isinstance(data, dict):
            return QAResult(False, reason="invalid_body")
        messages = data.get("messages")
        if not isinstance(messages, list):
            return QAResult(False, reason="messages_required")
        question = self._extract_last_user(messages)
        if not question:
            return QAResult(False, reason="empty_question")
        person_name = self._resolve_person_name(data, messages)
        if not person_name:
            return QAResult(False, reason="person_missing")
        markdown = self._load_markdown(person_name)
        if not markdown:
            return QAResult(False, person_name=person_name, reason="story_not_found")
        parsed_doc = parser_utils.parse_story_document(markdown)
        content = self._build_answer(person_name, question, markdown, parsed_doc)
        if not content:
            return QAResult(False, person_name=person_name, reason="no_local_match")
        return QAResult(True, content=content, person_name=person_name, reason="local_story")

    def _resolve_person_name(self, data: Dict[str, object], messages: List[Dict[str, object]]) -> str:
        context = data.get("context")
        if isinstance(context, dict):
            for key in ("personName", "person", "name"):
                value = str(context.get(key) or "").strip()
                if value:
                    return value
        for key in ("person", "personName", "name"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        system_text = self._extract_system_text(messages)
        matched = re.search(r"扮演历史人物[:：]\s*([^\n。]+)", system_text)
        if matched:
            return matched.group(1).strip()
        known_people = self._list_known_people()
        for name in known_people:
            if name and name in system_text:
                return name
        return ""

    def _list_known_people(self) -> List[str]:
        try:
            people = story_person_names(Path(self._project_root()) / "storymap" / "examples" / "story")
        except Exception:
            return []
        people.sort(key=len, reverse=True)
        return people

    @staticmethod
    def _extract_last_user(messages: List[Dict[str, object]]) -> str:
        last_user = ""
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip() == "user":
                last_user = str(message.get("content") or "").strip()
        return last_user

    @staticmethod
    def _extract_system_text(messages: List[Dict[str, object]]) -> str:
        system_text = ""
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip() == "system":
                system_text = str(message.get("content") or "")
        return system_text

    def _load_markdown(self, person_name: str) -> str:
        story_dir = Path(self._project_root()) / "storymap" / "examples" / "story"
        accepted, _ = classify_story_person_authenticity(person_name, story_dir)
        if not accepted:
            return ""
        known_people = self._list_known_people()
        canonical = str(canonical_person_name(person_name, known_people) or person_name).strip()
        candidate = story_dir / f"{canonical}.md"
        try:
            return candidate.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _build_answer(self, person_name: str, question: str, markdown: str, parsed_doc) -> str:
        normalized_question = self._normalize_text(question)
        info = dict(parsed_doc.basic_info_map or {})
        overview = str(parsed_doc.overview or "").strip()
        locations = [item.to_legacy_dict() for item in (parsed_doc.location_sections or [])]
        timeline_rows = list(parsed_doc.timeline_rows or [])
        timeline_header = list(parsed_doc.timeline_header or [])
        works = self._extract_work_titles(markdown)
        reviews = [str(item).strip() for item in (parsed_doc.historical_reviews or []) if str(item).strip()]

        if self._is_intro_question(normalized_question):
            return self._answer_intro(person_name, info, overview, works)
        if self._contains_any(normalized_question, ("出生", "生于", "籍贯", "家乡", "哪里人")):
            return self._answer_birth(person_name, info)
        if self._contains_any(normalized_question, ("去世", "卒于", "死于", "晚年", "终老")):
            return self._answer_death(person_name, info)
        if self._contains_any(normalized_question, ("作品", "著作", "写了", "诗", "词", "文章", "名句")):
            return self._answer_works(person_name, info, works, markdown)
        if self._contains_any(normalized_question, ("足迹", "行迹", "行程", "轨迹", "去过", "到过", "到哪", "哪里", "在哪", "迁徙", "贬到")):
            return self._answer_locations(person_name, locations, timeline_header, timeline_rows)
        if self._contains_any(normalized_question, ("评价", "地位", "成就", "贡献", "影响")):
            return self._answer_achievements(person_name, info, overview, reviews)

        retrieval_answer = self._answer_by_retrieval(
            question=question,
            info=info,
            overview=overview,
            locations=locations,
            timeline_header=timeline_header,
            timeline_rows=timeline_rows,
            reviews=reviews,
        )
        if retrieval_answer:
            return retrieval_answer
        return ""

    def _answer_intro(self, person_name: str, info: Dict[str, str], overview: str, works: Sequence[str]) -> str:
        parts = []
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

    def _answer_birth(self, person_name: str, info: Dict[str, str]) -> str:
        birth = (info.get("出生") or "").strip()
        if not birth:
            birthplace = (info.get("籍贯") or "").strip()
            if birthplace:
                birth = birthplace
        if not birth:
            return f"本地人物档案里没有明确写出{person_name}的出生信息。"
        return f"根据本地人物档案，{person_name}的出生信息是：{birth}"

    def _answer_death(self, person_name: str, info: Dict[str, str]) -> str:
        death = (info.get("去世") or "").strip()
        if not death:
            return f"本地人物档案里没有明确写出{person_name}的去世信息。"
        return f"根据本地人物档案，{person_name}的去世信息是：{death}"

    def _answer_works(
        self,
        person_name: str,
        info: Dict[str, str],
        works: Sequence[str],
        markdown: str,
    ) -> str:
        achievements = (info.get("主要成就") or "").strip()
        quote_lines = []
        for line in markdown.splitlines():
            text = line.strip().lstrip("-").strip()
            if not text:
                continue
            if "《" in text and "》" in text:
                continue
            if len(text) <= 30 and any(ch in text for ch in ("，", "。", "？", "！")):
                quote_lines.append(text)
        parts = []
        if works:
            parts.append("代表作品：" + "、".join(list(works)[:8]))
        if achievements:
            parts.append("相关成就：" + achievements[:120])
        if quote_lines:
            parts.append("可见名句：" + " / ".join(quote_lines[:3]))
        if not parts:
            return f"本地人物档案中没有整理出{person_name}的作品信息。"
        return f"根据本地人物档案，{person_name}的作品相关信息如下：\n- " + "\n- ".join(parts)

    def _answer_locations(
        self,
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
            timeline_items = self._timeline_briefs(timeline_header, timeline_rows, limit=6)
            lines.extend(timeline_items)
        if not lines:
            return f"本地人物档案中暂未整理出{person_name}的足迹信息。"
        return f"根据本地人物档案，{person_name}的主要足迹包括：\n- " + "\n- ".join(lines[:6])

    def _answer_achievements(
        self,
        person_name: str,
        info: Dict[str, str],
        overview: str,
        reviews: Sequence[str],
    ) -> str:
        parts = []
        for key in ("历史地位", "主要成就", "主要身份"):
            value = str(info.get(key) or "").strip()
            if value:
                parts.append(value)
        if overview:
            parts.append(overview[:160].strip())
        parts.extend(list(reviews[:2]))
        if not parts:
            return f"本地人物档案中暂未整理出{person_name}的评价与成就信息。"
        deduped = []
        seen = set()
        for part in parts:
            if part and part not in seen:
                seen.add(part)
                deduped.append(part)
        return f"根据本地人物档案，{person_name}的评价与成就可以概括为：\n- " + "\n- ".join(deduped[:4])

    def _answer_by_retrieval(
        self,
        *,
        question: str,
        info: Dict[str, str],
        overview: str,
        locations: Sequence[Dict[str, str]],
        timeline_header: Sequence[str],
        timeline_rows: Sequence[Sequence[str]],
        reviews: Sequence[str],
    ) -> str:
        evidences = []
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
        for line in self._timeline_briefs(timeline_header, timeline_rows, limit=10):
            evidences.append(("时间线", line))
        for review in reviews[:5]:
            evidences.append(("评价", review))

        scored = []
        keywords = self._extract_keywords(question)
        for label, text in evidences:
            score = self._score_text(question, keywords, text)
            if score > 0:
                scored.append((score, label, text))
        scored.sort(key=lambda item: (-item[0], len(item[2])))
        if not scored:
            return ""
        hits = []
        for _, label, text in scored[:4]:
            hits.append(f"{label}：{text}")
        return f"根据本地人物档案，和你问题最相关的信息是：\n- " + "\n- ".join(hits)

    @staticmethod
    def _contains_any(text: str, tokens: Sequence[str]) -> bool:
        return any(token in text for token in tokens)

    @staticmethod
    def _is_intro_question(text: str) -> bool:
        return LocalHistoryQAAgent._contains_any(
            text,
            ("你是谁", "是谁", "介绍", "简介", "何人", "什么人", "生平"),
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).strip()

    def _extract_keywords(self, question: str) -> List[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", str(question or ""))
        keywords = []
        seen = set()
        for token in tokens:
            token = token.strip()
            if not token or token in _QUERY_STOPWORDS:
                continue
            if token not in seen:
                seen.add(token)
                keywords.append(token)
        return keywords

    def _score_text(self, question: str, keywords: Sequence[str], text: str) -> int:
        haystack = self._normalize_text(text)
        if not haystack:
            return 0
        score = 0
        for keyword in keywords:
            if keyword in haystack:
                score += max(3, len(keyword))
        compact_question = self._normalize_text(question)
        shared_chars = {ch for ch in compact_question if ch in haystack and "\u4e00" <= ch <= "\u9fff"}
        score += len(shared_chars)
        return score

    def _timeline_briefs(
        self,
        timeline_header: Sequence[str],
        timeline_rows: Sequence[Sequence[str]],
        *,
        limit: int,
    ) -> List[str]:
        if not timeline_rows:
            return []
        time_idx = self._find_header_index(timeline_header, ("时间", "年份", "年表", "年代", "时期", "时间段"))
        place_idx = self._find_header_index(timeline_header, ("地点", "地名", "现称", "今地", "今名"))
        event_idx = self._find_header_index(timeline_header, ("事件", "经历", "大事", "作品", "活动"))
        briefs: List[str] = []
        for row in timeline_rows:
            time_text = self._cell(row, time_idx)
            place_text = self._cell(row, place_idx)
            event_text = self._cell(row, event_idx)
            if not any([time_text, place_text, event_text]):
                continue
            parts = []
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

    @staticmethod
    def _find_header_index(headers: Sequence[str], candidates: Sequence[str]) -> int:
        for idx, header in enumerate(headers):
            header_text = str(header or "").strip()
            if any(candidate in header_text for candidate in candidates):
                return idx
        return -1

    @staticmethod
    def _cell(row: Sequence[str], idx: int) -> str:
        if idx < 0 or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

    @staticmethod
    def _extract_work_titles(markdown: str) -> List[str]:
        titles = re.findall(r"《([^》]{1,40})》", str(markdown or ""))
        deduped = []
        seen = set()
        for title in titles:
            clean = title.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            deduped.append(clean)
        return deduped

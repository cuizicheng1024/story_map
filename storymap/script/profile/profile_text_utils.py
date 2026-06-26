from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


_LITERARY_ROLE_TOKENS = (
    "诗人",
    "词人",
    "文学家",
    "散文家",
    "作家",
    "小说家",
    "剧作家",
    "诗词家",
    "文人",
    "赋家",
)
_HISTORICAL_RECORD_TOKENS = (
    "《史记》",
    "《汉书》",
    "《后汉书》",
    "《三国志》",
    "《晋书》",
    "《宋书》",
    "《南齐书》",
    "《梁书》",
    "《陈书》",
    "《魏书》",
    "《北齐书》",
    "《周书》",
    "《隋书》",
    "《旧唐书》",
    "《新唐书》",
    "《旧五代史》",
    "《新五代史》",
    "《宋史》",
    "《辽史》",
    "《金史》",
    "《元史》",
    "《明史》",
    "《清史稿》",
    "《资治通鉴》",
    "史载",
    "记载",
    "载曰",
    "评曰",
    "本纪",
    "列传",
)
_WORK_TEXT_BAD_PREFIX_PATTERNS = (
    r"^(课文/词作|作品简介|内容简介|作者简介|写作背景|主题思想|艺术特色|主要成就|核心要点|关键史实|历史地位)\s*[：:]",
    r"^李春本人无文学作品传世",
    r"^暂无[。；;!！]?$",
)
_DERIVED_WORK_TEXT_LIBRARY = {
    "中国石拱桥": "\n".join(
        [
            "“桥的设计完全合乎科学原理，施工技术更是巧妙绝伦。”",
            "“赵州桥不但形式优美，而且结构坚固。”",
        ]
    ),
    "记承天寺夜游": "\n".join(
        [
            "“庭下如积水空明，水中藻、荇交横，盖竹柏影也。”",
            "“但少闲人如吾两人者耳。”",
        ]
    ),
}


def extract_works(text: str) -> List[str]:
    if not text:
        return []
    items = re.findall(r"《([^》]+)》", text)
    seen = set()
    works: List[str] = []
    for item in items:
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            works.append(name)
    return works


def work_title_aliases(title: str) -> List[str]:
    clean_title = str(title or "").strip()
    if not clean_title:
        return []
    aliases: List[str] = []

    def push(value: str) -> None:
        item = str(value or "").strip()
        if item and item not in aliases:
            aliases.append(item)

    push(clean_title)
    for chunk in re.split(r"[·・:：]", clean_title):
        push(chunk)
    short_title = re.sub(r"[上中下篇卷章节编]\s*$", "", clean_title).strip()
    push(short_title)
    for chunk in list(aliases):
        trimmed = re.sub(r"[上中下篇卷章节编]\s*$", "", chunk).strip()
        push(trimmed)
    return aliases


def extract_work_texts(md: str) -> Dict[str, str]:
    if not isinstance(md, str) or not md.strip():
        return {}
    work_texts: Dict[str, str] = {}
    mentioned_titles: List[str] = []

    def remember_titles(raw_titles: List[str]) -> None:
        for raw_title in raw_titles:
            title = str(raw_title or "").strip()
            if title and title not in mentioned_titles:
                mentioned_titles.append(title)

    for raw_line in md.splitlines():
        line = str(raw_line or "").strip().lstrip("-").strip()
        if "《" not in line:
            continue
        remember_titles(re.findall(r"《([^》]{1,80})》", line))
        for title, quote in re.findall(r"《([^》]{1,80})》\s*[：:]\s*[“\"「](.+?)[”\"」]", line):
            _register_work_text(work_texts, title, quote)
    for raw_line in md.splitlines():
        line = str(raw_line or "").strip()
        if "《" not in line:
            continue
        clauses = [seg.strip() for seg in re.split(r"[；;]\s*", line) if str(seg or "").strip()]
        for clause in clauses:
            titles = re.findall(r"《([^》]{1,80})》", clause)
            if not titles:
                continue
            remember_titles(titles)
            context = re.sub(r"^\s*[-*•]\s*", "", clause)
            context = re.sub(r"\*\*", "", context).strip()
            context = re.sub(r"\s+", " ", context)
            context = _extract_work_excerpt_candidate(context)
            if not context:
                continue
            if len(titles) != 1:
                continue
            _register_work_context(work_texts, titles[0], context)
    return _merge_derived_work_texts(work_texts, mentioned_titles)


def split_quote_lines(text: str) -> List[str]:
    if not text:
        return []
    parts: List[str] = []
    buf: List[str] = []
    quote_pairs = {"“": "”", '"': '"', "「": "」", "『": "』"}
    closing_stack: List[str] = []
    for ch in str(text):
        if ch in quote_pairs:
            expected = quote_pairs[ch]
            if expected == ch and closing_stack and closing_stack[-1] == ch:
                closing_stack.pop()
            else:
                closing_stack.append(expected)
        elif closing_stack and ch == closing_stack[-1]:
            closing_stack.pop()
        if ch in {"；", ";"} and not closing_stack:
            item = "".join(buf).strip()
            if item:
                parts.append(item)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def extract_title_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    def _is_valid_title(value: str) -> bool:
        title = str(value or "").strip().strip("“”\"'「」『』")
        if not title:
            return False
        if len(title) > 12:
            return False
        blocked_patterns = (
            r"(?:之治|盛世|中兴|变法|政变|之乱|革命|战争|时代|时期|遗风)$",
            r"^(?:贞观之治|开元盛世|文景之治|光武中兴|百家争鸣|楚汉战争)$",
        )
        return not any(re.search(pattern, title) for pattern in blocked_patterns)

    honor_patterns = [
        r"(?:后世)?(?:被|为|并)?(?:尊为|誉为|奉为|称为|尊称为)[“\"「『]([^”\"」』]+)[”\"」』]",
        r"[，,]\s*([^，。；、]{1,12})\s*[，。；、]?(?:与|并与).{0,20}(?:并列|齐名)",
    ]
    for pattern in honor_patterns:
        match = re.search(pattern, raw)
        candidate = str(match.group(1) or "").strip() if match else ""
        if candidate and _is_valid_title(candidate):
            return candidate
    match = re.search(r"“([^”]+)”", raw)
    if match:
        candidate = match.group(1).strip()
        if _is_valid_title(candidate):
            return candidate
    return ""


def clean_short_review_text(text: str, *, max_len: int = 88) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("|") and raw.count("|") >= 3:
        return ""
    if re.fullmatch(r"\|\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?", raw):
        return ""
    raw = re.sub(r"^\s*[-*•]\s*", "", raw)
    raw = re.sub(r"^\d+\.\s*", "", raw)
    raw = raw.replace("**", "").strip()
    quoted = re.search(r"[“\"「『](.+?)[”\"」』]", raw)
    if quoted and str(quoted.group(1) or "").strip():
        return str(quoted.group(1) or "").strip()
    trimmed = raw
    if "：" in trimmed:
        trimmed = trimmed.split("：", 1)[1].strip()
    elif ":" in trimmed:
        trimmed = trimmed.split(":", 1)[1].strip()
    trimmed = re.split(r"\s*(?:——|--|—)\s*", trimmed, maxsplit=1)[0].strip()
    trimmed = re.sub(r"[（(][^）)]{0,40}[）)]\s*$", "", trimmed).strip()
    trimmed = trimmed.strip("“”\"「」『』")
    trimmed = re.sub(r"\s+", " ", trimmed)
    if not trimmed:
        return ""
    if len(trimmed) > max_len:
        trimmed = trimmed[: max_len - 1].rstrip() + "…"
    return trimmed


def choose_short_review(
    *,
    info: Dict[str, str],
    locations: List[Dict[str, str]],
    work_texts: Dict[str, str],
    historical_reviews: List[str],
    fallback: str = "",
) -> str:
    self_direct_candidates, self_work_candidates = _collect_self_review_candidates(locations, work_texts)
    explicit_short_review_raw = [item for item in historical_reviews if _is_explicit_short_review(item)]
    literary_review_raw = [item for item in historical_reviews if _is_literary_review(item)]
    record_review_raw = [item for item in historical_reviews if _is_historical_record_review(item)]
    explicit_short_review_candidates = _dedupe_review_candidates(explicit_short_review_raw)
    literary_review_candidates = _dedupe_review_candidates(literary_review_raw)
    record_review_candidates = _dedupe_review_candidates(record_review_raw)
    categorized_raw = set(explicit_short_review_raw + literary_review_raw + record_review_raw)
    generic_review_candidates = _dedupe_review_candidates([item for item in historical_reviews if item not in categorized_raw])
    candidate_groups = (
        [
            explicit_short_review_candidates,
            self_work_candidates,
            record_review_candidates,
            self_direct_candidates,
            literary_review_candidates,
            generic_review_candidates,
        ]
        if _is_literary_person(info)
        else [
            explicit_short_review_candidates,
            literary_review_candidates,
            record_review_candidates,
            self_direct_candidates,
            self_work_candidates,
            generic_review_candidates,
        ]
    )
    for group in candidate_groups:
        for item in group:
            if str(item or "").strip():
                return str(item).strip()
    return clean_short_review_text(fallback)


def _extract_work_excerpt_candidate(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"\s+", " ", raw.replace("**", "")).strip()
    if not cleaned:
        return ""
    if re.fullmatch(r"(?:[诗词文赋文集帖序碑记]|代表作|作品)?\s*《[^》]{1,80}》[。！？!?]?", cleaned):
        return ""
    if re.fullmatch(r"(?:相关作品|代表作|作品|著有|写有|曾作|收录作品)?[：:]?\s*(?:[^《》]{0,24})?《[^》]{1,80}》[。！？!?]?", cleaned):
        return ""
    for pattern in _WORK_TEXT_BAD_PREFIX_PATTERNS:
        if re.match(pattern, cleaned):
            return ""
    quoted = [
        str(item or "").strip()
        for item in re.findall(r"[“\"「](.+?)[”\"」]", cleaned)
        if str(item or "").strip()
    ]
    if quoted:
        return "\n".join(f"“{item}”" for item in quoted[:2])
    for sentence in re.split(r"(?<=[。！？!?；;])\s*", cleaned):
        candidate = str(sentence or "").strip()
        if len(candidate) < 8 or len(candidate) > 120:
            continue
        if any(re.match(pattern, candidate) for pattern in _WORK_TEXT_BAD_PREFIX_PATTERNS):
            continue
        return candidate
    return ""


def _register_work_text(store: Dict[str, str], title: str, text: str) -> None:
    clean_title = str(title or "").strip()
    clean_text = str(text or "").strip()
    if not clean_title or not clean_text:
        return
    clean_text = re.sub(r"\s*\n\s*", "\n", clean_text).strip()
    for alias in work_title_aliases(clean_title):
        if not alias:
            continue
        existing = str(store.get(alias) or "").strip()
        if not existing or len(clean_text) > len(existing):
            store[alias] = clean_text


def _register_work_context(store: Dict[str, str], title: str, text: str) -> None:
    clean_title = str(title or "").strip()
    clean_text = str(text or "").strip()
    if not clean_title or not clean_text:
        return
    aliases = work_title_aliases(clean_title)
    if any(str(store.get(alias) or "").strip() for alias in aliases):
        return
    _register_work_text(store, clean_title, clean_text)


def _merge_derived_work_texts(store: Dict[str, str], mentioned_titles: Optional[List[str]] = None) -> Dict[str, str]:
    merged = dict(store or {})
    mentioned_aliases = set()
    for raw_title in mentioned_titles or []:
        for alias in work_title_aliases(str(raw_title or "")):
            mentioned_aliases.add(alias)
    for title, derived_text in _DERIVED_WORK_TEXT_LIBRARY.items():
        aliases = work_title_aliases(title)
        if mentioned_aliases and not any(alias in mentioned_aliases for alias in aliases):
            continue
        if not mentioned_aliases and not any(alias in merged for alias in aliases):
            continue
        has_good_excerpt = any(_extract_work_excerpt_candidate(str(merged.get(alias) or "")) for alias in aliases)
        if has_good_excerpt:
            continue
        _register_work_text(merged, title, derived_text)
    return merged


def _is_literary_person(info: Dict[str, str]) -> bool:
    haystack = " ".join(
        [
            str(info.get("主要身份") or ""),
            str(info.get("历史地位") or ""),
            str(info.get("主要成就") or ""),
        ]
    )
    return any(token in haystack for token in _LITERARY_ROLE_TOKENS)


def _is_historical_record_review(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(token in raw for token in _HISTORICAL_RECORD_TOKENS)


def _is_literary_review(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw or _is_historical_record_review(raw):
        return False
    return "《" in raw and "》" in raw


def _is_explicit_short_review(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return bool(re.match(r"^(人物)?短评\s*[：:]", raw))


def _dedupe_review_candidates(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        cleaned = clean_short_review_text(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _collect_self_review_candidates(
    locations: List[Dict[str, str]],
    work_texts: Dict[str, str],
) -> Tuple[List[str], List[str]]:
    raw_candidates: List[str] = []
    for loc in locations:
        raw_candidates.extend(split_quote_lines(str(loc.get("quotes") or "")))
    direct_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" not in str(item or "")])
    work_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" in str(item or "")])
    work_candidates.extend(_dedupe_review_candidates([str(text or "") for text in work_texts.values()]))
    return direct_candidates, _dedupe_review_candidates(work_candidates)

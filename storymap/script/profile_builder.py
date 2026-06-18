from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

try:
    from . import parsers as parser_utils
except ImportError:
    import parsers as parser_utils


Coord = Tuple[float, float]
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
_SPECULATIVE_LOCATION_PATTERNS = (
    r"推断",
    r"存疑",
    r"待考",
    r"说法不一",
    r"史料未载",
    r"不可考",
    r"古称不详",
    r"地点不详",
    r"某地",
    r"周边区域",
    r"可能",
)


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


def _loose_place_key(text: str) -> str:
    cleaned = parser_utils._pick_geocode_name(str(text or ""))
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（(].*?[）)]", "", cleaned)
    cleaned = re.sub(r"[，,。.;；:：、】【\[\]{}<>《》\"'“”‘’·•/\\|-]+", "", cleaned)
    for token in ("风景区", "景区", "古战场", "旧址", "遗址", "故居", "博物馆"):
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"[省市区县州郡府镇乡村旗盟]", "", cleaned)
    return cleaned.strip()


def _loose_coord_lookup(coords_cache: Dict[str, Coord], candidates: List[str]) -> Optional[Coord]:
    if not coords_cache:
        return None
    loose_candidates = [_loose_place_key(candidate) for candidate in candidates if str(candidate or "").strip()]
    loose_candidates = [candidate for candidate in loose_candidates if candidate]
    if not loose_candidates:
        return None
    scored: List[Tuple[int, str]] = []
    for raw_key in coords_cache.keys():
        key = str(raw_key or "").strip()
        if not key:
            continue
        loose_key = _loose_place_key(key)
        if not loose_key:
            continue
        for candidate in loose_candidates:
            if loose_key in candidate or candidate in loose_key:
                scored.append((len(loose_key), key))
                break
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return coords_cache.get(scored[0][1])


def _split_person_alias_values(*values: object) -> List[str]:
    out: List[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        for part in re.split(r"[、，,；;/\s]+", text):
            alias = str(part or "").strip()
            if alias and alias not in out:
                out.append(alias)
    return out


def _coord_group_key(lat: object, lng: object) -> str:
    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except Exception:
        return ""
    if not (-90 <= lat_value <= 90 and -180 <= lng_value <= 180):
        return ""
    return f"{lat_value:.4f},{lng_value:.4f}"


def _is_speculative_location_item(item: Dict[str, object]) -> bool:
    text = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("ancientName") or ""),
            str(item.get("modernName") or ""),
            str(item.get("event") or ""),
            str(item.get("significance") or ""),
            str(item.get("time") or ""),
        ]
    ).strip()
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in _SPECULATIVE_LOCATION_PATTERNS)


def _choose_primary_location(items: List[Dict[str, object]]) -> Dict[str, object]:
    def score(item: Dict[str, object]) -> Tuple[int, int, int]:
        text = " ".join(
            [
                str(item.get("event") or ""),
                str(item.get("significance") or ""),
                str(item.get("duration") or ""),
            ]
        ).strip()
        return (
            1 if str(item.get("duration") or "").strip() else 0,
            len(extract_works(text)),
            len(text),
        )

    return max(items, key=score)


def _merge_location_cluster(items: List[Dict[str, object]]) -> Dict[str, object]:
    base = dict(_choose_primary_location(items))

    def merge_text(field: str) -> str:
        seen: List[str] = []
        for item in items:
            value = str(item.get(field) or "").strip()
            if value and value not in seen:
                seen.append(value)
        return "；".join(seen[:4])

    merged_works: List[str] = []
    merged_quotes: List[str] = []
    for item in items:
        for work in item.get("works") or []:
            clean = str(work or "").strip()
            if clean and clean not in merged_works:
                merged_works.append(clean)
        for quote in item.get("quoteLines") or []:
            clean = str(quote or "").strip()
            if clean and clean not in merged_quotes:
                merged_quotes.append(clean)

    base["event"] = merge_text("event") or str(base.get("event") or "")
    base["significance"] = merge_text("significance") or str(base.get("significance") or "")
    base["duration"] = merge_text("duration") or str(base.get("duration") or "")
    base["works"] = merged_works
    base["quoteLines"] = merged_quotes
    return base


def _collapse_sparse_single_site_locations(loc_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if len(loc_items) <= 1:
        return loc_items

    groups: Dict[str, List[Dict[str, object]]] = {}
    for item in loc_items:
        key = _coord_group_key(item.get("lat"), item.get("lng"))
        if not key:
            continue
        groups.setdefault(key, []).append(item)
    if not groups:
        return loc_items

    concrete_keys = [
        key for key, items in groups.items()
        if any(not _is_speculative_location_item(item) for item in items)
    ]
    if len(concrete_keys) == 1:
        return [_merge_location_cluster(groups[concrete_keys[0]])]

    if len(groups) == 1:
        key = next(iter(groups.keys()))
        return [_merge_location_cluster(groups[key])]

    return loc_items


def _extract_location_time_bounds(raw: object) -> Tuple[Optional[int], Optional[int]]:
    text = str(raw or "").strip()
    if not text:
        return None, None
    years: List[int] = []
    year_pattern = re.compile(r"(公元前|前)?\s*(\d{1,4})(?=年(?!代))")
    for match in year_pattern.finditer(text):
        try:
            value = int(match.group(2))
        except Exception:
            continue
        era = str(match.group(1) or "").strip()
        years.append(-value if era else value)
    has_explicit_year = bool(re.search(r"(?:公元前|前)?\s*\d{1,4}\s*年(?!代)", text))
    if not years and ("世纪" in text or "年代" in text) and not has_explicit_year:
        return None, None
    if not years:
        for match in re.finditer(r"(?<!\d)(-?\d{1,4})(?!\d)(?!\s*世纪)", text):
            try:
                years.append(int(match.group(1)))
            except Exception:
                continue
    if not years:
        return None, None
    if len(years) == 1:
        return years[0], years[0]
    return min(years), max(years)


def _looks_like_death_location(item: Dict[str, object]) -> bool:
    kind = str(item.get("type") or "").strip().lower()
    if kind == "death":
        return True
    text = " ".join(
        str(item.get(key) or "").strip()
        for key in ("event", "significance")
        if str(item.get(key) or "").strip()
    )
    if not text:
        return False
    negated_death_pattern = re.compile(r"(不代表|并非|不是|并不是|非|不属|不算)(?:[^，。；;、,\s]{0,6})(去世|逝世|病逝|身亡|死亡|殒命|辞世|亡故|谢世|终老)")
    if negated_death_pattern.search(text):
        return False
    death_tokens = ("去世", "逝世", "病逝", "身亡", "死亡", "殒命", "惊悸而死", "溺水", "辞世", "亡故", "谢世", "终老", "安葬", "葬于")
    if any(token in text for token in death_tokens):
        return True
    return bool(re.search(r"(?:^|[，。；;、,\s])卒(?:于|地|处)?(?:$|[，。；;、,\s])", text))


def _infer_location_significance(
    item: Dict[str, object],
    *,
    person_name: str = "",
) -> str:
    existing = str(item.get("significance") or "").strip()
    if existing:
        return existing
    event = str(item.get("event") or "").strip()
    name = str(item.get("name") or item.get("modernName") or item.get("ancientName") or "此地").strip() or "此地"
    kind = str(item.get("type") or "").strip().lower()
    if kind == "birth":
        return f"{name}是{person_name or '该人物'}人生起点的重要地点，也为理解其出身背景与后世纪念提供线索。"
    if kind == "death" or _looks_like_death_location(item):
        return f"{name}对应{person_name or '该人物'}人生终章，是观察其命运转折与历史结局的重要节点。"
    if not event:
        return f"{name}是{person_name or '该人物'}人生轨迹中的关键停驻点，可据此串联其生平阶段变化。"
    if any(token in event for token in ("起兵", "结义", "投军", "出仕", "赴京", "登第", "受命", "入朝")):
        return f"{name}标志着{person_name or '该人物'}人生阶段的开启或身份转折，是其后续经历的重要起点。"
    if any(token in event for token in ("镇守", "驻守", "坐镇", "长期", "居于", "讲学", "任职")):
        return f"{name}是{person_name or '该人物'}展开核心活动的重要舞台，体现其在这一阶段的主要职责与影响。"
    if any(token in event for token in ("大败", "击败", "斩", "北伐", "凯旋", "封", "称帝", "建功", "水淹")):
        return f"{name}见证了{person_name or '该人物'}的重要功业节点，也是其历史声望形成的关键场域。"
    if any(token in event for token in ("败走", "失守", "被贬", "流放", "遇害", "擒杀", "失荆州", "兵败")):
        return f"{name}对应{person_name or '该人物'}命运转折甚至失势阶段，对理解其人生起伏具有关键意义。"
    return f"{name}与“{event}”这一事件紧密相关，是理解{person_name or '该人物'}生平轨迹的重要地点。"


def _sort_profile_locations(loc_items: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if len(loc_items) <= 1:
        return loc_items

    indexed = list(enumerate(loc_items))

    def _key(entry: Tuple[int, Dict[str, object]]) -> Tuple[int, int, int, int]:
        idx, item = entry
        start_year, end_year = _extract_location_time_bounds(item.get("time"))
        kind = str(item.get("type") or "").strip().lower()
        if kind == "birth":
            rank = 0
        elif kind == "death" or _looks_like_death_location(item):
            rank = 2
        else:
            rank = 1
        if rank == 0 and start_year is None:
            # Keep birth nodes at the head of the journey even when the source only says "生年不详".
            year_key = -(10**9)
        else:
            year_key = start_year if start_year is not None else 10**9
        end_key = end_year if end_year is not None else year_key
        return (year_key, rank, end_key, idx)

    indexed.sort(key=_key)
    return [item for _, item in indexed]


def _work_title_aliases(title: str) -> List[str]:
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
    for alias in _work_title_aliases(clean_title):
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
    aliases = _work_title_aliases(clean_title)
    if any(str(store.get(alias) or "").strip() for alias in aliases):
        return
    _register_work_text(store, clean_title, clean_text)


def _merge_derived_work_texts(store: Dict[str, str], mentioned_titles: Optional[List[str]] = None) -> Dict[str, str]:
    merged = dict(store or {})
    mentioned_aliases = set()
    for raw_title in mentioned_titles or []:
        for alias in _work_title_aliases(str(raw_title or "")):
            mentioned_aliases.add(alias)
    for title, derived_text in _DERIVED_WORK_TEXT_LIBRARY.items():
        aliases = _work_title_aliases(title)
        # Only backfill excerpts for works already mentioned on the current page.
        if mentioned_aliases and not any(alias in mentioned_aliases for alias in aliases):
            continue
        if not mentioned_aliases and not any(alias in merged for alias in aliases):
            continue
        has_good_excerpt = any(_extract_work_excerpt_candidate(str(merged.get(alias) or "")) for alias in aliases)
        if has_good_excerpt:
            continue
        _register_work_text(merged, title, derived_text)
    return merged


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
                # Multiple works in one clause often carry different quotes; avoid cross-assigning them.
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
        t = str(value or "").strip().strip("“”\"'「」『』")
        if not t:
            return False
        if len(t) > 12:
            return False
        # Filter out reign-era / macro historical phrases that are not person honorifics.
        blocked_patterns = (
            r"(?:之治|盛世|中兴|变法|政变|之乱|革命|战争|时代|时期|遗风)$",
            r"^(?:贞观之治|开元盛世|文景之治|光武中兴|百家争鸣|楚汉战争)$",
        )
        return not any(re.search(pattern, t) for pattern in blocked_patterns)
    honor_patterns = [
        r"(?:后世)?(?:被|为|并)?(?:尊为|誉为|奉为|称为|尊称为)[“\"「『]([^”\"」』]+)[”\"」』]",
        r"[，,]\s*([^，。；、]{1,12})\s*[，。；、]?(?:与|并与).{0,20}(?:并列|齐名)",
    ]
    for pattern in honor_patterns:
        m = re.search(pattern, raw)
        candidate = str(m.group(1) or "").strip() if m else ""
        if candidate and _is_valid_title(candidate):
            return candidate
    m = re.search(r"“([^”]+)”", raw)
    if m:
        candidate = m.group(1).strip()
        if _is_valid_title(candidate):
            return candidate
    return ""


def _clean_short_review_text(text: str, *, max_len: int = 88) -> str:
    raw = str(text or "").strip()
    if not raw:
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
        cleaned = _clean_short_review_text(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _collect_self_review_candidates(locations: List[Dict[str, str]], work_texts: Dict[str, str]) -> Tuple[List[str], List[str]]:
    raw_candidates: List[str] = []
    for loc in locations:
        raw_candidates.extend(split_quote_lines(str(loc.get("quotes") or "")))
    direct_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" not in str(item or "")])
    work_candidates = _dedupe_review_candidates([item for item in raw_candidates if "《" in str(item or "")])
    work_candidates.extend(_dedupe_review_candidates([str(text or "") for text in work_texts.values()]))
    return direct_candidates, _dedupe_review_candidates(work_candidates)


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
        [explicit_short_review_candidates, self_work_candidates, record_review_candidates, self_direct_candidates, literary_review_candidates, generic_review_candidates]
        if _is_literary_person(info)
        else [explicit_short_review_candidates, literary_review_candidates, record_review_candidates, self_direct_candidates, self_work_candidates, generic_review_candidates]
    )
    for group in candidate_groups:
        for item in group:
            if str(item or "").strip():
                return str(item).strip()
    return _clean_short_review_text(fallback)


def build_points(
    places: List[Dict[str, str]],
    events: List[Dict[str, str]],
    *,
    allow_geocode: bool = True,
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    geocode_city: Callable[[str], Optional[Coord]],
    event_callback: Optional[callable] = None,
) -> List[Dict[str, object]]:
    del event_callback
    if not isinstance(places, list) or not isinstance(events, list):
        return []
    pts: List[Dict[str, object]] = []
    for p in places:
        name = p.get("modern") or p.get("ancient") or ""
        if not name:
            continue
        coord = lookup_coords_from_historical_index(p.get("ancient") or "", p.get("modern") or "", name)
        if allow_geocode and (not coord):
            coord = geocode_city(name)
        if not coord:
            continue
        lat, lon = coord
        matched = []
        for e in events:
            desc = e.get("desc") or ""
            if name and name in desc:
                matched.append(e)
        lines = [f"**{name}**", ""]
        items = matched[:6] if matched else events[:3]
        for e in items:
            era = e.get("era", "")
            ad = e.get("ad", "")
            desc = e.get("desc", "")
            lines.append(f"- {era} / {ad}：{desc}")
        pts.append({"name": name, "lat": lat, "lon": lon, "md": "\n".join(lines)})
    return pts


def extract_intro_fields(md: str) -> Dict[str, str]:
    if not isinstance(md, str):
        return {"朝代": "", "身份": "", "生卒年": "", "主要事件": "", "主要作品": "", "历史地位": "", "一生行程": ""}
    lines = md.splitlines()
    in_intro = False
    fields = {"朝代": "", "身份": "", "生卒年": "", "主要事件": "", "主要作品": "", "历史地位": "", "一生行程": ""}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            in_intro = title == "简介"
            continue
        if not in_intro:
            continue
        t = stripped
        if "：" in t:
            k, v = t.split("：", 1)
            k = k.strip()
            v = v.strip()
            if k in fields:
                fields[k] = v
    if any(fields.values()):
        return fields
    info = parser_utils._parse_basic_info(md)
    if info:
        if not fields["朝代"]:
            fields["朝代"] = info.get("时代", "") or info.get("朝代", "")
        if not fields["身份"]:
            fields["身份"] = info.get("主要身份", "")
        if not fields["历史地位"]:
            fields["历史地位"] = info.get("历史地位", "")
        if not fields["主要事件"]:
            fields["主要事件"] = info.get("主要成就", "")
        if not fields["生卒年"]:
            birth_text = info.get("出生", "")
            death_text = info.get("去世", "")
            birth_date, _ = parser_utils._parse_date_location(birth_text, ["出生于", "生于"])
            death_date, _ = parser_utils._parse_date_location(death_text, ["卒于", "去世于", "卒"])
            if birth_date or death_date:
                fields["生卒年"] = f"{birth_date}-{death_date}".strip("-")
            else:
                fields["生卒年"] = " / ".join([t for t in [birth_text, death_text] if t])
    in_section = False
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            if "人生足迹地图说明" in title:
                in_section = True
                continue
            if in_section:
                break
        if not in_section or "：" not in line:
            continue
        label = ""
        m = re.search(r"\*\*(.+?)\*\*", line)
        if m:
            label = m.group(1).strip()
        val = line.split("：", 1)[-1].strip()
        if label == "行程概览":
            fields["一生行程"] = val
            break
        if not fields["一生行程"] and label in {"时间跨度", "地理范围"}:
            fields["一生行程"] = val
    return fields


def build_profile_data(
    md: str,
    *,
    fallback_person: str = "",
    allow_geocode: bool = True,
    event_callback: Optional[callable] = None,
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    batch_split_ancient_modern: Callable[[List[str], Optional[callable]], None],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    build_points_fn: Callable[..., List[Dict[str, object]]],
) -> Optional[Dict[str, object]]:
    if not isinstance(md, str) or not md.strip():
        return None
    parsed_doc = parser_utils.parse_story_document(md)
    normalized_md = parsed_doc.normalized_markdown
    info = dict(parsed_doc.basic_info_map)
    locations = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    coords_cache = dict(parsed_doc.coords_table)
    coords_search_map = dict(parsed_doc.coords_search_map)
    if not info:
        fields = extract_intro_fields(normalized_md)
        name_guess = ""
        for line in normalized_md.splitlines():
            t = line.strip()
            if t.startswith("# "):
                name_guess = t[2:].strip()
                break
        if any(fields.values()):
            info = {}
            if name_guess:
                info["姓名"] = name_guess
            dynasty = str(fields.get("朝代") or "").strip()
            if dynasty:
                info["时代"] = dynasty
            identity = str(fields.get("身份") or "").strip()
            if identity:
                info["主要身份"] = identity
            hist = str(fields.get("历史地位") or "").strip()
            if hist:
                info["历史地位"] = hist
            events_text = str(fields.get("主要事件") or "").strip()
            works_text = str(fields.get("主要作品") or "").strip()
            if events_text:
                info["主要成就"] = events_text
            elif works_text:
                info["主要成就"] = works_text
        elif name_guess:
            info = {"姓名": name_guess}
        if not locations and coords_cache:
            locations = [
                {
                    "name": key,
                    "location": key,
                    "type": "move",
                    "time": "",
                    "duration": "",
                    "event": "",
                    "significance": "",
                    "quotes": "",
                }
                for key in coords_cache.keys()
                if str(key or "").strip()
            ]
        if not info and not locations:
            return None
    fallback_person = str(fallback_person or "").strip()
    name_raw = info.get("姓名", "") or fallback_person
    name = name_raw.split("（", 1)[0].strip() or name_raw.strip()
    title = extract_title_from_text(info.get("历史地位", "")) or extract_title_from_text(name_raw) or ""
    description = parsed_doc.overview
    if not description:
        description = "；".join([t for t in [info.get("历史地位", ""), info.get("主要成就", "")] if t])
    description = re.sub(r"-{3,}$", "", description).strip()
    works = extract_works(" ".join([description, info.get("主要成就", ""), info.get("历史地位", "")]))
    work_texts = extract_work_texts(normalized_md)
    short_review = choose_short_review(
        info=info,
        locations=locations,
        work_texts=work_texts,
        historical_reviews=parsed_doc.historical_reviews,
        fallback=title,
    )
    birth_text = info.get("出生", "")
    death_text = info.get("去世", "")
    birth_date, birth_loc = parser_utils._parse_date_location(birth_text, ["出生于", "生于"])
    death_date, death_loc = parser_utils._parse_date_location(death_text, ["卒于", "去世于", "卒"])

    if not locations:
        try:
            pts = build_points_fn(
                parsed_doc.places,
                parsed_doc.events,
                allow_geocode=allow_geocode,
                event_callback=event_callback,
            )
        except Exception:
            pts = []
        loc_items: List[Dict[str, object]] = []
        for p in pts:
            if not isinstance(p, dict):
                continue
            name0 = str(p.get("name") or "").strip()
            try:
                lat = float(p.get("lat"))  # type: ignore[arg-type]
                lng = float(p.get("lon"))  # type: ignore[arg-type]
            except Exception:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            loc_items.append(
                {
                    "name": name0,
                    "location": name0,
                    "ancient": name0,
                    "modern": "",
                    "lat": lat,
                    "lng": lng,
                    "type": "move",
                    "time": "",
                    "stay": "",
                    "event": "",
                    "meaning": "",
                    "quote": "",
                    "md": str(p.get("md") or ""),
                }
            )
        if loc_items:
            locations = loc_items

    loc_texts = [birth_loc, death_loc]
    loc_texts.extend([loc.get("location") or loc.get("name") or "" for loc in locations])
    batch_split_ancient_modern(loc_texts, event_callback=event_callback)
    lifespan = info.get("享年", "")
    birth_modern = split_ancient_modern(birth_loc, event_callback)[1]
    death_modern = split_ancient_modern(death_loc, event_callback)[1]
    birth_geo = parser_utils._pick_geocode_name(birth_modern or birth_loc)
    death_geo = parser_utils._pick_geocode_name(death_modern or death_loc)
    birth_coord = parser_utils._extract_inline_coord_pair(birth_text) or fuzzy_coord_lookup(coords_cache, [birth_geo, birth_modern, birth_loc])
    death_coord = parser_utils._extract_inline_coord_pair(death_text) or fuzzy_coord_lookup(coords_cache, [death_geo, death_modern, death_loc])
    if not birth_coord:
        birth_coord = lookup_coords_from_historical_index(birth_geo, birth_modern, birth_loc)
    if not death_coord:
        death_coord = lookup_coords_from_historical_index(death_geo, death_modern, death_loc)
    if allow_geocode and (not birth_coord) and birth_geo:
        birth_coord = resolve_place_coord(birth_geo, None, birth_loc, birth_modern)
    if allow_geocode and (not death_coord) and death_geo:
        death_coord = resolve_place_coord(death_geo, None, death_loc, death_modern)

    dynasty = (info.get("时代", "") or info.get("朝代", "")).strip()
    courtesy_name = str(info.get("字", "") or info.get("表字", "")).strip()
    art_name = str(info.get("号", "") or info.get("别号", "")).strip()
    aliases = _split_person_alias_values(
        info.get("别名", ""),
        info.get("别称", ""),
        info.get("曾用名", ""),
        info.get("又名", ""),
        courtesy_name,
        art_name,
    )
    person = {
        "name": name or "人物",
        "title": title,
        "description": description,
        "quote": short_review or title,
        "shortReview": short_review or title,
        "dynasty": dynasty,
        "courtesyName": courtesy_name,
        "artName": art_name,
        "aliases": aliases,
        "birthplace": birth_loc,
        "avatar": "",
        "birth": {
            "date": birth_date,
            "location": birth_loc,
            "lat": birth_coord[0] if birth_coord else None,
            "lng": birth_coord[1] if birth_coord else None,
            "coordSystem": "WGS84" if birth_coord else "",
        },
        "death": {
            "date": death_date,
            "location": death_loc,
            "lat": death_coord[0] if death_coord else None,
            "lng": death_coord[1] if death_coord else None,
            "coordSystem": "WGS84" if death_coord else "",
        },
        "lifespan": lifespan,
        "highlights": {
            "honor": title,
            "status": (info.get("历史地位", "") or "").strip(),
            "identities": (info.get("主要身份", "") or "").strip(),
            "achievements": (info.get("主要成就", "") or "").strip(),
            "works": works,
            "reviews": parsed_doc.historical_reviews,
        },
    }

    loc_items: List[Dict[str, object]] = []
    for loc in locations:
        loc_text = loc.get("location") or loc.get("name") or ""
        ancient, modern = split_ancient_modern(loc_text, event_callback)
        geo_name = parser_utils._pick_geocode_name(modern or loc_text or loc.get("name") or ancient)
        coord_candidates = [geo_name, modern, loc_text, loc.get("name") or "", ancient]
        coord = parser_utils._extract_inline_coord_pair(loc_text) or fuzzy_coord_lookup(coords_cache, coord_candidates)
        if not coord:
            coord = _loose_coord_lookup(coords_cache, coord_candidates)
        search_name = ""
        for candidate_key in [
            geo_name,
            parser_utils._pick_geocode_name(modern) if modern else "",
            parser_utils._pick_geocode_name(loc_text) if loc_text else "",
            parser_utils._pick_geocode_name(loc.get("name") or "") if loc.get("name") else "",
        ]:
            if candidate_key and candidate_key in coords_search_map:
                search_name = coords_search_map[candidate_key]
                break
        if (not search_name) and coords_search_map:
            for candidate_key in coord_candidates:
                loose_candidate = _loose_place_key(candidate_key)
                if not loose_candidate:
                    continue
                for raw_key, raw_search in coords_search_map.items():
                    if loose_candidate in _loose_place_key(raw_key):
                        search_name = raw_search
                        break
                if search_name:
                    break
        if not coord:
            coord = lookup_coords_from_historical_index(
                geo_name,
                search_name,
                ancient,
                modern,
                loc_text,
                loc.get("name") or "",
            )
        geocode_candidates = []
        if search_name:
            geocode_candidates.append(search_name)
        if geo_name and geo_name not in geocode_candidates:
            geocode_candidates.append(geo_name)
        if allow_geocode and (not coord):
            for candidate in geocode_candidates:
                year = None
                try:
                    m = re.search(r"(?<!\d)(-?\d{1,4})(?!\d)", str(loc.get("time") or ""))
                    year = int(m.group(1)) if m else None
                except Exception:
                    year = None
                coord = resolve_place_coord(
                    candidate,
                    year,
                    ancient,
                    modern,
                    loc_text,
                    loc.get("name") or "",
                )
                if coord:
                    break
        if not coord:
            continue
        works = extract_works(" ".join([loc.get("event", ""), loc.get("significance", "")]))
        quote_lines = split_quote_lines(loc.get("quotes", ""))
        inferred_significance = _infer_location_significance(
            loc,
            person_name=name or fallback_person,
        )
        loc_items.append(
            {
                "name": loc.get("name") or geo_name,
                "ancientName": ancient or loc.get("name") or "",
                "modernName": modern or loc_text,
                "lat": coord[0],
                "lng": coord[1],
                "coordSystem": "WGS84",
                "type": loc.get("type", "normal"),
                "event": loc.get("event", ""),
                "time": loc.get("time", ""),
                "duration": loc.get("duration", ""),
                "significance": inferred_significance,
                "works": works,
                "quoteLines": quote_lines,
            }
        )
    if not loc_items:
        if coords_cache and not (birth_coord or death_coord):
            loc_items = [
                {
                    "name": key,
                    "ancientName": "",
                    "modernName": key,
                    "lat": coord[0],
                    "lng": coord[1],
                    "coordSystem": "WGS84",
                    "type": "move",
                    "event": "",
                    "time": "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                }
                for key, coord in coords_cache.items()
                if str(key or "").strip()
            ]
        elif birth_coord or death_coord:
            birth_ancient, birth_modern_2 = split_ancient_modern(birth_loc, event_callback)
            death_ancient, death_modern_2 = split_ancient_modern(death_loc, event_callback)
            fallback_items: List[Dict[str, object]] = []
            if birth_coord:
                fallback_items.append(
                    {
                    "name": birth_modern_2 or birth_modern or birth_loc or "出生地",
                    "ancientName": birth_ancient or "",
                    "modernName": birth_modern_2 or birth_modern or birth_loc or "",
                    "lat": birth_coord[0],
                    "lng": birth_coord[1],
                    "coordSystem": "WGS84",
                    "type": "birth",
                    "event": "出生",
                    "time": birth_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                    }
                )
            if death_coord:
                fallback_items.append(
                    {
                    "name": death_modern_2 or death_modern or death_loc or "去世地",
                    "ancientName": death_ancient or "",
                    "modernName": death_modern_2 or death_modern or death_loc or "",
                    "lat": death_coord[0],
                    "lng": death_coord[1],
                    "coordSystem": "WGS84",
                    "type": "death",
                    "event": "去世",
                    "time": death_date or "",
                    "duration": "",
                    "significance": "",
                    "works": [],
                    "quoteLines": [],
                    }
                )
            loc_items = fallback_items
        else:
            loc_items = []
    loc_items = _collapse_sparse_single_site_locations(loc_items)
    loc_items = _sort_profile_locations(loc_items)
    return {
        "person": person,
        "locations": loc_items,
        "coordinateSystem": "WGS84",
        "mapStyle": {
            "pathColor": "#1e40af",
            "markers": {
                "normal": {"color": "#3498db"},
                "birth": {"color": "#2ecc71"},
                "death": {"color": "#e74c3c"},
            },
        },
        "textbookPoints": parsed_doc.textbook_points,
        "examPoints": parsed_doc.exam_points,
        "workTexts": work_texts,
    }


def load_profile_from_md(
    md: str,
    *,
    fallback_person: str = "",
    allow_geocode: bool = True,
    event_callback: Optional[callable] = None,
    split_ancient_modern: Callable[[str, Optional[callable]], Tuple[str, str]],
    batch_split_ancient_modern: Callable[[List[str], Optional[callable]], None],
    fuzzy_coord_lookup: Callable[[Dict[str, Coord], List[str]], Optional[Coord]],
    lookup_coords_from_historical_index: Callable[..., Optional[Coord]],
    resolve_place_coord: Callable[..., Optional[Coord]],
    build_points_fn: Callable[..., List[Dict[str, object]]],
) -> Optional[Dict[str, object]]:
    if not md:
        return None
    return build_profile_data(
        md,
        fallback_person=fallback_person,
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=split_ancient_modern,
        batch_split_ancient_modern=batch_split_ancient_modern,
        fuzzy_coord_lookup=fuzzy_coord_lookup,
        lookup_coords_from_historical_index=lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        build_points_fn=build_points_fn,
    )

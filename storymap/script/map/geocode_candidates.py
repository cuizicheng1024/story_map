from __future__ import annotations

import re
from typing import Callable, List, Optional

_PAREN_CONTENT_RE = re.compile(r"[（(].*?[)）]")
_GEOCODE_PREFIX_RE = re.compile(
    r"^(?:出生于|生于|去世于|卒于|逝于|死于|位于|位在|今属|今为|今在|今称|今名为|古称|又称|旧称|别称|地点(?:为)?|位置(?:为)?|故里|故乡|籍贯|祖籍|原籍)\s*[:：]?\s*"
)
_FOREIGN_LOCATION_MARKERS = (
    "吉尔吉斯斯坦", "巴基斯坦", "阿富汗", "澳大利亚", "新西兰", "阿根廷", "葡萄牙",
    "俄罗斯", "美国", "英国", "法国", "德国", "日本", "韩国", "朝鲜", "越南", "泰国",
    "缅甸", "老挝", "柬埔寨", "印度", "伊朗", "伊拉克", "土耳其", "埃及", "加拿大",
    "墨西哥", "巴西", "西班牙", "意大利", "荷兰", "比利时", "瑞士", "瑞典", "挪威",
    "芬兰", "丹麦", "爱尔兰", "以色列", "沙特", "阿联酋", "卡塔尔", "南非", "共和国",
    "王国", "联邦", "斯坦",
)
_GEOCODE_REJECT_EXACT = {
    "-",
    "--",
    "—",
    "——",
    "未知",
    "不详",
    "无",
    "暂无",
    "地点",
    "位置",
    "地名",
    "某地",
    "当地",
    "此地",
    "这里",
    "那里",
    "去世",
    "出生",
    "出生地",
    "去世地",
    "逝世",
    "死亡",
    "中国",
    "全国",
    "世界",
    "海外",
    "国内",
    "各地",
    "中国去世",
    "中国出生",
}
_GEOCODE_REJECT_PATTERNS = (
    re.compile(r"(?:待考|不详|未知|存疑|说法不一|一说|另说|传说|推测|可能|未详|无确切|缺乏确切|史载不详)"),
    re.compile(r"(?:具体|确切).{0,8}(?:位置|地点|地名)"),
    re.compile(r"(?:位置|地点|地名).{0,8}(?:不详|待考|存疑|未知|不明)"),
    re.compile(r"(?:出生|去世|逝世|卒|死亡)(?:地|于)?$"),
)


def looks_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def looks_foreign_location(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    return any(marker in value for marker in _FOREIGN_LOCATION_MARKERS)


def is_meaningful_place_candidate(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if value in _GEOCODE_REJECT_EXACT:
        return False
    return bool(re.search(r"[^\W_]", value, flags=re.UNICODE))


def trim_geocode_candidate(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = _PAREN_CONTENT_RE.sub("", value)
    previous = None
    while value and value != previous:
        previous = value
        value = _GEOCODE_PREFIX_RE.sub("", value).strip()
    value = re.split(r"[\n\r]+", value, maxsplit=1)[0].strip()
    value = re.split(r"[，,。；;：:]", value, maxsplit=1)[0].strip()
    value = value.strip(" 、，,；;:：()（）[]【】<>《》\"'“”‘’")
    return value


def reject_geocode_candidate_reason(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "empty"
    cleaned = trim_geocode_candidate(raw)
    if not cleaned:
        return "empty_after_trim"
    if cleaned in _GEOCODE_REJECT_EXACT:
        return "generic_term"
    if any(pattern.search(raw) or pattern.search(cleaned) for pattern in _GEOCODE_REJECT_PATTERNS):
        return "non_place_phrase"
    if not is_meaningful_place_candidate(cleaned):
        return "not_meaningful"
    return ""


def build_geocode_candidates(
    name: str,
    *,
    on_rejected: Optional[Callable[[str, str, str], None]] = None,
) -> List[str]:
    base = str(name or "").strip()
    if not base:
        return []
    seen = set()
    items = [base]
    paren = re.findall(r"[（(]([^）)]+)[）)]", base)
    for part in paren:
        part = part.strip()
        if not part:
            continue
        if part.startswith("今") and len(part) > 1:
            items.append(part[1:].strip())
        items.append(part)
    split_markers = ["、", "，", ",", "；", ";", "和", "及", " / ", "/"]
    for marker in split_markers:
        if marker in base:
            left = base.split(marker, 1)[0].strip()
            if left:
                items.append(left)
            break
    if looks_foreign_location(base):
        for marker in sorted(_FOREIGN_LOCATION_MARKERS, key=len, reverse=True):
            if marker and base.startswith(marker):
                trimmed = base[len(marker):].strip(" ，,；;:/·•()（）")
                if trimmed:
                    items.append(trimmed)
    if looks_chinese(base) and "中国" not in base and "China" not in base and not looks_foreign_location(base):
        items.append(f"中国{base}")
        items.append(f"{base} 中国")
    out: List[str] = []
    for item in items:
        raw = item.strip()
        cleaned = trim_geocode_candidate(raw)
        reason = reject_geocode_candidate_reason(raw)
        if reason:
            if callable(on_rejected):
                on_rejected(raw, reason, cleaned)
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


__all__ = [
    "build_geocode_candidates",
    "is_meaningful_place_candidate",
    "looks_chinese",
    "looks_foreign_location",
    "reject_geocode_candidate_reason",
    "trim_geocode_candidate",
]

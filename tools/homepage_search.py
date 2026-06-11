from __future__ import annotations

import re
import warnings
from typing import Dict, List

try:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"codecs\.open\(\) is deprecated.*",
            category=DeprecationWarning,
            module=r"pypinyin(\..*)?",
        )
        from pypinyin import lazy_pinyin  # type: ignore
except Exception:
    lazy_pinyin = None


HAS_PINYIN = lazy_pinyin is not None


def unique_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def normalize_search_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""
    normalized = normalized.replace("·", "").replace("・", "").replace("•", "").replace("‧", "")
    normalized = re.sub(r"[“”\"'`‘’]+", "", normalized)
    normalized = re.sub(r"[\s\-_./,，、:：;；()（）\[\]{}<>《》]+", "", normalized)
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)
    return normalized.strip()


def split_search_terms(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = [raw]
    parts.extend(re.split(r"[\\/|,，、;；:：\s（）()]+", raw))
    return unique_keep_order(parts)


def pinyin_variants(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw or lazy_pinyin is None:
        return []
    if not re.search(r"[\u4e00-\u9fff]", raw):
        return []
    try:
        tokens = [str(item).strip().lower() for item in lazy_pinyin(raw, errors="ignore") if str(item).strip()]
    except Exception:
        return []
    if not tokens:
        return []
    full = normalize_search_text("".join(tokens))
    initials = normalize_search_text("".join([item[0] for item in tokens if item]))
    variants: List[str] = []
    if len(full) >= 2:
        variants.append(full)
    if len(initials) >= 2 and initials != full:
        variants.append(initials)
    return unique_keep_order(variants)


def build_search_fields(name: str, aliases: List[str], foreign_name: str) -> Dict[str, List[str]]:
    raw_terms: List[str] = []
    raw_terms.extend(split_search_terms(name))
    for alias in aliases or []:
        raw_terms.extend(split_search_terms(alias))
    if foreign_name:
        raw_terms.extend(split_search_terms(foreign_name))
    raw_terms = unique_keep_order(raw_terms)

    normalized_terms: List[str] = []
    pinyin_terms: List[str] = []
    for term in raw_terms:
        normalized = normalize_search_text(term)
        if normalized:
            normalized_terms.append(normalized)
        pinyin_terms.extend(pinyin_variants(term))

    search_tokens = unique_keep_order(normalized_terms + pinyin_terms)
    return {
        "search_keys": raw_terms[:16],
        "search_tokens": search_tokens[:32],
        "search_pinyin": unique_keep_order(pinyin_terms)[:12],
    }


__all__ = [
    "HAS_PINYIN",
    "build_search_fields",
    "normalize_search_text",
    "pinyin_variants",
    "split_search_terms",
    "unique_keep_order",
]

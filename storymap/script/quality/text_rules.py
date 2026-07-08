from __future__ import annotations

import re

_THINK_PATTERN_DEFS: list[tuple[str, str]] = [
    (r"The user wants me to .*?into a structured JSON format\.\s*", ""),
    (r"Since there (?:are|is) no external material[s]? provided,.*?cautions\.\s*", ""),
    (r"Let me think about what I know about [^:]+:\s*", ""),
    (r"Let me organize what I know about [^:]+:\s*", ""),
    (r"Let me (?:think|organize|draft|refine|check|structure|finalize)[^.]*\.\s*", ""),
    (r"I need to .*?(?:\.\s*|\n)", ""),
    (r"Actually wait[^.]*\.\s*", ""),
    (r"Looking good[^.]*\.\s*", ""),
    (r"I'll .*? structure[^.]*\.\s*", ""),
    (r"I want to [^。.]*[。.]\s*", ""),
    (r"I want to [^。.]*\s*$", ""),
    (r"Total roughly[^.]*\.\s*", ""),
    (r"(?:^|\n)- [^\n]+?(?:courtesy name|Dynasty|Era|Key identit|Key achievement)[^\n]*\n", "\n"),
    (r"(?:^|\n)- [^\n]*?(?:Born:|Died:|Classical period|Child prodigy|Major works:)[^\n]*\n", "\n"),
]


def cn_to_int(s: str) -> int | None:
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if s in cn_map:
        return cn_map[s]
    if "十" in s:
        parts = s.split("十")
        tens = cn_map.get(parts[0], 1) if parts[0] else 1
        ones = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def get_think_patterns() -> list[re.Pattern]:
    return [
        re.compile(pattern, re.IGNORECASE | (re.DOTALL if "." in pattern else 0))
        for pattern, _ in _THINK_PATTERN_DEFS
    ]


def get_think_replacements() -> list[tuple[str, str]]:
    return list(_THINK_PATTERN_DEFS)


__all__ = ["cn_to_int", "get_think_patterns", "get_think_replacements"]

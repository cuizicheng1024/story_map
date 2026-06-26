from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


_PERSON_CANONICAL_REGISTRY: Dict[str, str] = {
    "苏东坡": "苏轼",
    "唐三藏": "玄奘",
    "唐太宗": "李世民",
    "毛主席": "毛泽东",
    "乔纳森": "乔纳森·斯威夫特",
}


def normalize_person_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[（(].*?[）)]", "", text).strip()
    text = re.sub(r"[《》【】\[\]<>\"“”‘’·•\s]+", "", text)
    return text.strip()


def person_redirects(available_names: Optional[Iterable[str]] = None) -> Dict[str, str]:
    redirects = dict(_PERSON_CANONICAL_REGISTRY)
    if available_names is None:
        return redirects
    # redirect 是否生效要看当前磁盘状态：如果别名已经有独立 Markdown，
    # 就保留真实人物页，不再把它当成纯跳转名。
    available_tokens = {normalize_person_token(name) for name in available_names if normalize_person_token(name)}
    filtered: Dict[str, str] = {}
    for alias, canonical in redirects.items():
        alias_token = normalize_person_token(alias)
        canonical_token = normalize_person_token(canonical)
        # A real Markdown source should win over redirect behavior.
        if alias_token and alias_token in available_tokens:
            continue
        if canonical_token and canonical_token not in available_tokens:
            continue
        filtered[str(alias).strip()] = str(canonical).strip()
    return filtered


def canonical_person_name(value: Any, available_names: Optional[Iterable[str]] = None) -> str:
    token = normalize_person_token(value)
    if not token:
        return ""
    canonical = str(_PERSON_CANONICAL_REGISTRY.get(token) or token).strip()
    if available_names is None:
        return canonical or token
    available_map = {
        normalize_person_token(name): str(name or "").strip()
        for name in available_names
        if normalize_person_token(name)
    }
    available = set(available_map)
    # 如果别名本身已经有真实 Markdown 页面，就保留真实页面名，
    # 不再把它继续折叠回 canonical 名。
    if token in available:
        return available_map.get(token, token)
    if canonical != token and canonical not in available:
        return token
    return available_map.get(canonical, canonical) or token


def canonical_story_name_entries(raw_names: Iterable[str]) -> List[Tuple[str, str, List[str]]]:
    raw_items = [str(name or "").strip() for name in raw_names if str(name or "").strip()]
    # 这里必须保留原始故事文件名，canonical 合并已经下沉到 redirect 层；
    # 否则构建阶段会错误改写真实文件名。与此同时，首页搜索和节点 alias
    # 仍然需要知道“哪些纯别名应归到这个真实人物页”。
    redirects = person_redirects(raw_items)
    alias_map: Dict[str, List[str]] = {}
    for alias, canonical in redirects.items():
        alias_name = str(alias or "").strip()
        canonical_name = str(canonical or "").strip()
        if not alias_name or not canonical_name:
            continue
        alias_map.setdefault(canonical_name, []).append(alias_name)
    return [
        (raw_name, raw_name, sorted(alias_map.get(raw_name, [])))
        for raw_name in sorted(raw_items)
    ]

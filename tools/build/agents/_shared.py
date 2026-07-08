"""共享工具 — Agent 间复用的纯函数。

避免 searcher/editor/geolocator 中重复定义 _parse_embedded_json。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from storymap.script.quality.text_rules import cn_to_int, get_think_patterns, get_think_replacements

# ── JSON 提取正则（加固版） ──
# 使用 [^}]* 逐字段匹配替代 .*? 避免 markdown 中的 }; 提前截断
_JSON_IN_SCRIPT = re.compile(
    r"window\.__EXPORT_DATA__\s*=\s*(\{.*?\});\s*</script>",
    re.DOTALL,
)
_JSON_IN_CONST = re.compile(
    r'const data = (\{.*?"person".*?\});\s*window\.__EXPORT_DATA__',
    re.DOTALL,
)


def parse_embedded_json(html: str) -> tuple[dict | None, str | None]:
    """从 HTML 内嵌 <script> 中提取 __EXPORT_DATA__ JSON。

    支持两种格式：
      - window.__EXPORT_DATA__ = {...};
      - const data = {...}; window.__EXPORT_DATA__ = data;

    Returns:
        (parsed_dict, raw_json_string) 或 (None, None)
    """
    m = _JSON_IN_SCRIPT.search(html)
    if not m:
        m = _JSON_IN_CONST.search(html)
    if not m:
        return None, None

    raw = m.group(1)
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return None, None


from __future__ import annotations

import re
from typing import Dict, List

from ...core import parsers as parser_utils
from ...map.geocode_candidates import reject_geocode_candidate_reason


def summarize_samples(items: List[str], limit: int = 3) -> str:
    if not items:
        return ""
    samples = items[:limit]
    more = len(items) - len(samples)
    sample_text = "、".join(samples)
    if more > 0:
        return f"{sample_text} 等 {more} 个"
    return sample_text


def collect_quality_metrics(md: str) -> Dict[str, int]:
    if not isinstance(md, str):
        return {"timeline_rows": 0, "places": 0, "locations": 0, "coords": 0}
    parsed_doc = parser_utils.parse_story_document(md)
    return {
        "timeline_rows": len(parsed_doc.timeline_rows),
        "places": len(parsed_doc.places),
        "locations": len(parsed_doc.location_sections),
        "coords": len(parsed_doc.coords_table),
    }


_KNOWN_ANCIENT_PLACE_REFERENCE: Dict[str, tuple[float, float]] = {
    "长安": (34.261, 108.940),
    "洛阳": (34.618, 112.454),
    "建康": (32.058, 118.796),
    "金陵": (32.058, 118.796),
    "汴京": (34.797, 114.308),
    "汴梁": (34.797, 114.308),
    "临安": (30.259, 120.168),
    "大都": (39.904, 116.407),
    "燕京": (39.904, 116.407),
    "盛京": (41.804, 123.431),
    "邺城": (36.347, 114.410),
    "许昌": (34.035, 113.852),
    "荆州": (30.335, 112.240),
    "益州": (30.573, 104.067),
    "幽州": (39.904, 116.407),
    "凉州": (37.928, 102.641),
    "扬州": (32.394, 119.413),
    "江陵": (30.335, 112.240),
    "会稽": (30.003, 120.582),
    "襄阳": (32.009, 112.123),
    "汉中": (33.068, 107.023),
    "碎叶城": (42.833, 75.300),
    "蜀中": (30.573, 104.067),
    "夜郎": (26.500, 106.700),
    "楼兰": (40.516, 89.833),
    "龟兹": (41.726, 82.936),
    "于阗": (37.114, 79.922),
    "疏勒": (39.468, 75.993),
    "大宛": (40.528, 71.787),
    "月氏": (39.628, 67.470),
    "匈奴王庭": (47.919, 106.917),
    "轮台": (41.727, 84.253),
    "玉门关": (40.354, 93.866),
    "阳关": (39.928, 94.258),
    "高昌": (42.926, 89.183),
    "交趾": (21.029, 105.852),
    "日南": (16.464, 107.585),
    "象郡": (22.817, 108.328),
    "桂林郡": (25.274, 110.290),
    "南海郡": (23.129, 113.264),
    "陇西": (34.978, 104.636),
    "北地": (36.064, 107.625),
    "上郡": (38.044, 109.742),
    "九原": (40.597, 109.960),
    "云中": (40.787, 111.704),
    "雁门": (39.073, 112.808),
    "代郡": (39.915, 114.287),
    "渔阳": (40.133, 117.400),
    "右北平": (40.980, 118.673),
    "辽西": (41.129, 121.121),
    "辽东": (41.129, 123.431),
    "西域": (41.000, 85.000),
    "漠北": (48.000, 106.000),
    "岭南": (23.500, 112.000),
    "江东": (31.500, 119.500),
    "巴蜀": (30.500, 104.000),
    "中原": (34.500, 113.500),
    "关东": (34.500, 116.000),
    "河西": (39.000, 100.000),
    "河套": (40.500, 108.000),
    "塞北": (42.000, 115.000),
    "倭国": (34.694, 135.502),
    "高句丽": (41.790, 126.178),
    "百济": (36.350, 127.385),
    "新罗": (35.856, 129.225),
    "平城京": (34.686, 135.789),
    "平安京": (35.012, 135.768),
}

_ANCIENT_PLACE_TOLERANCE_DEG = 2.0
_CN_NUMERALS = "一二三四五六七八九十"
_EXPECTED_SECTION_NUMBERS = ["一", "二", "三", "四", "五"]
_re_section_number = re.compile(r"^##\s+([一二三四五六七八九十])、", re.MULTILINE)


def _validate_ancient_place_coords(coords: Dict[str, tuple[float, float]]) -> List[str]:
    issues: List[str] = []
    mismatches: List[str] = []
    for name, (lat, lon) in coords.items():
        ref = _KNOWN_ANCIENT_PLACE_REFERENCE.get(name)
        if ref is None:
            continue
        ref_lat, ref_lon = ref
        if abs(lat - ref_lat) > _ANCIENT_PLACE_TOLERANCE_DEG or abs(lon - ref_lon) > _ANCIENT_PLACE_TOLERANCE_DEG:
            mismatches.append(f"{name}({lat:.3f},{lon:.3f})→应为({ref_lat:.3f},{ref_lon:.3f})")
    if mismatches:
        issues.append(f"古地名坐标疑似地理编码误识：{'；'.join(mismatches[:5])}")
    return issues


def _validate_section_numbers(md: str, issues: List[str]) -> None:
    found = _re_section_number.findall(md)
    if not found:
        return
    seen: set[str] = set()
    for c in found:
        if c in seen:
            issues.append(f"章节编号重复：「## {c}、」出现多次")
            return
        seen.add(c)
    cn_to_idx = {c: i + 1 for i, c in enumerate(_CN_NUMERALS)}
    indices = [cn_to_idx.get(c) for c in found if c in cn_to_idx]
    if not indices:
        return
    expected = 1
    for idx in indices:
        if idx != expected:
            issues.append(
                f"章节编号不连续：预期「## {_EXPECTED_SECTION_NUMBERS[expected-1] if expected <= len(_EXPECTED_SECTION_NUMBERS) else _CN_NUMERALS[expected-1]}、」但出现「## {_CN_NUMERALS[idx-1]}、」"
            )
            return
        expected += 1


def validate_data_quality(md: str) -> List[str]:
    if not isinstance(md, str) or not md.strip():
        return ["内容为空或格式不正确"]
    issues: List[str] = []
    parsed_doc = parser_utils.parse_story_document(md)
    _validate_section_numbers(md, issues)

    # ── 检测降级格式（简化版 Markdown，使用 ### 生平 / ### 足迹 代替表格）──
    _degraded_timeline = _detect_degraded_timeline(md)
    _degraded_footprint = _detect_degraded_footprint(md)
    _degraded_coords = _extract_degraded_coords(md)

    header = parsed_doc.timeline_header
    rows = parsed_doc.timeline_rows
    if not header or not rows:
        if _degraded_timeline:
            issues.append("年份表缺失或为空（已检测到降级生平格式，可忽略）")
        else:
            issues.append("年份表缺失或为空")
    else:
        if not any("现称" in c for c in header):
            issues.append("年份表缺少现称列")
        if not any("事件" in c for c in header):
            issues.append("年份表缺少事件列")
    locations = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    if not locations:
        if _degraded_footprint:
            issues.append("重要地点段落缺失或为空（已检测到降级足迹格式，可忽略）")
        else:
            issues.append("重要地点段落缺失或为空")
    else:
        missing_event = [item for item in locations if not (item.get("event") or "").strip()]
        if missing_event and len(missing_event) >= max(1, len(locations) // 2):
            issues.append(f"重要地点事迹缺失较多（{len(missing_event)} / {len(locations)}）")
    place_names = []
    seen_place_names = set()
    for place in parsed_doc.places:
        name = place.get("modern") or place.get("ancient") or ""
        name = parser_utils.pick_geocode_name(name)
        if not name or reject_geocode_candidate_reason(name):
            continue
        if name not in seen_place_names:
            seen_place_names.add(name)
            place_names.append(name)
    coords = parsed_doc.coords_table
    if place_names and not coords:
        # ── 标准格式兜底：检测 "四、生平时间线" 表格是否已包含现称数据 ──
        if _detect_standard_timeline_coords(md):
            issues.append("地点坐标表缺失或为空（已检测到标准时间线表格，可忽略）")
        elif _degraded_coords:
            issues.append("地点坐标表缺失或为空（已检测到降级内联坐标，可忽略）")
        else:
            issues.append("地点坐标表缺失或为空")
    if coords:
        invalid = []
        for name, coord in coords.items():
            lat, lon = coord
            if abs(lat) > 90 or abs(lon) > 180:
                invalid.append(name)
        if invalid:
            issues.append(f"地点坐标存在异常范围：{summarize_samples(invalid)}")
        missing = [name for name in place_names if name not in coords]
        if missing:
            issues.append(f"地点坐标缺失：{summarize_samples(missing)}")
        semantic_issues = _validate_ancient_place_coords(coords)
        if semantic_issues:
            issues.extend(semantic_issues)
    return issues


# ── 标准格式时间线表格检测 ──
# 标准 Markdown 的 "四、生平时间线" 表格：| 年份 | 古称 | 现称 | 事件 |
# 其中"现称"列包含可落点的现代地名，但解析器只识别 "## 地点坐标" 标题，
# 导致 coords_table 为空。此处检测标准表格中是否存在有效现称数据。
_TIMELINE_TABLE_HEADING_RE = re.compile(r"^##\s+.*生平时间线")  # ## 四、生平时间线
_TIMELINE_TABLE_ROW_RE = re.compile(
    r"^\|\s*\d{3,4}\s*[|｜].*?[|｜].*?[|｜]"
)  # | 1140 年 | 历城 | 山东省... |


def _detect_standard_timeline_coords(md: str) -> bool:
    """检测标准格式 "四、生平时间线" 表格中是否存在有效现称数据。

    当表格包含现称列且至少有一行有效地名时，视为坐标数据已充分，
    不应再报"地点坐标表缺失"。
    """
    if not isinstance(md, str):
        return False
    lines = md.splitlines()
    in_section = False
    table_started = False
    row_count = 0
    for line in lines:
        if _TIMELINE_TABLE_HEADING_RE.match(line.strip()):
            in_section = True
            table_started = False
            row_count = 0
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if stripped.startswith("|") and not table_started:
            table_started = True
            # 检查表头是否含"现称"列
            if "现称" not in stripped:
                in_section = False
                table_started = False
            continue
        if table_started:
            if _TIMELINE_TABLE_ROW_RE.match(stripped):
                row_count += 1
            elif not stripped.startswith("|"):
                in_section = False
                table_started = False
    return row_count >= 1


# ── 降级格式检测 ──

_DEGRADED_TIMELINE_LINE_RE = re.compile(r"^- \*\*\d{3,4}.*\*\*：")  # - **1037**：...
_DEGRADED_FOOTPRINT_COORD_RE = re.compile(r"`\[(\d+\.\d+),\s*(\d+\.\d+)\]`")  # `[29.61,103.93]`


def _detect_degraded_timeline(md: str) -> bool:
    """检测是否存在降级生平格式（### 生平 + 带年份的列表项）。"""
    if not isinstance(md, str):
        return False
    lines = md.splitlines()
    in_section = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### 生平") or stripped.startswith("## 生平"):
            in_section = True
            continue
        if in_section and stripped.startswith("#"):
            break
        if in_section and _DEGRADED_TIMELINE_LINE_RE.match(stripped):
            count += 1
    return count >= 2  # 至少 2 条时间线才算有效


def _detect_degraded_footprint(md: str) -> bool:
    """检测是否存在降级足迹格式（### 足迹 + 带坐标的列表项）。"""
    if not isinstance(md, str):
        return False
    lines = md.splitlines()
    in_section = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### 足迹") or stripped.startswith("## 足迹"):
            in_section = True
            continue
        if in_section and stripped.startswith("#"):
            break
        if in_section and _DEGRADED_FOOTPRINT_COORD_RE.search(stripped):
            count += 1
    return count >= 1  # 至少 1 个坐标点


def _extract_degraded_coords(md: str) -> int:
    """提取降级足迹格式中的内联坐标数量。"""
    if not isinstance(md, str):
        return 0
    lines = md.splitlines()
    in_section = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### 足迹") or stripped.startswith("## 足迹"):
            in_section = True
            continue
        if in_section and stripped.startswith("#"):
            break
        if in_section:
            count += len(_DEGRADED_FOOTPRINT_COORD_RE.findall(stripped))
    return count


def print_quality_report(md: str) -> None:
    if not isinstance(md, str):
        print("数据质量检查：\n- 内容为空或格式不正确")
        return
    metrics = collect_quality_metrics(md)
    issues = validate_data_quality(md)
    print("数据质量检查：")
    print(f"- 年份表行数：{metrics['timeline_rows']}")
    print(f"- 地点条目：{metrics['places']}")
    print(f"- 坐标条目：{metrics['coords']}")
    print(f"- 结构化地点：{metrics['locations']}")
    if issues:
        for item in issues:
            print(f"- {item}")
    else:
        print("- 未发现明显问题")

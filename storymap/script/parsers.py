from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_BANNED_PLACE_KEYS = {"中国", "全国", "世界", "海外", "国内", "各地"}

try:
    from .models import BasicInfo, LocationEntry, ParsedStoryDocument
except ImportError:
    from models import BasicInfo, LocationEntry, ParsedStoryDocument


def _is_table_separator(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped.startswith("|"):
        return False
    inner = stripped.strip("|").strip()
    if not inner:
        return False
    cells = [c.strip() for c in inner.split("|")]
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c) is not None for c in cells)


def _pick_geocode_name(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"今([^）)]+)", text)
    if match:
        return match.group(1).strip()
    for sep in [" / ", "/", "或", "、", "，", ",", "；", ";"]:
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    return re.sub(r"[（(].*?[）)]", "", text).strip()


def _normalize_place_key(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"[（(].*?[）)]", "", raw)
    raw = re.sub(r"^(今|现|今称|现称)\s*", "", raw)
    raw = re.sub(r"(省|市|县|区|州|郡|府|道|路|镇|乡|村)$", "", raw)
    raw = re.sub(r"\s+", "", raw)
    return raw.strip()


def _split_ancient_modern(loc_text: str) -> Tuple[str, str]:
    text = str(loc_text or "").strip()
    if not text:
        return "", ""
    m = re.search(r"[（(]\s*今\s*([^）)]+)[）)]", text)
    if m:
        modern = m.group(1).strip()
        ancient = re.sub(r"[（(].*?[）)]", "", text).strip()
        ancient = re.sub(r"^(古称|又称|旧称)[:：]?\s*", "", ancient).strip()
        return ancient, modern
    m = re.search(r"\b今(?:称)?\s*([^\s，。；;、/]+)", text)
    if m:
        modern = m.group(1).strip()
        rest = text[: m.start()].strip()
        rest = re.sub(r"[（(].*?[）)]", "", rest).strip()
        rest = re.sub(r"^(古称|又称|旧称)[:：]?\s*", "", rest).strip()
        return rest, modern
    return "", ""


def _historical_index_candidates() -> List[Path]:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    candidates = [
        repo_root / "data" / "historical_places_index.jsonl",
        repo_root / "historical_places_index.jsonl",
        here.with_name("historical_places_index.jsonl"),
        Path.cwd() / "historical_places_index.jsonl",
    ]
    seen = set()
    result: List[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


@lru_cache(maxsize=1)
def _load_historical_places_index() -> Dict[str, Tuple[float, float]]:
    mapping: Dict[str, Tuple[float, float]] = {}
    index_path: Optional[Path] = None
    for candidate in _historical_index_candidates():
        if candidate.exists() and candidate.is_file():
            index_path = candidate
            break
    if index_path is None:
        return mapping
    try:
        with index_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = (line or "").strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                ancient = str(obj.get("ancient_name") or "").strip()
                modern = str(obj.get("modern_name") or "").strip()
                try:
                    lat = float(obj.get("lat"))
                    lon = float(obj.get("lon"))
                except Exception:
                    continue
                for key in (ancient, modern):
                    norm = _normalize_place_key(key)
                    if norm and norm not in mapping:
                        mapping[norm] = (lat, lon)
    except Exception:
        return {}
    return mapping


def _lookup_coords_from_historical_index(*names: str) -> Optional[Tuple[float, float]]:
    mapping = _load_historical_places_index()
    if not mapping:
        return None
    for name in names:
        norm = _normalize_place_key(name)
        if not norm:
            continue
        coord = mapping.get(norm)
        if coord:
            return coord
    return None


def _fuzzy_coord_lookup(
    coords_cache: Dict[str, Tuple[float, float]],
    candidates: List[str],
) -> Optional[Tuple[float, float]]:
    if not coords_cache:
        return None
    raw_candidates = [str(c or "").strip() for c in candidates if str(c or "").strip()]
    for candidate in raw_candidates:
        if candidate in coords_cache:
            return coords_cache.get(candidate)
    candidate_norms = [_normalize_place_key(c) for c in raw_candidates]
    candidate_norms = [n for n in candidate_norms if n]
    if not candidate_norms:
        return None
    scored: List[Tuple[int, str]] = []
    for key in coords_cache.keys():
        raw_key = str(key or "").strip()
        norm_key = _normalize_place_key(raw_key)
        if not norm_key or norm_key in _BANNED_PLACE_KEYS or len(norm_key) < 2:
            continue
        for candidate_norm in candidate_norms:
            if norm_key in candidate_norm or candidate_norm in norm_key:
                scored.append((len(norm_key), raw_key))
                break
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return coords_cache.get(scored[0][1])


def _parse_timeline_table(md: str) -> tuple[List[str], List[List[str]]]:
    if not isinstance(md, str):
        return [], []
    lines = md.splitlines()
    in_sec = False
    header: List[str] = []
    rows: List[List[str]] = []
    table_started = False
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_sec = title.startswith("年份")
            table_started = False
            header = []
            continue
        if not in_sec:
            continue
        if line.strip().startswith("|") and not table_started:
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            table_started = True
            continue
        if table_started:
            stripped = line.strip()
            if _is_table_separator(stripped):
                continue
            if stripped.startswith("|"):
                rows.append([c.strip() for c in stripped.strip("|").split("|")])
            else:
                break
    if header and rows:
        return header, rows
    header = []
    rows = []
    table_started = False
    for line in lines:
        if line.strip().startswith("|") and not table_started:
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            table_started = True
            continue
        if table_started:
            stripped = line.strip()
            if _is_table_separator(stripped):
                continue
            if stripped.startswith("|"):
                rows.append([c.strip() for c in stripped.strip("|").split("|")])
            else:
                if header and rows and any(
                    any(k in c for k in ("现称", "事件", "年号", "公元")) for c in header
                ):
                    return header, rows
                header = []
                rows = []
                table_started = False
    if header and rows and any(any(k in c for k in ("现称", "事件", "年号", "公元")) for c in header):
        return header, rows
    return [], []


def _parse_basic_info(md: str) -> Dict[str, str]:
    if not isinstance(md, str):
        return {}
    lines = md.splitlines()
    in_profile = False
    in_basic = False
    info: Dict[str, str] = {}
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_profile = "人物档案" in title
            in_basic = False
            continue
        if not in_profile:
            continue
        if line.strip().startswith("### "):
            title = line.strip().lstrip("#").strip()
            in_basic = "基本信息" in title
            continue
        if in_basic:
            m = re.match(r"-\s*\*\*(.+?)\*\*：\s*(.+)", line.strip())
            if m:
                info[m.group(1).strip()] = m.group(2).strip()
    return info


def _parse_overview(md: str) -> str:
    if not isinstance(md, str):
        return ""
    lines = md.splitlines()
    in_profile = False
    in_overview = False
    buf: List[str] = []
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_profile = "人物档案" in title
            if not in_profile:
                in_overview = False
            continue
        if not in_profile:
            continue
        if line.strip().startswith("### "):
            title = line.strip().lstrip("#").strip()
            in_overview = "生平概述" in title
            continue
        if in_overview:
            t = line.strip()
            if not t or re.match(r"^-{3,}$", t):
                continue
            buf.append(t)
    return "".join(buf).strip()


def _parse_textbook_points(md: str) -> str:
    if not isinstance(md, str) or not md.strip():
        return ""
    lines = md.splitlines()
    start_idx: Optional[int] = None
    titles = {
        "## 人教版教材知识点",
        "## 教材知识点",
        "## 教材知识点与考点",
        "## 教材知识点和考点",
    }
    for i, line in enumerate(lines):
        t = line.strip()
        if any(t == x or t.startswith(x + "（") or t.startswith(x + "(") for x in titles):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    buf: List[str] = []
    for line in lines[start_idx:]:
        if line.strip().startswith("## "):
            break
        buf.append(line.rstrip())
    return "\n".join(buf).strip("\n").strip()


def _parse_exam_points(md: str) -> str:
    if not isinstance(md, str) or not md.strip():
        return ""
    lines = md.splitlines()
    titles = {
        "## 初高中阶段考点",
        "## 初高中考点",
        "## 初高中阶段考点信息",
        "## 考点",
        "## 教材考点",
        "## 中考考点",
        "## 高考考点",
    }
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        t = line.strip()
        if any(t == x or t.startswith(x + "（") or t.startswith(x + "(") for x in titles):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    buf: List[str] = []
    for line in lines[start_idx:]:
        if line.strip().startswith("## "):
            break
        buf.append(line.rstrip())
    return "\n".join(buf).strip("\n").strip()


def _derive_exam_points_from_textbook_points(textbook_points: str) -> str:
    t = (textbook_points or "").strip()
    if not t:
        return ""
    t = re.sub(r"^###\s*初中阶段\s*$", "### 初中阶段考点", t, flags=re.M)
    t = re.sub(r"^###\s*高中阶段\s*$", "### 高中阶段考点", t, flags=re.M)
    if "### 初中阶段考点" not in t and "### 高中阶段考点" not in t:
        return "### 考点\n" + t
    return t


def _parse_historical_reviews(md: str) -> List[str]:
    if not isinstance(md, str) or not md.strip():
        return []
    lines = md.splitlines()
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if line.strip() == "### 历史评价":
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    buf: List[str] = []
    for line in lines[start_idx:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("### ") or s.startswith("## "):
            break
        if s.startswith("-"):
            s = s.lstrip("-").strip()
        s = re.sub(r"^\d+\.\s*", "", s).strip()
        if s:
            buf.append(s)
        if len(buf) >= 3:
            break
    return buf


def _parse_location_sections(md: str) -> List[Dict[str, str]]:
    if not isinstance(md, str):
        return []
    lines = md.splitlines()
    in_section = False
    current: Dict[str, str] | None = None
    locations: List[Dict[str, str]] = []
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            if "人生历程" in title or "重要地点" in title:
                in_section = True
                current = None
                continue
            if in_section:
                break
        if not in_section:
            continue
        if line.strip().startswith("### "):
            if current:
                locations.append(current)
            raw_title = line.strip().lstrip("#").strip()
            loc_type = "normal"
            if "出生地" in raw_title:
                loc_type = "birth"
            elif "去世地" in raw_title:
                loc_type = "death"
            name = raw_title.split("：", 1)[-1].strip() if "：" in raw_title else raw_title
            name = re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+", "", name).strip()
            current = {
                "name": name,
                "type": loc_type,
                "time": "",
                "location": "",
                "event": "",
                "significance": "",
                "duration": "",
                "quotes": "",
            }
            continue
        if current:
            m = re.match(r"-\s*\*\*(.+?)\*\*：\s*(.+)", line.strip())
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                if key in {"时间", "时段", "时期", "年代", "公元纪年", "年号纪年"}:
                    current["time"] = val
                elif key in {"位置", "地点"}:
                    current["location"] = val
                elif key in {"事迹", "背景", "经过", "事件"}:
                    current["event"] = (current["event"] + " " + val).strip()
                elif key in {"意义", "影响"}:
                    current["significance"] = val
                elif key in {"停留", "停留时间", "停留时长", "居留", "驻留", "逗留", "在此时间", "在此时长"}:
                    current["duration"] = val
                elif key in {"名篇名句", "代表名句", "名句", "诗句"}:
                    current["quotes"] = (current["quotes"] + "；" + val).strip("；")
    if current:
        locations.append(current)
    return locations


def _parse_date_location(text: str, keys: List[str]) -> tuple[str, str]:
    date = ""
    m = re.search(r"(公元前|前)?\d{1,4}年", text)
    if m:
        date = m.group(0)
    loc_raw = ""
    for k in keys:
        if k in text:
            loc_raw = text.split(k, 1)[-1].strip("。；; ")
            break
    if not loc_raw:
        loc_raw = str(text or "").strip("。；; ")
    try:
        if not re.search(r"(一说|或说|又说|另说)", loc_raw):
            loc_raw = re.sub(
                r"[（(][^）)]*(存疑|不详|未详|未知|无法确认|生年不详|卒年不详)[^）)]*[）)]\s*$",
                "",
                loc_raw,
            )
    except Exception:
        pass
    loc_raw = re.sub(
        r"^\s*(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?\s*[?？]?\s*[，,]?\s*",
        "",
        loc_raw,
    ).strip("。；; ")
    loc_raw = re.sub(r"^\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?\s*[?？]?\s*[，,]?\s*", "", loc_raw).strip("。；; ")
    loc_raw = re.sub(r"^\s*\d{1,2}\s*(?:日|号)\s*[?？]?\s*[，,]?\s*", "", loc_raw).strip("。；; ")
    loc_raw = re.sub(r"^\s*(?:约|大约|约于)?\s*\d{1,2}\s*世纪(?:初|中|末)?\s*[，,]?\s*", "", loc_raw).strip("。；; ")
    parts = [p.strip("。；; ") for p in re.split(r"[，,；;]", loc_raw) if p.strip("。；; ")]
    bad = re.compile(r"(存疑|不详|未详|未知|无法确认|生年不详|卒年不详)")
    date_hint = re.compile(
        r"((公元前|公元|前)?\s*\d{1,4}\s*年|\d{1,2}\s*月|\d{1,2}\s*(?:日|号)|[元正冬腊一二三四五六七八九十百千]+\s*年|[正冬腊一二三四五六七八九十]+\s*月|[初廿卅一二三四五六七八九十]+\s*(?:日|号))"
    )
    place_hint = re.compile(r"(省|市|县|区|州|郡|府|路|镇|乡|村|京|关|岛|山|江|河|湖|海|城|陵|台|庐|寺)")
    loc = ""
    for p in parts:
        if not p or bad.search(p):
            continue
        if date_hint.search(p) and not place_hint.search(p):
            continue
        cand = p.strip("。；; ")
        if not cand:
            continue
        cand = re.sub(r"[（(][^）)]*\d{1,4}\s*年[^）)]*[）)]", "", cand).strip("。；; ")
        cand = re.sub(r"[（(][^）)]*\d{1,2}\s*世纪(?:初|中|末)?[^）)]*[）)]", "", cand).strip("。；; ")
        cand = re.sub(r"^\s*(?:一说|或说|又说|另说|约|大约|约于|或)\s*", "", cand).strip("。；; ")
        cand = re.sub(r"^\s*(公元前|公元|前)?\s*\d{1,4}\s*年\s*[，,；;]?\s*", "", cand).strip("。；; ")
        cand = re.sub(r"^\s*\d{1,2}\s*世纪(?:初|中|末)?\s*[，,；;]?\s*", "", cand).strip("。；; ")
        cand = re.sub(r"(公元前|公元|前)?\s*\d{1,4}\s*年", "", cand).strip("。；; ")
        cand = re.sub(r"\d{1,2}\s*世纪(?:初|中|末)?", "", cand).strip("。；; ")
        if not cand or bad.search(cand):
            continue
        loc = cand
        break
    loc = re.sub(r"^\s*(?:出生于|出生在|生于|生在|于|在)\s*", "", loc.strip("。；; ")).strip("。；; ")
    return date, loc


def _parse_coord_cell(s: str) -> Optional[float]:
    t = str(s or "").strip()
    if not t:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t.replace("−", "-"))
    if not m:
        return None
    try:
        v = float(m.group(0))
    except Exception:
        return None
    neg = bool(re.search(r"(?i)[ws]", t)) or ("西" in t) or ("南" in t)
    if neg and v > 0:
        v = -v
    return v


def _parse_lat_lon_pair(text: str) -> Optional[tuple[float, float]]:
    t = str(text or "").strip()
    if not t:
        return None
    parts = [x.strip() for x in re.split(r"[,，;；]", t) if x.strip()]
    if len(parts) < 2:
        parts = [x.strip() for x in re.split(r"\s+", t) if x.strip()]
    if len(parts) < 2:
        return None

    def _one(seg: str) -> Optional[tuple[float, str]]:
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*°?\s*([NSEW])?", seg.strip(), flags=re.I)
        if not m:
            return None
        try:
            v = float(m.group(1))
        except Exception:
            return None
        d = (m.group(2) or "").upper()
        if d in {"S", "W"} and v > 0:
            v = -v
        return (v, d)

    a = _one(parts[0])
    b = _one(parts[1])
    if not a or not b:
        return None
    av, ad = a
    bv, bd = b
    if ad in {"E", "W"} and bd in {"N", "S"}:
        return (bv, av)
    return (av, bv)


def _extract_inline_coord_pair(text: str) -> Optional[tuple[float, float]]:
    t = str(text or "").replace("−", "-").strip()
    if not t:
        return None
    for pattern in [
        r"(?:坐标|经纬度|大致经纬度)\s*[:：]\s*([0-9NSEWnsew\.\-°\s,，;；]+)",
        r"([0-9]+(?:\.\d+)?\s*°?\s*[NSns]\s*[,，]\s*[0-9]+(?:\.\d+)?\s*°?\s*[EWew])",
        r"([0-9]+(?:\.\d+)?\s*[,，]\s*-?[0-9]+(?:\.\d+)?)",
    ]:
        m = re.search(pattern, t)
        if not m:
            continue
        pair = _parse_lat_lon_pair(m.group(1))
        if pair:
            return pair
    return None


def _parse_coords_table(md: str) -> Dict[str, tuple[float, float]]:
    if not isinstance(md, str):
        return {}
    lines = md.splitlines()
    in_section = False
    table_started = False
    idx_name = None
    idx_lat = None
    idx_lon = None
    idx_coord = None
    coords: Dict[str, tuple[float, float]] = {}

    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_section = "地点坐标" in title
            table_started = False
            idx_name = None
            idx_lat = None
            idx_lon = None
            idx_coord = None
            continue
        if not in_section:
            continue
        if line.strip().startswith("|") and not table_started:
            table_started = True
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            for i, c in enumerate(header):
                if "现称" in c or "地点" in c:
                    idx_name = i
                if ("现代搜索地名" in c) or ("现代行政区" in c) or ("行政区划" in c):
                    if idx_name is None:
                        idx_name = i
                if "纬度" in c or "lat" in c.lower():
                    idx_lat = i
                if "经度" in c or "lon" in c.lower() or "lng" in c.lower():
                    idx_lon = i
                if ("坐标" in c or "经纬度" in c) and idx_coord is None:
                    idx_coord = i
            continue
        if table_started:
            stripped = line.strip()
            if _is_table_separator(stripped):
                continue
            if not stripped.startswith("|"):
                break
            row = [c.strip() for c in stripped.strip("|").split("|")]
            if idx_name is None or idx_name >= len(row):
                continue
            name = _pick_geocode_name(row[idx_name])
            lat = None
            lon = None
            if idx_lat is not None and idx_lon is not None and idx_lat < len(row) and idx_lon < len(row):
                lat = _parse_coord_cell(row[idx_lat])
                lon = _parse_coord_cell(row[idx_lon])
            elif idx_coord is not None and idx_coord < len(row):
                pair = _parse_lat_lon_pair(row[idx_coord])
                if pair:
                    lat, lon = pair
            if (lat is None or lon is None):
                for cell in row:
                    pair = _extract_inline_coord_pair(cell)
                    if pair:
                        lat, lon = pair
                        break
            if lat is None or lon is None:
                continue
            if name:
                coords[name] = (float(lat), float(lon))
    return coords


def _parse_coords_search_map(md: str) -> Dict[str, str]:
    if not isinstance(md, str):
        return {}
    lines = md.splitlines()
    in_section = False
    table_started = False
    idx_name = None
    idx_search = None
    search_map: Dict[str, str] = {}
    for line in lines:
        if line.strip().startswith("## "):
            title = line.strip().lstrip("#").strip()
            in_section = "地点坐标" in title
            table_started = False
            idx_name = None
            idx_search = None
            continue
        if not in_section:
            continue
        if line.strip().startswith("|") and not table_started:
            table_started = True
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            for i, c in enumerate(header):
                if "现称" in c or "地点" in c:
                    idx_name = i
                if ("现代搜索地名" in c) or ("现代行政区" in c) or ("行政区划" in c):
                    idx_search = i
            continue
        if table_started:
            stripped = line.strip()
            if _is_table_separator(stripped):
                continue
            if not stripped.startswith("|"):
                break
            row = [c.strip() for c in stripped.strip("|").split("|")]
            if idx_name is None or idx_search is None or idx_name >= len(row) or idx_search >= len(row):
                continue
            name = _pick_geocode_name(row[idx_name])
            search = _pick_geocode_name(row[idx_search])
            if name and search:
                search_map[name] = search
    return search_map


def _normalize_markdown_tables(md: str) -> str:
    if not isinstance(md, str):
        return md
    lines = md.splitlines()
    out: List[str] = []
    current_h2 = ""
    timeline_fixed = False
    coords_fixed = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("## "):
            current_h2 = stripped.lstrip("#").strip()
            out.append(line)
            i += 1
            continue
        if stripped.startswith("|"):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            is_timeline_section = ("生平时间线" in current_h2) or current_h2.startswith("年份")
            is_coords_section = "地点坐标" in current_h2
            if is_timeline_section and not timeline_fixed:
                has_year = any("年份" in c for c in header_cells)
                has_event = any("事件" in c for c in header_cells)
                if has_year and has_event:
                    out.append(line)
                    if i + 1 < n:
                        next_stripped = lines[i + 1].strip()
                        if not _is_table_separator(next_stripped) and next_stripped.startswith("|"):
                            out.append("| " + " | ".join("---" for _ in header_cells) + " |")
                    else:
                        out.append("| " + " | ".join("---" for _ in header_cells) + " |")
                    timeline_fixed = True
                    i += 1
                    continue
            if is_coords_section and not coords_fixed:
                has_name = any(("现称" in c) or ("地点" in c) for c in header_cells)
                has_lat = any(("纬度" in c) or ("lat" in c.lower()) for c in header_cells)
                has_lon = any(("经度" in c) or ("lon" in c.lower()) or ("lng" in c.lower()) for c in header_cells)
                if has_name and has_lat and has_lon:
                    out.append(line)
                    if i + 1 < n:
                        next_stripped = lines[i + 1].strip()
                        if not _is_table_separator(next_stripped) and next_stripped.startswith("|"):
                            out.append("| " + " | ".join("---" for _ in header_cells) + " |")
                    else:
                        out.append("| " + " | ".join("---" for _ in header_cells) + " |")
                    coords_fixed = True
                    i += 1
                    continue
        out.append(line)
        i += 1
    return "\n".join(out)


def parse_places(md: str) -> List[Dict[str, str]]:
    if not isinstance(md, str):
        return []
    header, rows = _parse_timeline_table(md)
    if not header or not rows:
        return []
    idx_ancient = None
    idx_modern = None
    for i, c in enumerate(header):
        if "古称" in c:
            idx_ancient = i
        if "现称" in c:
            idx_modern = i
    if idx_ancient is None and idx_modern is None:
        return []
    res: List[Dict[str, str]] = []
    for row in rows:
        a = row[idx_ancient] if idx_ancient is not None and idx_ancient < len(row) else ""
        b = row[idx_modern] if idx_modern is not None and idx_modern < len(row) else ""
        if "：" in a:
            a = a.split("：", 1)[-1].strip()
        if "：" in b:
            b = b.split("：", 1)[-1].strip()
        a = re.sub(r"[（）()].*?[）)]", "", a).strip()
        b = re.sub(r"[（）()].*?[）)]", "", b).strip()
        if a or b:
            res.append({"ancient": a, "modern": b})
    return res


def parse_events(md: str) -> List[Dict[str, str]]:
    if not isinstance(md, str):
        return []
    header, rows = _parse_timeline_table(md)
    if not header or not rows:
        return []
    idx_era = None
    idx_ad = None
    idx_desc = None
    for i, c in enumerate(header):
        if "年号" in c:
            idx_era = i
        if "公元" in c:
            idx_ad = i
        if "事件" in c:
            idx_desc = i
    if idx_era is None and idx_ad is None and idx_desc is None:
        return []
    res: List[Dict[str, str]] = []
    for row in rows:
        era = row[idx_era] if idx_era is not None and idx_era < len(row) else ""
        ad = row[idx_ad] if idx_ad is not None and idx_ad < len(row) else ""
        desc = row[idx_desc] if idx_desc is not None and idx_desc < len(row) else ""
        if era or ad or desc:
            res.append({"era": era, "ad": ad, "desc": desc})
    return res


def parse_story_document(md: str) -> ParsedStoryDocument:
    normalized = _normalize_markdown_tables(md)
    basic_info_map = _parse_basic_info(normalized)
    basic_info = BasicInfo(
        name=basic_info_map.get("姓名", ""),
        dynasty=(basic_info_map.get("时代", "") or basic_info_map.get("朝代", "")).strip(),
        birth_text=basic_info_map.get("出生", ""),
        death_text=basic_info_map.get("去世", ""),
        lifespan=basic_info_map.get("享年", ""),
        identity=basic_info_map.get("主要身份", ""),
        status=basic_info_map.get("历史地位", ""),
        achievements=basic_info_map.get("主要成就", ""),
        raw=dict(basic_info_map),
    )
    timeline_header, timeline_rows = _parse_timeline_table(normalized)
    textbook_points = _parse_textbook_points(normalized)
    exam_points = _parse_exam_points(normalized)
    if not exam_points and textbook_points:
        exam_points = _derive_exam_points_from_textbook_points(textbook_points)
    locations = [
        LocationEntry(
            name=item.get("name", ""),
            location_text=item.get("location", ""),
            location_type=item.get("type", "normal"),
            time=item.get("time", ""),
            event=item.get("event", ""),
            significance=item.get("significance", ""),
            duration=item.get("duration", ""),
            quotes=item.get("quotes", ""),
        )
        for item in _parse_location_sections(normalized)
    ]
    return ParsedStoryDocument(
        raw_markdown=md if isinstance(md, str) else "",
        normalized_markdown=normalized,
        basic_info_map=basic_info_map,
        basic_info=basic_info,
        overview=_parse_overview(normalized),
        timeline_header=timeline_header,
        timeline_rows=timeline_rows,
        places=parse_places(normalized),
        events=parse_events(normalized),
        location_sections=locations,
        coords_table=_parse_coords_table(normalized),
        coords_search_map=_parse_coords_search_map(normalized),
        textbook_points=textbook_points,
        exam_points=exam_points,
        historical_reviews=_parse_historical_reviews(normalized),
    )


__all__ = [
    "_extract_inline_coord_pair",
    "_derive_exam_points_from_textbook_points",
    "_is_table_separator",
    "_normalize_markdown_tables",
    "_parse_basic_info",
    "_parse_coord_cell",
    "_parse_lat_lon_pair",
    "_parse_coords_search_map",
    "_parse_coords_table",
    "_parse_date_location",
    "_parse_exam_points",
    "_parse_historical_reviews",
    "_parse_location_sections",
    "_fuzzy_coord_lookup",
    "_lookup_coords_from_historical_index",
    "_normalize_place_key",
    "_parse_overview",
    "_parse_textbook_points",
    "_parse_timeline_table",
    "_pick_geocode_name",
    "_split_ancient_modern",
    "parse_events",
    "parse_places",
    "parse_story_document",
]

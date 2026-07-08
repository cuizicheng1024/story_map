from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from storymap.script.core import parsers as parser_utils
from storymap.script.core.project_paths import is_valid_person_name, person_name_from_filename, story_person_names
from tools.build.homepage.config import ROLE_BAND_LABELS, ROLE_BAND_SPECS
from tools.build.homepage.normalizers import _gcj02_to_wgs84

@dataclass
class HtmlEntry:
    person: str
    file: str
    mtime: float


def _html_birth_has_coords(html_path: Path) -> bool:
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    m = re.search(r"\"birth\"\\s*:\\s*\\{([\\s\\S]*?)\\}\\s*,\\s*\"death\"", text)
    if not m:
        m = re.search(r"\"birth\"\\s*:\\s*\\{([\\s\\S]*?)\\}", text)
    if not m:
        return False
    body = m.group(1)
    return bool(re.search(r"\"lat\"\\s*:\\s*-?\\d+(?:\\.\\d+)?", body) and re.search(r"\"lng\"\\s*:\\s*-?\\d+(?:\\.\\d+)?", body))


def _scan_latest_html(story_map_dir: Path) -> Dict[str, HtmlEntry]:
    latest: Dict[str, HtmlEntry] = {}
    for p in story_map_dir.glob("*.html"):
        if not p.is_file():
            continue
        person = person_name_from_filename(p.name).strip()
        if not is_valid_person_name(person):
            continue
        e = HtmlEntry(person=person, file=p.name, mtime=p.stat().st_mtime)
        cur = latest.get(person)
        if cur is None:
            latest[person] = e
            continue
        cur_has = _html_birth_has_coords(story_map_dir / cur.file)
        e_has = _html_birth_has_coords(p)
        if e_has and not cur_has:
            latest[person] = e
            continue
        canonical_name = f"{person}.html"
        if e_has == cur_has:
            cur_is_canonical = cur.file == canonical_name
            e_is_canonical = e.file == canonical_name
            if e_is_canonical and not cur_is_canonical:
                latest[person] = e
                continue
        if e_has == cur_has and e.mtime > cur.mtime:
            latest[person] = e
    return latest


def _extract_birth_from_story_map_html(html_path: Path) -> Tuple[Optional[float], Optional[float], str, str]:
    try:
        text = html_path.read_text(encoding="utf-8")
    except Exception:
        return None, None, "", ""
    m = re.search(r"const data\s*=\s*(\{[\s\S]*?\})\s*;\s*window\.__EXPORT_DATA__", text)
    if not m:
        return None, None, "", ""
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None, None, "", ""
    person = data.get("person") if isinstance(data, dict) else None
    if not isinstance(person, dict):
        return None, None, "", ""
    dynasty = str(person.get("dynasty") or "").strip()
    birthplace = str(person.get("birthplace") or "").strip()
    birth = person.get("birth")
    if not isinstance(birth, dict):
        return None, None, birthplace, dynasty
    lat = birth.get("lat")
    lng = birth.get("lng")
    try:
        lat_f = float(lat) if lat is not None else None
    except Exception:
        lat_f = None
    try:
        lng_f = float(lng) if lng is not None else None
    except Exception:
        lng_f = None
    return lat_f, lng_f, birthplace, dynasty


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_people_from_story_md(story_md_dir: Path) -> List[str]:
    return story_person_names(story_md_dir)


def _extract_years_from_md(md_text: str) -> Tuple[Optional[int], Optional[int]]:
    text = md_text

    def parse_years(s: str) -> List[int]:
        out: List[int] = []
        src = str(s or "")
        for m in re.finditer(r"(?<!\d)(-?\d{1,4})(?!\d)", src):
            try:
                y = int(m.group(1))
            except Exception:
                continue
            if y < 0:
                out.append(y)
                continue
            suffix = src[m.end() : min(len(src), m.end() + 4)]
            if suffix.startswith("世纪"):
                continue
            if suffix and suffix[0] in ("月", "日", "号"):
                continue
            prefix = src[max(0, m.start() - 8) : m.start()]
            p = prefix.strip()
            if "公元前" in prefix or p.endswith("前") or "BC" in prefix.upper():
                y = -y
            out.append(y)
        return out

    def pick_year(s: str) -> Optional[int]:
        ys = parse_years(s)
        if not ys:
            return None
        return ys[0]

    def pick_two_years(s: str) -> Tuple[Optional[int], Optional[int]]:
        ys = parse_years(s)
        if len(ys) < 2:
            return None, None
        return ys[0], ys[1]

    m = re.search(r"\*\*生卒年\*\*[:：]\s*([^\n]+)", text)
    if not m:
        m = re.search(r"(?:生卒年|生卒)[:：]\s*([^\n]+)", text)
    if m:
        b, d = pick_two_years(m.group(1))
        if b is not None or d is not None:
            return b, d

    birth = None
    death = None
    mb = re.search(r"\*\*出生\*\*[:：]\s*([^\n]+)", text)
    if not mb:
        mb = re.search(r"(?:出生)[:：]\s*([^\n]+)", text)
    if mb:
        birth = pick_year(mb.group(1))

    md = re.search(r"\*\*(去世|逝世)\*\*[:：]\s*([^\n]+)", text)
    if not md:
        md = re.search(r"(去世|逝世)[:：]\s*([^\n]+)", text)
    if md:
        death = pick_year(md.group(2))

    if birth is None and death is None:
        head = text[:420]
        ys: List[int] = []
        for m in re.finditer(r"(公元前|公元|前)\s*(\d{1,4})\s*年", head):
            try:
                y = int(m.group(2))
            except Exception:
                continue
            prefix = m.group(1) or ""
            if prefix in ("公元前", "前"):
                y = -y
            ys.append(y)
        if len(ys) >= 2:
            return ys[0], ys[1]
        if len(ys) == 1:
            return ys[0], None

    if birth is not None and death is not None:
        try:
            if birth > death and birth > 1000 and death > 0 and death < 400:
                death = None
        except Exception:
            pass

    return birth, death


def _extract_birthplace_from_md(md_text: str) -> Tuple[str, str, str]:
    if not isinstance(md_text, str) or not md_text.strip():
        return "", "", ""
    m = re.search(r"\*\*出生\*\*[:：]\s*([^\n]+)", md_text)
    if not m:
        m = re.search(r"(?:出生)[:：]\s*([^\n]+)", md_text)
    if not m:
        head = md_text[:320]
        mm = re.search(r"([^\s，,。]{2,18})人", head)
        if mm:
            cand = mm.group(1).strip()
            allow = [
                "北京",
                "天津",
                "上海",
                "重庆",
                "河北",
                "河南",
                "山东",
                "山西",
                "陕西",
                "江苏",
                "浙江",
                "安徽",
                "江西",
                "福建",
                "广东",
                "广西",
                "湖南",
                "湖北",
                "四川",
                "云南",
                "贵州",
                "甘肃",
                "青海",
                "辽宁",
                "吉林",
                "黑龙江",
                "内蒙古",
                "宁夏",
                "新疆",
                "西藏",
                "海南",
                "香港",
                "澳门",
            ]
            if any(x in cand for x in allow) or re.search(r"(省|市|县|州|郡|国|府|区|镇|乡|村)$", cand):
                return cand, cand, ""
        return "", "", ""
    text = m.group(1).strip()
    if not re.search(r"(一说|或说|又说|另说)", text):
        text = re.sub(
            r"[（(][^）)]*(存疑|不详|未详|未知|无法确认|生年不详|卒年不详)[^）)]*[）)]\s*$",
            "",
            text,
        ).strip()
    text = _strip_birthplace_date_ambiguity_text(text)
    text = re.sub(
        r"^\s*(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?\s*[?？]?\s*[，,]?\s*",
        "",
        text,
    ).strip()
    text = re.sub(
        r"^\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?\s*[?？]?\s*[，,]?\s*",
        "",
        text,
    ).strip()
    text = re.sub(r"^\s*\d{1,2}\s*(?:日|号)\s*[?？]?\s*[，,]?\s*", "", text).strip()
    text = re.sub(r"^\s*(?:约|大约|约于)?\s*\d{1,2}\s*世纪(?:初|中|末)?\s*[，,]?\s*", "", text).strip()
    if parser_utils._location_text_is_native_place_only(parser_utils._strip_common_birthplace_prefixes(text)):
        return "", "", ""
    if not text:
        return "", "", ""
    if re.fullmatch(
        r"(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?\s*",
        text,
    ):
        return "", "", ""
    if re.fullmatch(r"\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?\s*", text):
        return "", "", ""
    parts = [p.strip() for p in re.split(r"[，,]", text) if p.strip()]
    bad = re.compile(r"(存疑|不详|未详|未知|无法确认|生年不详|卒年不详|一说|或说|又说|另说|另有|说法|年说)")
    loc = ""
    for p in parts:
        if not p or bad.search(p):
            continue
        if _looks_like_date_or_period_text(p):
            continue
        if re.search(r"(年间|时期|时代|初年|末年|前期|中期|后期)$", p) and not re.search(
            r"(省|市|县|州|郡|国|府|区|镇|乡|村|岛|湾|山|河|湖|海)",
            p,
        ):
            continue
        loc = p
        break
    if not loc:
        loc = parts[0] if parts else text
    loc = parser_utils._strip_native_place_annotations(loc.strip())
    loc = re.sub(r"^\s*(?:出生于|出生在|生于|生在|于|在)\s*", "", loc).strip()
    if (loc.startswith("（") and loc.endswith("）")) or (loc.startswith("(") and loc.endswith(")")):
        loc = loc[1:-1].strip()
    if not loc:
        return "", "", ""
    bad_kw = re.compile(r"(小说|虚构|未明确|具体年份|年份|生年|卒年|出生年|出生年份|年号)")
    if bad_kw.search(loc):
        return "", "", ""
    if re.search(r"(公元前|公元)\s*\d{1,4}", loc):
        return "", "", ""
    if re.search(r"\d{2,4}\s*年", loc):
        return "", "", ""
    if re.search(r"[一二三四五六七八九十]{1,4}年", loc) and not re.search(r"(省|市|县|州|郡|国|府|区|镇|乡|村|岛|湾|山|河|湖|海)", loc):
        return "", "", ""
    ancient = loc
    modern = ""
    if "（" in loc and "）" in loc:
        left, right = loc.split("（", 1)
        ancient = left.strip()
        modern = right.split("）", 1)[0].strip()
    elif "(" in loc and ")" in loc:
        left, right = loc.split("(", 1)
        ancient = left.strip()
        modern = right.split(")", 1)[0].strip()
    modern = re.sub(r"^今", "", modern).strip()
    loc = re.sub(r"[（）()]+", "", loc).strip()
    ancient = re.sub(r"[（）()]+", "", ancient).strip()
    modern = re.sub(r"[（）()]+", "", modern).strip()
    loc = _strip_birthplace_date_ambiguity_text(loc)
    ancient = _strip_birthplace_date_ambiguity_text(ancient)
    modern = _strip_birthplace_date_ambiguity_text(modern)
    if _birthplace_has_multiple_place_options(loc):
        modern = ""
    return loc, ancient, modern


def _extract_basic_place_from_md(md_text: str, labels: Tuple[str, ...]) -> Tuple[str, str, str]:
    if not isinstance(md_text, str) or not md_text.strip():
        return "", "", ""
    match = None
    for label in labels:
        match = re.search(rf"\*\*{re.escape(label)}\*\*[:：]\s*([^\n]+)", md_text)
        if match:
            break
    raw = str(match.group(1) or "").strip() if match else ""
    if not raw:
        raw = parser_utils.extract_native_place_from_story_text(md_text)
    if not raw:
        return "", "", ""
    ancient = raw
    modern = ""
    bracket_match = re.match(r"^(.*?)[（(]([^）)]+)[）)]\s*$", raw)
    if bracket_match:
        ancient = str(bracket_match.group(1) or "").strip()
        modern = str(bracket_match.group(2) or "").strip()
    modern = re.sub(r"^今", "", modern).strip()
    raw = re.sub(r"[（）()]+", "", raw).strip()
    ancient = re.sub(r"[（）()]+", "", ancient).strip()
    modern = re.sub(r"[（）()]+", "", modern).strip()
    return raw, ancient, modern


def _looks_like_date_or_period_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"^\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?$", value):
        return True
    if re.search(
        r"^(?:约|大约|约于)?\s*(公元前|公元|前)?\s*\d{1,4}(?:/\d{1,4})?\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*(?:日|号))?)?$",
        value,
    ):
        return True
    if re.search(r"^(?:约|大约|约于)?\s*\d{1,2}\s*世纪(?:初|中|末)?$", value):
        return True
    return False


def _strip_parenthetical_place_text(text: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", str(text or "")).strip()


def _strip_common_birthplace_prefixes(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^今\s*", "", cleaned).strip()
    cleaned = re.sub(r"^(?:出生于|出生在|生于|生在|于|在)\s*", "", cleaned).strip()
    return cleaned


def _strip_birthplace_date_ambiguity_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"[（(][^（）()]*?(?:出生时辰|出生(?:具体)?日期|具体出生日期|一说生于\s*\d{3,4}\s*年)[^（）()]*?[）)]",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(
        r"(?:[，,]\s*)?(?:具体出生日期待考|出生具体日期说法不一|出生时辰有说法不一|一说生于\s*\d{3,4}\s*年)\s*$",
        "",
        cleaned,
    ).strip()
    return cleaned


def _birthplace_text_is_ambiguous(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"(存疑|不详|未详|未知|无法确认|待考|待查证|说法不一|一说|或说|又说|另说|另有)", value):
        return True
    if re.search(r"(有[^，。；]*或[^，。；]*(?:等|等说)?)", value):
        return True
    return False


def _birthplace_has_multiple_place_options(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"(有[^，。；]*或[^，。；]*(?:地|处|城|岛|州|郡|县|市|国|等)?)", value):
        return True
    if "或" not in value:
        return False
    return bool(re.search(r"(今[^，。；]*或)|(或[^，。；]*今)", value))


def _birthplace_source_values(birthplace_modern: str, birthplace_ancient: str, birthplace_raw: str) -> List[str]:
    if _birthplace_has_multiple_place_options(birthplace_raw):
        return []
    out: List[str] = []
    for value in (birthplace_modern, birthplace_ancient, birthplace_raw):
        text = str(value or "").strip()
        if not text or _birthplace_text_is_ambiguous(text):
            continue
        out.append(text)
    return out


def _birthplace_lookup_terms(birthplace_modern: str, birthplace_ancient: str, birthplace_raw: str) -> List[str]:
    terms: List[str] = []
    seen = set()
    for value in _birthplace_source_values(birthplace_modern, birthplace_ancient, birthplace_raw):
        cleaned = _strip_common_birthplace_prefixes(value)
        variants = [cleaned, _strip_parenthetical_place_text(cleaned)]
        for variant in variants:
            term = str(variant or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _extract_relations(md_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    text = md_text
    kw_norm = {
        "父": "父亲",
        "父亲": "父亲",
        "母": "母亲",
        "母亲": "母亲",
        "祖父": "祖父",
        "祖母": "祖母",
        "兄": "兄长",
        "兄长": "兄长",
        "弟": "弟弟",
        "弟弟": "弟弟",
        "姐": "姐姐",
        "姐姐": "姐姐",
        "妹": "妹妹",
        "妹妹": "妹妹",
        "子": "子女",
        "儿子": "子女",
        "女儿": "子女",
        "配偶": "配偶",
        "妻子": "配偶",
        "丈夫": "配偶",
        "师从": "师承",
        "师事": "师承",
        "老师": "师承",
        "导师": "师承",
        "友人": "亲友",
        "好友": "亲友",
        "朋友": "亲友",
        "同僚": "同僚",
        "同事": "同僚",
        "盟友": "盟友",
        "对手": "对手",
        "政敌": "政敌",
        "敌人": "政敌",
    }
    patterns: List[Tuple[str, str, int]] = [
        ("父亲", r"(父亲|父)[：:][^\S\n]*([^\n]+)", 2),
        ("母亲", r"(母亲|母)[：:][^\S\n]*([^\n]+)", 2),
        ("祖父", r"(祖父)[：:][^\S\n]*([^\n]+)", 2),
        ("祖母", r"(祖母)[：:][^\S\n]*([^\n]+)", 2),
        ("兄长", r"(兄长|兄)[：:][^\S\n]*([^\n]+)", 2),
        ("弟弟", r"(弟弟|弟)[：:][^\S\n]*([^\n]+)", 2),
        ("姐姐", r"(姐姐|姐)[：:][^\S\n]*([^\n]+)", 2),
        ("妹妹", r"(妹妹|妹)[：:][^\S\n]*([^\n]+)", 2),
        ("子女", r"(子|儿子|女儿)[：:][^\S\n]*([^\n]+)", 2),
        ("配偶", r"(配偶|妻子|丈夫)[：:][^\S\n]*([^\n]+)", 2),
        ("师承", r"(师从|师事|老师|导师)[：:][^\S\n]*([^\n]+)", 2),
        ("亲友", r"(友人|好友|朋友)[：:][^\S\n]*([^\n]+)", 2),
        ("同僚", r"(同僚|同事|盟友|对手|政敌|敌人)[：:][^\S\n]*([^\n]+)", 2),
        ("并称", r"与([^\n，。,。;；]{2,10})并称", 1),
        ("会面", r"与([^\n，。,。;；]{2,10})相会", 1),
        ("交友", r"结交([^\n，。,。;；]{2,10})", 1),
        ("问道", r"问道于([^\n，。,。;；]{2,10})", 1),
        ("问学", r"问学于([^\n，。,。;；]{2,10})", 1),
    ]
    out_meta: List[Dict[str, str]] = []
    seen_name = set()
    for default_label, pat, group_idx in patterns:
        for m in re.finditer(pat, text):
            label = default_label
            if group_idx == 2:
                kw = str(m.group(1) or "").strip()
                if kw:
                    label = kw_norm.get(kw, label)
            s = str(m.group(group_idx) or "").strip()
            if not s:
                continue
            s = re.sub(r"[，。；;].*$", "", s).strip()
            parts = re.split(r"[、,，/｜|]", s)
            for p in parts:
                n = re.sub(r"[\s\(\)（）\[\]【】《》<>\"“”‘’·•]+", "", p).strip()
                if not (1 < len(n) <= 10):
                    continue
                if n in seen_name:
                    continue
                seen_name.add(n)
                out_meta.append({"name": n, "label": label})
    names = [x["name"] for x in out_meta if isinstance(x, dict) and x.get("name")]
    return names[:8], out_meta[:12]


def _pick_markdown_field(md_text: str, field: str) -> str:
    text = md_text

    m = re.search(rf"\*\*{re.escape(field)}\*\*\s*[:：]\s*([^\n]+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(rf"^-\s*\*\*{re.escape(field)}\*\*\s*[:：]\s*([^\n]+)", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def _extract_disambiguation(md_text: str) -> Tuple[List[str], str, List[str]]:
    aliases: List[str] = []
    foreign = ""
    domains: List[str] = []

    alias_raw = [
        _pick_markdown_field(md_text, "别名"),
        _pick_markdown_field(md_text, "别名/称号"),
        _pick_markdown_field(md_text, "别名/字"),
        _pick_markdown_field(md_text, "又名"),
        _pick_markdown_field(md_text, "原名"),
        _pick_markdown_field(md_text, "号"),
    ]
    for a in [x for x in alias_raw if x]:
        parts = [p.strip() for p in re.split(r"[、,，/｜|；;]", a) if p.strip()]
        for p in parts:
            x = re.sub(r"^(原名|别名|别名/称号|别名/字|又名|号|字|笔名|曾用名|化名|小字|学名|谱名)[:：]?", "", p).strip()
            x = re.sub(r"[\[\]（）()“”\"'‘’\s·•]+", "", x).strip()
            if 1 < len(x) <= 16 and x not in aliases:
                aliases.append(x)
    foreign = (
        _pick_markdown_field(md_text, "外文名")
        or _pick_markdown_field(md_text, "英文名")
        or _pick_markdown_field(md_text, "原文名")
        or _pick_markdown_field(md_text, "外文名称")
        or ""
    )
    foreign = foreign.strip().strip("“”\"'‘’")
    d = (
        _pick_markdown_field(md_text, "领域标签")
        or _pick_markdown_field(md_text, "领域")
        or _pick_markdown_field(md_text, "学科")
        or _pick_markdown_field(md_text, "职业标签")
        or ""
    )
    if d:
        parts = [p.strip() for p in re.split(r"[、,，/｜|；;]", d) if p.strip()]
        for p in parts:
            x = re.sub(r"[\[\]（）()“”\"'‘’\s·•]+", "", p).strip()
            if 1 < len(x) <= 18 and x not in domains:
                domains.append(x)
    return aliases[:6], (foreign or ""), domains[:6]


def _split_role_parts(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts: List[str] = []
    for item in re.split(r"[、,，/｜|；;]", text):
        cleaned = str(item).strip()
        cleaned = re.sub(r"^(主要身份|身份|职业|职业标签|身份标签|领域标签|领域|学科)\s*[:：]?", "", cleaned).strip()
        cleaned = re.sub(r"[（(].*?[)）]", "", cleaned).strip()
        cleaned = re.sub(r"\s+", "", cleaned)
        if 1 < len(cleaned) <= 24 and cleaned not in parts:
            parts.append(cleaned)
    return parts


def _match_role_band(part: str) -> Optional[Tuple[str, str, str]]:
    value = str(part or "").strip()
    if not value:
        return None
    for band_key, band_label, keywords in ROLE_BAND_SPECS:
        for keyword in keywords:
            if keyword in value or value in keyword:
                return band_key, band_label, keyword
    return None


def _resolve_main_role_band(
    *,
    md_text: str,
    domain_tags: List[str],
    review: str,
    quote: str,
) -> Tuple[str, str]:
    explicit_parts: List[str] = []
    for field in ("主要身份", "身份", "职业", "身份标签", "职业标签", "领域标签", "领域", "学科"):
        explicit_parts.extend(_split_role_parts(_pick_markdown_field(md_text, field)))
    for item in domain_tags:
        explicit_parts.extend(_split_role_parts(item))
    seen: set[str] = set()
    for part in explicit_parts:
        if part in seen:
            continue
        seen.add(part)
        matched = _match_role_band(part)
        if matched:
            return matched[0], part

    fallback_text = " ".join([str(review or ""), str(quote or ""), str(md_text[:800] or "")]).strip()
    if fallback_text:
        best_score = 0
        best_band = "other"
        best_label = ROLE_BAND_LABELS["other"]
        for band_key, band_label, keywords in ROLE_BAND_SPECS:
            score = 0
            for keyword in keywords:
                score += fallback_text.count(keyword)
            if score > best_score:
                best_score = score
                best_band = band_key
                best_label = band_label
        if best_score > 0:
            return best_band, best_label
    return "other", ROLE_BAND_LABELS["other"]


def _dynasty_hint_from_md(md_text: str) -> str:
    m = re.search(r"\*\*时代\*\*[:：]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"时代[：:]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\*\*朝代\*\*[:：]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"朝代[：:]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip()
    return ""


def _dynasty_mid_year(dynasty: str) -> Optional[int]:
    d = str(dynasty or "").strip()
    if not d:
        return None
    t = re.sub(r"\s+", "", d)

    ranges: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋", (-770, -476)),
        ("战国", (-475, -221)),
        ("春秋战国", (-770, -221)),
        ("先秦", (-800, -221)),
        ("秦", (-221, -206)),
        ("西汉", (-206, 8)),
        ("东汉", (25, 220)),
        ("汉", (-206, 220)),
        ("三国", (220, 280)),
        ("魏晋南北朝", (220, 589)),
        ("魏晋", (220, 420)),
        ("南北朝", (420, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("五代", (907, 960)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1911)),
        ("近代", (1840, 1911)),
        ("民国", (1912, 1949)),
        ("现代", (1949, 2000)),
        ("当代", (1949, 2000)),
    ]

    for key, (a, b) in ranges:
        if key and (key in t):
            return int(round((a + b) / 2))
    return None


def _pick_main_dynasty_by_years(birth_year: Optional[int], death_year: Optional[int]) -> str:
    by = birth_year if isinstance(birth_year, int) else None
    dy = death_year if isinstance(death_year, int) else None
    if by is None and dy is None:
        return ""
    if by is None:
        by = dy
    if dy is None:
        dy = by
    if by is None or dy is None:
        return ""
    a = min(by, dy)
    b = max(by, dy)
    if a == b:
        b = a + 1
    bands: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋战国", (-800, -221)),
        ("秦", (-221, -206)),
        ("汉", (-206, 220)),
        ("魏晋南北", (220, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1840)),
        ("近代", (1840, 1911)),
        ("现代", (1911, 2000)),
    ]
    best = ""
    best_ol = 0
    for name, (x, y) in bands:
        ol = max(0, min(b, y) - max(a, x))
        if ol > best_ol:
            best_ol = ol
            best = name
    return best


def _normalize_dynasty_label(*, person: str, dynasty_raw: str, birth_year: Optional[int], death_year: Optional[int]) -> str:
    s = str(dynasty_raw or "").strip()
    if s:
        return s
    overrides = {
        "李渊": "唐",
        "李世民": "唐",
        "唐太宗": "唐",
        "朱元璋": "明",
        "明太祖": "明",
    }
    if person in overrides:
        return overrides[person]
    return _pick_main_dynasty_by_years(birth_year, death_year) or ""


def _dynasty_range_from_label(dynasty: str) -> Optional[Tuple[int, int]]:
    d = str(dynasty or "").strip()
    if not d:
        return None
    t = re.sub(r"\s+", "", d)
    ranges: List[Tuple[str, Tuple[int, int]]] = [
        ("春秋战国", (-800, -221)),
        ("先秦", (-800, -221)),
        ("秦", (-221, -206)),
        ("汉", (-206, 220)),
        ("魏晋南北", (220, 589)),
        ("魏晋", (220, 420)),
        ("南北朝", (420, 589)),
        ("隋", (581, 618)),
        ("唐", (618, 907)),
        ("宋", (960, 1279)),
        ("元", (1271, 1368)),
        ("明", (1368, 1644)),
        ("清", (1644, 1911)),
        ("近代", (1840, 1911)),
        ("民国", (1912, 1949)),
        ("现代", (1911, 2000)),
        ("当代", (1911, 2000)),
    ]
    for key, (a, b) in ranges:
        if key and key in t:
            return a, b
    return None


def _pick_quote(spot: Dict[str, Any]) -> str:
    s = str(spot.get("spotlight") or "").strip()
    if s:
        return s
    quotes = spot.get("quotes")
    if isinstance(quotes, list) and quotes:
        q = str(quotes[0] or "").strip()
        if q:
            return q
    intro = str(spot.get("intro") or "").strip()
    if intro:
        return intro
    return ""


def _clean_review_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*[-*•]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
    cleaned = re.sub(r"^(?:人物)?短评\s*[：:]\s*", "", cleaned)
    return cleaned.strip()


def _normalize_home_work_title(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[*_`]+", "", text)
    if text.startswith("《") and text.endswith("》") and len(text) > 2:
        text = text[1:-1]
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_work_titles_from_text(text: str, *, limit: int = 6) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in re.findall(r"《([^》]{1,40})》", str(text or "")):
        title = _normalize_home_work_title(raw)
        if not title or title in seen:
            continue
        seen.add(title)
        out.append(title)
        if len(out) >= limit:
            break
    return out


def _resolve_person_works(spot: object, md_text: str, *, limit: int = 6) -> List[str]:
    if isinstance(spot, dict):
        raw_works = spot.get("works")
        if isinstance(raw_works, list):
            works: List[str] = []
            seen = set()
            for item in raw_works:
                title = _normalize_home_work_title(str(item or ""))
                if not title or title in seen:
                    continue
                seen.add(title)
                works.append(title)
                if len(works) >= limit:
                    return works
            if works:
                return works
    return _extract_work_titles_from_text(md_text, limit=limit)


def _load_work_summary_items(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return {}
    data = _read_json(path)
    items = data.get("items") if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in items.items():
        title = _normalize_home_work_title(str(key or ""))
        if not title or not isinstance(value, dict):
            continue
        item = dict(value)
        item["title"] = _normalize_home_work_title(str(item.get("title") or title))
        out[title] = item
        for alias in item.get("aliases") or []:
            alias_title = _normalize_home_work_title(str(alias or ""))
            if alias_title and alias_title not in out:
                out[alias_title] = item
    return out


def _pick_person_work_summaries(
    titles: List[str],
    work_summary_items: Dict[str, Dict[str, Any]],
    *,
    limit: int = 3,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw_title in titles:
        title = _normalize_home_work_title(raw_title)
        if not title or title in out:
            continue
        item = work_summary_items.get(title)
        if not isinstance(item, dict):
            continue
        out[title] = {
            "title": _normalize_home_work_title(str(item.get("title") or title)) or title,
            "authors": [str(x).strip() for x in item.get("authors") or [] if str(x).strip()],
            "era": str(item.get("era") or "").strip(),
            "genre": str(item.get("genre") or "").strip(),
            "one_liner": str(item.get("one_liner") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "quote": str(item.get("quote") or "").strip(),
            "quotes": [str(x).strip() for x in item.get("quotes") or [] if str(x).strip()],
            "quote_policy": str(item.get("quote_policy") or "").strip(),
        }
        if len(out) >= limit:
            break
    return out


_FOREIGN_PLACE_HINT_RE = re.compile(
    r"(美国|智利|法国|英国|俄罗斯|希腊|乌克兰|西班牙|意大利|德国|日本|韩国|朝鲜|越南|泰国|缅甸|斯里兰卡|印度尼西亚|印度|巴西|阿根廷|墨西哥|古巴|加拿大|澳大利亚|新西兰|南非|埃及|以色列|巴勒斯坦|土耳其|伊朗|伊拉克|叙利亚|阿富汗|巴基斯坦|挪威|瑞典|芬兰|丹麦|冰岛|荷兰|比利时|瑞士|奥地利|葡萄牙|波兰|捷克|匈牙利|罗马尼亚|保加利亚|塞尔维亚|克罗地亚|爱尔兰|苏联|黎巴嫩|哥伦比亚|尼泊尔|乌兹别克斯坦|土库曼斯坦|拉丁美洲|中亚|花拉子模|花剌子模|罗马|雅典|马其顿|佛罗伦萨|伦敦|巴黎|柏林|东京|都柏林|莫斯科)"
)
_DOMESTIC_PLACE_HINT_RE = re.compile(
    r"(中国|中华|北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|西藏|宁夏|新疆|香港|澳门|京师|汴京|临安|长安|洛阳|开封|应天府|顺天府|松江府|苏州府|杭州府|眉州|眉山|黄州|密州|徐州|常州|惠州|儋州|郡|府|州|县|省|市)"
)
_CHINESE_DYNASTY_HINT_RE = re.compile(
    r"(中国|中华|夏|商|周|春秋|战国|秦|汉|三国|魏|蜀汉|吴|晋|南北朝|隋|唐|宋|辽|金|元|明|清|民国|中国近代|中国现代|中国当代|近现代中国|当代中国)"
)
_FOREIGN_DYNASTY_HINT_RE = re.compile(
    r"(美国|智利|法国|英国|俄罗斯|希腊|乌克兰|西班牙|意大利|德国|日本|韩国|朝鲜|越南|泰国|缅甸|斯里兰卡|印度尼西亚|印度|巴西|阿根廷|墨西哥|古巴|加拿大|澳大利亚|新西兰|南非|埃及|以色列|巴勒斯坦|土耳其|伊朗|伊拉克|叙利亚|阿富汗|巴基斯坦|挪威|瑞典|芬兰|丹麦|冰岛|荷兰|比利时|瑞士|奥地利|葡萄牙|波兰|捷克|匈牙利|罗马尼亚|保加利亚|塞尔维亚|克罗地亚|爱尔兰|苏联|黎巴嫩|哥伦比亚|尼泊尔|乌兹别克斯坦|土库曼斯坦|拉丁美洲|中亚|古希腊|古罗马|罗马帝国|拜占庭|奥斯曼|波斯|阿拉伯|伊斯兰|阿拔斯|花拉子模|花剌子模|蒙兀儿|欧洲|欧洲近代|文艺复兴|启蒙|工业革命|维多利亚时代|托勒密王国|神圣罗马帝国|英属印度|法兰西|英格兰|苏格兰|马其顿|美索不达米亚)"
)


def _is_foreign_person(*, foreign_name: str, birthplace_modern: str, birthplace_raw: str, dynasty: str) -> bool:
    dynasty_text = str(dynasty or "").strip()
    dynasty_text = dynasty_text.replace("公元前", "").replace("公元", "")
    has_chinese_dynasty = bool(_CHINESE_DYNASTY_HINT_RE.search(dynasty_text))
    has_foreign_dynasty = bool(_FOREIGN_DYNASTY_HINT_RE.search(dynasty_text))
    if has_chinese_dynasty and not has_foreign_dynasty:
        return False
    if has_foreign_dynasty and not has_chinese_dynasty:
        return True
    place_texts = [str(value or "").strip() for value in (birthplace_modern, birthplace_raw) if str(value or "").strip()]
    for text in place_texts:
        if _FOREIGN_PLACE_HINT_RE.search(text):
            return True
    for text in place_texts:
        if _DOMESTIC_PLACE_HINT_RE.search(text):
            return False
    if has_chinese_dynasty:
        return False
    return bool(str(foreign_name or "").strip())



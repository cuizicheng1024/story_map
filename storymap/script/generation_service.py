from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional

try:
    from . import parsers as parser_utils
except ImportError:
    import parsers as parser_utils


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


def validate_data_quality(md: str) -> List[str]:
    if not isinstance(md, str) or not md.strip():
        return ["内容为空或格式不正确"]
    issues: List[str] = []
    parsed_doc = parser_utils.parse_story_document(md)
    header = parsed_doc.timeline_header
    rows = parsed_doc.timeline_rows
    if not header or not rows:
        issues.append("年份表缺失或为空")
    else:
        if not any("现称" in c for c in header):
            issues.append("年份表缺少现称列")
        if not any("事件" in c for c in header):
            issues.append("年份表缺少事件列")
    locations = [item.to_legacy_dict() for item in parsed_doc.location_sections]
    if not locations:
        issues.append("重要地点段落缺失或为空")
    else:
        missing_event = [item for item in locations if not (item.get("event") or "").strip()]
        if missing_event and len(missing_event) >= max(1, len(locations) // 2):
            issues.append(f"重要地点事迹缺失较多（{len(missing_event)} / {len(locations)}）")
    place_names = []
    for place in parsed_doc.places:
        name = place.get("modern") or place.get("ancient") or ""
        name = parser_utils._pick_geocode_name(name)
        if name:
            place_names.append(name)
    coords = parsed_doc.coords_table
    if place_names and not coords:
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
    return issues


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


def render_html(
    title: str,
    points: List[Dict[str, object]],
    *,
    md: str = "",
    build_profile_data: Callable[[str], Optional[Dict[str, object]]],
    extract_intro_fields: Callable[[str], Dict[str, str]],
    render_profile_html: Callable[[Dict[str, object]], str],
    build_info_panel_html: Callable[[str, Dict[str, str]], str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
) -> str:
    if md and isinstance(md, str):
        profile = build_profile_data(md)
        if profile:
            profile["markdown"] = md
            return render_profile_html(profile)
        fields = extract_intro_fields(md)
        if any(fields.values()):
            info_panel_html = build_info_panel_html(title, fields)
            return render_amap_html(title, points, info_panel_html)
    return render_amap_html(title, points, "")


def generate_for_person(
    client: object,
    person: str,
    *,
    progress: Optional[callable] = None,
    allow_cache: bool = True,
    event_callback: Optional[callable] = None,
    story_paths: Callable[[str], tuple[str, str]],
    read_text: Callable[[str], str],
    extract_export_data_from_html: Callable[[str], Optional[Dict[str, object]]],
    write_text: Callable[[str, str], None],
    render_profile_html: Callable[[Dict[str, object]], str],
    load_profile_from_md: Callable[..., Optional[Dict[str, object]]],
    normalize_markdown_tables: Callable[[str], str],
    compute_total_distance_km: Callable[[str], object],
    insert_distance_intro: Callable[[str, float], str],
    save_markdown: Callable[[str, str], str],
    geocode_markdown_tool: Callable[[str], str],
    parse_story_markdown_tool: Callable[[str], Dict[str, object]],
    validate_story_markdown_tool: Callable[[str], Dict[str, object]],
    render_html_fn: Callable[..., str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
    save_html: Callable[[str, str], str],
    format_seconds: Callable[[float], str],
    get_llm_client: Callable[..., object],
    generate_historical_markdown: Callable[[object, str], str],
    logger: object,
) -> Dict[str, object]:
    md_path, html_path = story_paths(person)
    if allow_cache and os.path.exists(html_path):
        cached_html = read_text(html_path)
        needs_refresh = (
            ("export-bar" in cached_html)
            or ("leaflet" in cached_html)
            or ("/amap-config.js" not in cached_html)
        )
        if (not needs_refresh) and ("window.__EXPORT_DATA__" in cached_html):
            export_data = extract_export_data_from_html(cached_html)
            if export_data and os.path.exists(md_path):
                md = read_text(md_path)
                if md:
                    export_data["markdown"] = md
            return {
                "ok": True,
                "person": person,
                "markdown_path": md_path if os.path.exists(md_path) else "",
                "html_path": html_path,
                "steps": [{"label": "命中缓存", "duration": "0.00s"}],
                "duration": {"total": "0.00s"},
                "_profile": export_data,
                "cached": True,
            }
        md = read_text(md_path) if os.path.exists(md_path) else ""
        export_data = extract_export_data_from_html(cached_html)
        if export_data:
            if md:
                export_data["markdown"] = md
            html = render_profile_html(export_data)
            write_text(html_path, html)
            return {
                "ok": True,
                "person": person,
                "markdown_path": md_path if os.path.exists(md_path) else "",
                "html_path": html_path,
                "steps": [{"label": "刷新缓存", "duration": "0.00s"}],
                "duration": {"total": "0.00s"},
                "_profile": export_data,
                "cached": True,
                "refreshed": True,
            }
        if md:
            profile = load_profile_from_md(md, event_callback=event_callback)
            if profile:
                profile["markdown"] = md
                html = render_profile_html(profile)
                write_text(html_path, html)
                return {
                    "ok": True,
                    "person": person,
                    "markdown_path": md_path,
                    "html_path": html_path,
                    "steps": [{"label": "刷新缓存", "duration": "0.00s"}],
                    "duration": {"total": "0.00s"},
                    "_profile": profile,
                    "cached": True,
                    "refreshed": True,
                }

    if allow_cache and os.path.exists(md_path) and (not os.path.exists(html_path)):
        t0 = time.perf_counter()
        steps = []
        md = read_text(md_path)
        if not md.strip():
            return {"ok": False, "person": person, "error": "Markdown 为空，无法渲染"}
        if progress:
            progress(f"{person} 复用现有 Markdown")
        t_step = time.perf_counter()
        md = normalize_markdown_tables(md)
        t_norm = time.perf_counter() - t_step
        steps.append({"label": "复用Markdown", "duration": format_seconds(t_norm)})
        if progress:
            progress(f"{person} 地理编码")
        t_step = time.perf_counter()
        md_geo = geocode_markdown_tool(md)
        t_geo = time.perf_counter() - t_step
        steps.append({"label": "地理编码", "duration": format_seconds(t_geo)})
        validation = validate_story_markdown_tool(md_geo)
        if progress:
            progress(f"{person} 地图渲染")
        t_step = time.perf_counter()
        render_error = ""
        try:
            parsed = parse_story_markdown_tool(md_geo)
            pts = parsed.get("points") or []
            html = render_html_fn(person, pts, md=md_geo)
        except Exception as exc:
            render_error = str(exc).strip() or "地图渲染失败"
            logger.warning("render_failed person=%s error=%s", person, exc)
            html = render_amap_html(person, [], "")
        t_render = time.perf_counter() - t_step
        steps.append({"label": "地图渲染", "duration": format_seconds(t_render)})
        if progress:
            progress(f"{person} 文件写入")
        t_step = time.perf_counter()
        out = save_html(person, html)
        t_save = time.perf_counter() - t_step
        steps.append({"label": "文件写入", "duration": format_seconds(t_save)})
        total = time.perf_counter() - t0
        profile = load_profile_from_md(md_geo, event_callback=event_callback)
        result = {
            "ok": True,
            "person": person,
            "markdown_path": md_path,
            "html_path": out,
            "steps": steps,
            "duration": {
                "geocode": format_seconds(t_geo),
                "render": format_seconds(t_render),
                "save": format_seconds(t_save),
                "total": format_seconds(total),
            },
            "_profile": profile,
            "_validation": validation,
            "cached": False,
            "used_existing_markdown": True,
        }
        if render_error:
            result["warning"] = render_error
        return result

    t0 = time.perf_counter()
    if progress:
        progress(f"{person} 生成人物档案")
    t_step = time.perf_counter()
    if client is None:
        client = get_llm_client(event_callback=event_callback)
    md = generate_historical_markdown(client, person)
    t_md = time.perf_counter() - t_step
    if not md:
        return {"ok": False, "person": person, "error": "未取得内容"}
    md = normalize_markdown_tables(md)
    km = compute_total_distance_km(md)
    if isinstance(km, float):
        md = insert_distance_intro(md, km)
    if progress:
        progress(f"{person} 解析地点坐标")
    t_step = time.perf_counter()
    md = geocode_markdown_tool(md)
    t_geo = time.perf_counter() - t_step
    validation = validate_story_markdown_tool(md)
    saved = save_markdown(person, md)
    if progress:
        progress(f"{person} 构建时空结果")
    t_step = time.perf_counter()
    render_error = ""
    try:
        parsed = parse_story_markdown_tool(md)
        pts = parsed.get("points") or []
        html = render_html_fn(person, pts, md=md)
    except Exception as exc:
        render_error = str(exc).strip() or "地图渲染失败"
        logger.warning("render_failed person=%s error=%s", person, exc)
        html = render_amap_html(person, [], "")
    t_render = time.perf_counter() - t_step
    if progress:
        progress(f"{person} 保存分析产物")
    t_step = time.perf_counter()
    out = save_html(person, html)
    t_save = time.perf_counter() - t_step
    total = time.perf_counter() - t0
    profile = load_profile_from_md(md, event_callback=event_callback)
    result = {
        "ok": True,
        "person": person,
        "markdown_path": saved,
        "html_path": out,
        "steps": [
            {"label": "生成人物档案", "duration": format_seconds(t_md)},
            {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
            {"label": "构建时空结果", "duration": format_seconds(t_render)},
            {"label": "保存分析产物", "duration": format_seconds(t_save)},
        ],
        "duration": {
            "markdown": format_seconds(t_md),
            "geocode": format_seconds(t_geo),
            "render": format_seconds(t_render),
            "save": format_seconds(t_save),
            "total": format_seconds(total),
        },
        "_profile": profile,
        "_validation": validation,
        "cached": False,
    }
    if render_error:
        result["warning"] = render_error
    return result

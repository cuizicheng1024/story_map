from __future__ import annotations

import os
import re
import time
from typing import Callable, Dict, List, Optional

try:
    from . import parsers as parser_utils
    from .story_agent_runtime import extract_agent_runtime_metadata as _extract_agent_runtime_metadata
    from .story_agent_runtime import normalize_runtime_snapshot as _normalize_runtime_snapshot
except ImportError:
    import parsers as parser_utils
    from story_agent_runtime import extract_agent_runtime_metadata as _extract_agent_runtime_metadata
    from story_agent_runtime import normalize_runtime_snapshot as _normalize_runtime_snapshot


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


def enrich_markdown_for_map(
    md: str,
    *,
    normalize_markdown_tables: Callable[[str], str],
    geocode_markdown: Callable[[str], str],
    compute_total_distance_km: Callable[[str], object],
    insert_distance_intro: Callable[[str, float], str],
) -> str:
    if not isinstance(md, str):
        return ""
    enriched = normalize_markdown_tables(md)
    enriched = geocode_markdown(enriched)
    distance_km = compute_total_distance_km(enriched)
    if isinstance(distance_km, float):
        enriched = insert_distance_intro(enriched, distance_km)
    return enriched


def render_html(
    title: str,
    points: List[Dict[str, object]],
    *,
    md: str = "",
    build_profile_data: Callable[..., Optional[Dict[str, object]]],
    extract_intro_fields: Callable[[str], Dict[str, str]],
    render_profile_html: Callable[[Dict[str, object]], str],
    build_info_panel_html: Callable[[str, Dict[str, str]], str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
) -> str:
    if md and isinstance(md, str):
        profile = build_profile_data(md, fallback_person=title)
        if profile:
            profile["markdown"] = md
            return render_profile_html(profile)
        fields = extract_intro_fields(md)
        if any(fields.values()):
            info_panel_html = build_info_panel_html(title, fields)
            return render_amap_html(title, points, info_panel_html)
    return render_amap_html(title, points, "")


def _coerce_validation_dict(validation: object) -> Dict[str, object]:
    if not isinstance(validation, dict):
        return {}
    return dict(validation)


def _sync_runtime_final_validation(
    agent_runtime: Optional[Dict[str, object]],
    validation: object,
) -> Optional[Dict[str, object]]:
    if not isinstance(agent_runtime, dict) or not agent_runtime:
        return agent_runtime
    runtime = dict(agent_runtime)
    state = dict(runtime.get("state") or {})
    final_validation = _coerce_validation_dict(validation)
    if final_validation:
        state["validation"] = final_validation
        state["validation_stage"] = "final_output"
    runtime["state"] = state
    return runtime


def _build_render_failure_result(
    *,
    person: str,
    render_error: str,
    fallback_html_path: str,
    steps: List[Dict[str, object]],
    duration: Dict[str, str],
    profile: object,
    validation: object,
    markdown_path: str = "",
    agent_runtime: Optional[Dict[str, object]] = None,
    used_existing_markdown: bool = False,
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "ok": False,
        "status": "degraded",
        "degraded": True,
        "person": person,
        "error": str(render_error or "地图渲染失败"),
        "render_error": str(render_error or "地图渲染失败"),
        "fallback_html_path": fallback_html_path,
        "html_path": fallback_html_path,
        "steps": steps,
        "duration": duration,
        "_profile": profile,
        "_validation": validation,
        "cached": False,
        "used_existing_markdown": bool(used_existing_markdown),
        "warning": str(render_error or "地图渲染失败"),
    }
    if markdown_path:
        result["markdown_path"] = markdown_path
    if agent_runtime:
        result["_agent_runtime"] = agent_runtime
    return result


def _validation_issues(validation: object) -> List[str]:
    if not isinstance(validation, dict):
        return []
    return [str(item) for item in list(validation.get("issues") or []) if str(item).strip()]


def _build_quality_degraded_result(
    *,
    person: str,
    html_path: str,
    steps: List[Dict[str, object]],
    duration: Dict[str, str],
    profile: object,
    validation: object,
    markdown_path: str = "",
    cached: bool = False,
    refreshed: bool = False,
    used_existing_markdown: bool = False,
    agent_runtime: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    issues = _validation_issues(validation)
    summary = "；".join(issues[:3]) or "人物页存在待修正的数据质量问题"
    result: Dict[str, object] = {
        "ok": False,
        "status": "degraded",
        "degraded": True,
        "person": person,
        "error": summary,
        "warning": summary,
        "html_path": html_path,
        "steps": steps,
        "duration": duration,
        "_profile": profile,
        "_validation": validation,
        "cached": bool(cached),
        "refreshed": bool(refreshed),
        "used_existing_markdown": bool(used_existing_markdown),
        "quality_issue_summary": summary,
    }
    if markdown_path:
        result["markdown_path"] = markdown_path
    if agent_runtime:
        result["_agent_runtime"] = agent_runtime
    return result


def extract_agent_runtime_metadata(client: object) -> Dict[str, object]:
    return _extract_agent_runtime_metadata(client)


def normalize_runtime_snapshot(client: object) -> Dict[str, object]:
    return _normalize_runtime_snapshot(client)


def _cache_older_than_dependencies(html_path: str, dependency_paths: List[str]) -> bool:
    if not html_path or not os.path.exists(html_path):
        return True
    try:
        html_mtime = os.path.getmtime(html_path)
    except Exception:
        return True
    for path in dependency_paths:
        dep = str(path or "").strip()
        if not dep or not os.path.exists(dep):
            continue
        try:
            if os.path.getmtime(dep) > html_mtime:
                return True
        except Exception:
            continue
    return False


def _extract_html_template_signature(html: str) -> str:
    text = str(html or "")
    if not text:
        return ""
    m = re.search(r'"templateSignature"\s*:\s*"([^"]+)"', text)
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def _is_usable_export_profile(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    person = data.get("person")
    return isinstance(person, dict) and bool(str(person.get("name") or "").strip())


def _write_runtime_map_configs(
    html_path: str,
    *,
    write_text: Callable[[str, str], None],
    build_amap_config_js: Optional[Callable[[], bytes]] = None,
    build_geovis_config_js: Optional[Callable[[], bytes]] = None,
) -> None:
    if not html_path:
        return
    output_dir = os.path.dirname(os.path.abspath(html_path))
    writers = (
        ("amap-config.js", build_amap_config_js),
        ("geovis-config.js", build_geovis_config_js),
    )
    for filename, builder in writers:
        if not callable(builder):
            continue
        content = builder()
        if isinstance(content, bytes):
            text = content.decode("utf-8")
        else:
            text = str(content or "")
        write_text(os.path.join(output_dir, filename), text)


def _try_write_runtime_map_configs(
    html_path: str,
    *,
    write_text: Callable[[str, str], None],
    logger: object,
    build_amap_config_js: Optional[Callable[[], bytes]] = None,
    build_geovis_config_js: Optional[Callable[[], bytes]] = None,
) -> str:
    try:
        _write_runtime_map_configs(
            html_path,
            write_text=write_text,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
        )
        return ""
    except Exception as exc:
        logger.warning("runtime_map_config_write_failed html_path=%s error=%s", html_path, exc)
        return str(exc).strip() or "运行时地图配置写入失败"


def _runtime_map_configs_missing(html_path: str) -> bool:
    if not html_path:
        return True
    output_dir = os.path.dirname(os.path.abspath(html_path))
    return not (
        os.path.exists(os.path.join(output_dir, "amap-config.js"))
        and os.path.exists(os.path.join(output_dir, "geovis-config.js"))
    )


def _build_runtime_config_degraded_result(
    *,
    person: str,
    html_path: str,
    config_error: str,
    steps: List[Dict[str, object]],
    duration: Dict[str, str],
    profile: object,
    validation: object,
    markdown_path: str = "",
    cached: bool = False,
    refreshed: bool = False,
    used_existing_markdown: bool = False,
    agent_runtime: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    quality_issues = _validation_issues(validation)
    summary = f"运行时地图配置写入失败：{str(config_error or '').strip() or '未知错误'}"
    if quality_issues:
        summary = f"{summary}；{'；'.join(quality_issues[:2])}"
    result: Dict[str, object] = {
        "ok": False,
        "status": "degraded",
        "degraded": True,
        "person": person,
        "error": summary,
        "warning": summary,
        "html_path": html_path,
        "steps": steps,
        "duration": duration,
        "_profile": profile,
        "_validation": validation,
        "cached": bool(cached),
        "refreshed": bool(refreshed),
        "used_existing_markdown": bool(used_existing_markdown),
        "runtime_config_failed": True,
        "runtime_config_error": str(config_error or "").strip(),
    }
    if markdown_path:
        result["markdown_path"] = markdown_path
    if quality_issues:
        result["quality_issue_summary"] = "；".join(quality_issues[:3])
    if agent_runtime:
        result["_agent_runtime"] = agent_runtime
    return result


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
    cache_dependency_paths: Optional[List[str]],
    logger: object,
    current_profile_signature: Optional[Callable[[], str]] = None,
    build_amap_config_js: Optional[Callable[[], bytes]] = None,
    build_geovis_config_js: Optional[Callable[[], bytes]] = None,
) -> Dict[str, object]:
    md_path, html_path = story_paths(person)
    if allow_cache and os.path.exists(html_path):
        cached_html = read_text(html_path)
        cache_stale_by_code = _cache_older_than_dependencies(html_path, list(cache_dependency_paths or []))
        cache_stale_by_markdown = False
        cache_stale_by_signature = False
        if os.path.exists(md_path):
            try:
                cache_stale_by_markdown = os.path.getmtime(md_path) > os.path.getmtime(html_path)
            except OSError:
                cache_stale_by_markdown = False
        needs_refresh = (
            ("export-bar" in cached_html)
            or ("leaflet" in cached_html)
            or ("amap-config.js" not in cached_html)
            or ("geovis-config.js" not in cached_html)
            or cache_stale_by_code
            or cache_stale_by_markdown
        )
        if not needs_refresh and callable(current_profile_signature):
            expected_signature = str(current_profile_signature() or "").strip()
            actual_signature = _extract_html_template_signature(cached_html)
            if expected_signature and actual_signature != expected_signature:
                cache_stale_by_signature = True
                needs_refresh = True
        if (not needs_refresh) and ("window.__EXPORT_DATA__" in cached_html):
            export_data = extract_export_data_from_html(cached_html)
            validation = {"metrics": {}, "issues": []}
            if _is_usable_export_profile(export_data) and os.path.exists(md_path):
                md = read_text(md_path)
                if md:
                    export_data["markdown"] = md
                    validation = validate_story_markdown_tool(md)
            if _is_usable_export_profile(export_data):
                config_error = ""
                if _runtime_map_configs_missing(html_path):
                    config_error = _try_write_runtime_map_configs(
                        html_path,
                        write_text=write_text,
                        logger=logger,
                        build_amap_config_js=build_amap_config_js,
                        build_geovis_config_js=build_geovis_config_js,
                    )
                if config_error:
                    return _build_runtime_config_degraded_result(
                        person=person,
                        html_path=html_path,
                        markdown_path=md_path if os.path.exists(md_path) else "",
                        config_error=config_error,
                        steps=[{"label": "命中缓存", "duration": "0.00s"}],
                        duration={"total": "0.00s"},
                        profile=export_data,
                        validation=validation,
                        cached=True,
                    )
                if _validation_issues(validation):
                    return _build_quality_degraded_result(
                        person=person,
                        html_path=html_path,
                        markdown_path=md_path if os.path.exists(md_path) else "",
                        steps=[{"label": "命中缓存", "duration": "0.00s"}],
                        duration={"total": "0.00s"},
                        profile=export_data,
                        validation=validation,
                        cached=True,
                    )
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
        if _is_usable_export_profile(export_data) and (not cache_stale_by_code) and (not cache_stale_by_markdown) and (not cache_stale_by_signature):
            if md:
                export_data["markdown"] = md
            html = render_profile_html(export_data)
            write_text(html_path, html)
            config_error = _try_write_runtime_map_configs(
                html_path,
                write_text=write_text,
                logger=logger,
                build_amap_config_js=build_amap_config_js,
                build_geovis_config_js=build_geovis_config_js,
            )
            validation = validate_story_markdown_tool(md) if md else {"metrics": {}, "issues": []}
            if config_error:
                return _build_runtime_config_degraded_result(
                    person=person,
                    html_path=html_path,
                    markdown_path=md_path if os.path.exists(md_path) else "",
                    config_error=config_error,
                    steps=[{"label": "刷新缓存", "duration": "0.00s"}],
                    duration={"total": "0.00s"},
                    profile=export_data,
                    validation=validation,
                    cached=True,
                    refreshed=True,
                )
            if _validation_issues(validation):
                return _build_quality_degraded_result(
                    person=person,
                    html_path=html_path,
                    markdown_path=md_path if os.path.exists(md_path) else "",
                    steps=[{"label": "刷新缓存", "duration": "0.00s"}],
                    duration={"total": "0.00s"},
                    profile=export_data,
                    validation=validation,
                    cached=True,
                    refreshed=True,
                )
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
            profile = load_profile_from_md(md, event_callback=event_callback, fallback_person=person)
            if profile:
                profile["markdown"] = md
                html = render_profile_html(profile)
                write_text(html_path, html)
                config_error = _try_write_runtime_map_configs(
                    html_path,
                    write_text=write_text,
                    logger=logger,
                    build_amap_config_js=build_amap_config_js,
                    build_geovis_config_js=build_geovis_config_js,
                )
                validation = validate_story_markdown_tool(md)
                if config_error:
                    return _build_runtime_config_degraded_result(
                        person=person,
                        html_path=html_path,
                        markdown_path=md_path,
                        config_error=config_error,
                        steps=[{"label": "刷新缓存", "duration": "0.00s"}],
                        duration={"total": "0.00s"},
                        profile=profile,
                        validation=validation,
                        cached=True,
                        refreshed=True,
                    )
                if _validation_issues(validation):
                    return _build_quality_degraded_result(
                        person=person,
                        html_path=html_path,
                        markdown_path=md_path,
                        steps=[{"label": "刷新缓存", "duration": "0.00s"}],
                        duration={"total": "0.00s"},
                        profile=profile,
                        validation=validation,
                        cached=True,
                        refreshed=True,
                    )
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
        config_error = _try_write_runtime_map_configs(
            out,
            write_text=write_text,
            logger=logger,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
        )
        t_save = time.perf_counter() - t_step
        steps.append({"label": "文件写入", "duration": format_seconds(t_save)})
        total = time.perf_counter() - t0
        profile = load_profile_from_md(md_geo, event_callback=event_callback, fallback_person=person)
        duration = {
            "geocode": format_seconds(t_geo),
            "render": format_seconds(t_render),
            "save": format_seconds(t_save),
            "total": format_seconds(total),
        }
        if render_error:
            return _build_render_failure_result(
                person=person,
                render_error=render_error,
                fallback_html_path=out,
                markdown_path=md_path,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                used_existing_markdown=True,
            )
        if config_error:
            return _build_runtime_config_degraded_result(
                person=person,
                html_path=out,
                markdown_path=md_path,
                config_error=config_error,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                used_existing_markdown=True,
            )
        if _validation_issues(validation):
            return _build_quality_degraded_result(
                person=person,
                html_path=out,
                markdown_path=md_path,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                used_existing_markdown=True,
            )
        result = {
            "ok": True,
            "status": "ok",
            "degraded": False,
            "person": person,
            "markdown_path": md_path,
            "html_path": out,
            "steps": steps,
            "duration": duration,
            "_profile": profile,
            "_validation": validation,
            "cached": False,
            "used_existing_markdown": True,
        }
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
    agent_runtime = normalize_runtime_snapshot(client)
    if progress:
        progress(f"{person} 解析地点坐标")
    t_step = time.perf_counter()
    md = enrich_markdown_for_map(
        md,
        normalize_markdown_tables=normalize_markdown_tables,
        geocode_markdown=geocode_markdown_tool,
        compute_total_distance_km=compute_total_distance_km,
        insert_distance_intro=insert_distance_intro,
    )
    t_geo = time.perf_counter() - t_step
    validation = validate_story_markdown_tool(md)
    agent_runtime = _sync_runtime_final_validation(agent_runtime, validation)
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
    config_error = _try_write_runtime_map_configs(
        out,
        write_text=write_text,
        logger=logger,
        build_amap_config_js=build_amap_config_js,
        build_geovis_config_js=build_geovis_config_js,
    )
    t_save = time.perf_counter() - t_step
    total = time.perf_counter() - t0
    profile = load_profile_from_md(md, event_callback=event_callback, fallback_person=person)
    duration = {
        "markdown": format_seconds(t_md),
        "geocode": format_seconds(t_geo),
        "render": format_seconds(t_render),
        "save": format_seconds(t_save),
        "total": format_seconds(total),
    }
    if render_error:
        return _build_render_failure_result(
            person=person,
            render_error=render_error,
            fallback_html_path=out,
            markdown_path=saved,
            steps=[
                {"label": "生成人物档案", "duration": format_seconds(t_md)},
                {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
                {"label": "构建时空结果", "duration": format_seconds(t_render)},
                {"label": "保存分析产物", "duration": format_seconds(t_save)},
            ],
            duration=duration,
            profile=profile,
            validation=validation,
            agent_runtime=agent_runtime,
        )
    if config_error:
        return _build_runtime_config_degraded_result(
            person=person,
            html_path=out,
            markdown_path=saved,
            config_error=config_error,
            steps=[
                {"label": "生成人物档案", "duration": format_seconds(t_md)},
                {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
                {"label": "构建时空结果", "duration": format_seconds(t_render)},
                {"label": "保存分析产物", "duration": format_seconds(t_save)},
            ],
            duration=duration,
            profile=profile,
            validation=validation,
            agent_runtime=agent_runtime,
        )
    if _validation_issues(validation):
        return _build_quality_degraded_result(
            person=person,
            html_path=out,
            markdown_path=saved,
            steps=[
                {"label": "生成人物档案", "duration": format_seconds(t_md)},
                {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
                {"label": "构建时空结果", "duration": format_seconds(t_render)},
                {"label": "保存分析产物", "duration": format_seconds(t_save)},
            ],
            duration=duration,
            profile=profile,
            validation=validation,
            agent_runtime=agent_runtime,
        )
    result = {
        "ok": True,
        "status": "ok",
        "degraded": False,
        "person": person,
        "markdown_path": saved,
        "html_path": out,
        "steps": [
            {"label": "生成人物档案", "duration": format_seconds(t_md)},
            {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
            {"label": "构建时空结果", "duration": format_seconds(t_render)},
            {"label": "保存分析产物", "duration": format_seconds(t_save)},
        ],
        "duration": duration,
        "_profile": profile,
        "_validation": validation,
        "_agent_runtime": agent_runtime,
        "cached": False,
    }
    return result

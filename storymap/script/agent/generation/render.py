from __future__ import annotations

from typing import Callable, Dict, List, Optional


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
        profile = build_profile_data(md, fallback_person=title, allow_geocode=False)
        if profile:
            profile["markdown"] = md
            return render_profile_html(profile)
        fields = extract_intro_fields(md)
        if any(fields.values()):
            info_panel_html = build_info_panel_html(title, fields)
            return render_amap_html(title, points, info_panel_html)
    return render_amap_html(title, points, "")


def render_story_html(
    *,
    person: str,
    md: str,
    parse_story_markdown_tool: Callable[[str], Dict[str, object]],
    render_html_fn: Callable[..., str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
    logger: object,
) -> tuple[str, str]:
    render_error = ""
    try:
        parsed = parse_story_markdown_tool(md)
        pts = parsed.get("points") or []
        html = render_html_fn(person, pts, md=md)
    except Exception as exc:
        render_error = str(exc).strip() or "地图渲染失败"
        logger.warning("render_failed person=%s error=%s", person, exc)
        html = render_amap_html(person, [], "")
    return html, render_error


def build_profile_from_markdown(
    *,
    md: str,
    person: str,
    event_callback,
    load_profile_from_md: Callable[..., Optional[Dict[str, object]]],
) -> Optional[Dict[str, object]]:
    return load_profile_from_md(
        md,
        event_callback=event_callback,
        fallback_person=person,
        allow_geocode=False,
    )

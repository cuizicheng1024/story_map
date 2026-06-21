from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

try:
    from ..person_registry import canonical_person_name
    from .. import story_generation_tools as story_generation_tools_utils
except ImportError:
    from person_registry import canonical_person_name
    import story_generation_tools as story_generation_tools_utils


@dataclass
class GenerationState:
    person: str
    requested_person: str = ""
    md_draft: str = ""
    quality_issues: List[str] = field(default_factory=list)
    retry_count: int = 0
    profile: Optional[Dict[str, object]] = None
    html_path: str = ""
    markdown_path: str = ""
    stage: str = "start"
    cached: bool = False
    refreshed: bool = False
    used_existing_markdown: bool = False
    agent_runtime: Optional[Dict[str, object]] = None


def _is_usable_result(result: Dict[str, object]) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


def _resolve_stage(result: Dict[str, object]) -> str:
    if not _is_usable_result(result):
        return "failed"
    if result.get("cached") and not result.get("refreshed"):
        return "render_done"
    if result.get("refreshed"):
        return "render_done"
    if result.get("used_existing_markdown"):
        return "build_profile"
    return "done"


def _stellar_home_artifacts_missing(html_path: str) -> bool:
    base_dir = str(os.path.dirname(str(html_path or "").strip()) or "").strip()
    if not base_dir:
        return True
    return not (
        os.path.exists(os.path.join(base_dir, "index.html"))
        and os.path.exists(os.path.join(base_dir, "stellar_home_data.json"))
    )


def create_generation_api(
    *,
    append_coords_section: Callable[[str], str],
    parse_places: Callable[[str], List[Dict[str, str]]],
    parse_events: Callable[[str], List[Dict[str, str]]],
    build_points: Callable[..., List[Dict[str, object]]],
    collect_quality_metrics: Callable[[str], Dict[str, int]],
    validate_data_quality: Callable[[str], List[str]],
    print_quality_report: Callable[[str], None],
    generation_service_utils: object,
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
    render_html_fn: Callable[..., str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
    save_html: Callable[[str, str], str],
    format_seconds: Callable[[float], str],
    get_llm_client: Callable[..., object],
    generate_historical_markdown: Callable[[object, str], str],
    cache_dependency_paths: List[str],
    current_profile_signature: Callable[[], str],
    build_amap_config_js: Callable[[], bytes],
    build_geovis_config_js: Callable[[], bytes],
    refresh_stellar_homepage: Optional[Callable[[str], Dict[str, object]]],
    available_story_names: Optional[Callable[[], List[str]]],
    logger: object,
) -> Dict[str, object]:
    generation_tools = story_generation_tools_utils.create_generation_tools(
        append_coords_section=append_coords_section,
        parse_places=parse_places,
        parse_events=parse_events,
        build_points=build_points,
        collect_quality_metrics=collect_quality_metrics,
        validate_data_quality=validate_data_quality,
        print_quality_report=print_quality_report,
    )

    def build_generation_state(person: str, result: Dict[str, object], *, requested_person: str = "") -> GenerationState:
        markdown_path = str(result.get("markdown_path") or "")
        md_draft = ""
        if markdown_path and os.path.exists(markdown_path):
            md_draft = read_text(markdown_path)

        validation = result.get("_validation")
        issues = []
        if isinstance(validation, dict):
            raw_issues = validation.get("issues") or []
            if isinstance(raw_issues, list):
                issues = [str(item) for item in raw_issues]

        profile = result.get("_profile")
        profile_data = profile if isinstance(profile, dict) else None
        agent_runtime = result.get("_agent_runtime")
        agent_runtime_data = agent_runtime if isinstance(agent_runtime, dict) else None

        return GenerationState(
            person=person,
            requested_person=str(requested_person or result.get("requested_person") or person or ""),
            md_draft=md_draft,
            quality_issues=issues,
            retry_count=0,
            profile=profile_data,
            html_path=str(result.get("html_path") or ""),
            markdown_path=markdown_path,
            stage=_resolve_stage(result),
            cached=bool(result.get("cached")),
            refreshed=bool(result.get("refreshed")),
            used_existing_markdown=bool(result.get("used_existing_markdown")),
            agent_runtime=agent_runtime_data,
        )

    def list_generation_tools() -> List[Dict[str, str]]:
        specs: List[Dict[str, str]] = []
        for key, func in generation_tools.items():
            tool_meta = getattr(func, "__tool__", None)
            if tool_meta is None:
                continue
            specs.append(
                {
                    "key": key,
                    "name": tool_meta.name,
                    "description": tool_meta.description,
                }
            )
        return specs

    def _apply_homepage_refresh_result(result: Dict[str, object], refresh_result: Dict[str, object]) -> Dict[str, object]:
        normalized_refresh = dict(refresh_result or {}) if isinstance(refresh_result, dict) else {}
        result["_homepage_refresh"] = normalized_refresh
        if bool(normalized_refresh.get("ok")):
            return result
        detail = (
            str(normalized_refresh.get("error") or "").strip()
            or str(normalized_refresh.get("output") or "").strip()
            or "首页刷新失败"
        )
        summary = f"首页刷新失败：{detail}"
        result["ok"] = False
        result["status"] = "degraded"
        result["degraded"] = True
        result["warning"] = summary
        result["error"] = summary
        result["homepage_refresh_failed"] = True
        result["homepage_refresh_error"] = detail
        return result

    def should_refresh_stellar_home(result: Dict[str, object]) -> bool:
        if not _is_usable_result(result):
            return False
        html_path = str(result.get("html_path") or "").strip()
        if not html_path:
            return False
        if result.get("cached") and (not result.get("refreshed")) and (not _stellar_home_artifacts_missing(html_path)):
            return False
        return True

    def generate_for_person(
        client: object,
        person: str,
        progress: Optional[callable] = None,
        allow_cache: bool = True,
        event_callback: Optional[callable] = None,
        refresh_homepage: bool = True,
    ) -> Dict[str, object]:
        requested_person = str(person or "").strip()
        available_names: List[str] = []
        if available_story_names:
            try:
                available_names = [str(item or "").strip() for item in list(available_story_names() or []) if str(item or "").strip()]
            except Exception:
                available_names = []
        canonical_person = str(canonical_person_name(requested_person, available_names) or requested_person).strip()
        result = generation_service_utils.generate_for_person(
            client,
            canonical_person,
            progress=progress,
            allow_cache=allow_cache,
            event_callback=event_callback,
            story_paths=story_paths,
            read_text=read_text,
            extract_export_data_from_html=extract_export_data_from_html,
            write_text=write_text,
            render_profile_html=render_profile_html,
            load_profile_from_md=load_profile_from_md,
            normalize_markdown_tables=normalize_markdown_tables,
            compute_total_distance_km=compute_total_distance_km,
            insert_distance_intro=insert_distance_intro,
            save_markdown=save_markdown,
            geocode_markdown_tool=generation_tools["geocode_markdown"],
            parse_story_markdown_tool=generation_tools["parse_story_markdown"],
            validate_story_markdown_tool=generation_tools["validate_story_markdown"],
            render_html_fn=render_html_fn,
            render_amap_html=render_amap_html,
            save_html=save_html,
            format_seconds=format_seconds,
            get_llm_client=get_llm_client,
            generate_historical_markdown=generate_historical_markdown,
            cache_dependency_paths=cache_dependency_paths,
            logger=logger,
            current_profile_signature=current_profile_signature,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
        )
        result["requested_person"] = requested_person
        if refresh_homepage and refresh_stellar_homepage and should_refresh_stellar_home(result):
            result = _apply_homepage_refresh_result(result, refresh_stellar_homepage(canonical_person))
        result["_state"] = asdict(build_generation_state(canonical_person, result, requested_person=requested_person))
        return result

    return {
        "tools": generation_tools,
        "tool_specs": list_generation_tools(),
        "build_generation_state": build_generation_state,
        "should_refresh_stellar_home": should_refresh_stellar_home,
        "generate_for_person": generate_for_person,
    }

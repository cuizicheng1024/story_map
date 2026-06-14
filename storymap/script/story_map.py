"""
简要说明：
- 读取人物生平 Markdown，解析“年份”表中的地点与事件列
- 调用 geocode_city 获取 WGS84 坐标（若来源为高德 GCJ-02 则会自动转换）
- 生成可交互 HTML 地图：支持高德多种底图，连线展示顺序，Markdown 弹窗显示大事
"""
import logging
from typing import Dict, List, Optional

try:
    from .api import run_server as _run_api_server
    from . import app_factory as app_factory_utils
    from .artifacts import (
        ArtifactExportService,
        _active_story_map_dir,
        _extract_export_data_from_html,
        _public_story_map_dirs,
        _project_root,
        _read_text,
        _relative_path,
        _story_paths,
        _update_home_coords,
        _write_text,
        refresh_stellar_homepage,
        save_html,
    )
    from .env_utils import apply_story_map_env_aliases, load_project_env
    from . import export_builders as export_builder_utils
    from . import story_artifact_api as story_artifact_api_utils
    from .map_client import (
        append_coords_section,
        compute_total_distance_km,
        geocode_city,
        insert_distance_intro,
    )
    from .map_html_renderer import (
        build_info_panel_html,
        render_amap_html,
        render_multi_html,
        render_profile_html,
    )
    from . import map_html_renderer as map_html_renderer_utils
    from . import geocode_service as geocode_service_utils
    from . import generation_service as generation_service_utils
    from .history_qa_agent import LocalHistoryQAAgent
    from . import parsers as parser_utils
    from . import profile_builder as profile_builder_utils
    from .project_paths import story_md_dir_path, story_person_names
    from . import story_entrypoints as story_entrypoints_utils
    from . import story_generation_api as story_generation_api_utils
    from . import story_geocode_api as story_geocode_api_utils
    from . import story_profile_api as story_profile_api_utils
    from . import story_runtime_helpers as story_runtime_helpers_utils
    from . import story_runtime_api as story_runtime_api_utils
    from . import runtime_support as runtime_support_utils
    from . import story_cli as story_cli_utils
    from .story_agents import (
        StoryAgentLLM,
        extract_historical_figures,
        generate_historical_markdown,
        save_markdown,
    )
except ImportError:
    from api import run_server as _run_api_server
    import app_factory as app_factory_utils
    from artifacts import (
        ArtifactExportService,
        _active_story_map_dir,
        _extract_export_data_from_html,
        _public_story_map_dirs,
        _project_root,
        _read_text,
        _relative_path,
        _story_paths,
        _update_home_coords,
        _write_text,
        refresh_stellar_homepage,
        save_html,
    )
    from env_utils import apply_story_map_env_aliases, load_project_env
    import export_builders as export_builder_utils
    import story_artifact_api as story_artifact_api_utils
    from map_client import (
        append_coords_section,
        compute_total_distance_km,
        geocode_city,
        insert_distance_intro,
    )
    from map_html_renderer import (
        build_info_panel_html,
        render_amap_html,
        render_multi_html,
        render_profile_html,
    )
    import map_html_renderer as map_html_renderer_utils
    import geocode_service as geocode_service_utils
    import generation_service as generation_service_utils
    from history_qa_agent import LocalHistoryQAAgent
    import parsers as parser_utils
    import profile_builder as profile_builder_utils
    from project_paths import story_md_dir_path, story_person_names
    import story_entrypoints as story_entrypoints_utils
    import story_generation_api as story_generation_api_utils
    import story_geocode_api as story_geocode_api_utils
    import story_profile_api as story_profile_api_utils
    import story_runtime_helpers as story_runtime_helpers_utils
    import story_runtime_api as story_runtime_api_utils
    import runtime_support as runtime_support_utils
    import story_cli as story_cli_utils
    from story_agents import (
        StoryAgentLLM,
        extract_historical_figures,
        generate_historical_markdown,
        save_markdown,
    )


load_project_env(from_file=__file__, override=False)
apply_story_map_env_aliases()
runtime_support_utils.apply_minimax_env_aliases()

_LOGGER = logging.getLogger("story_map")
if not _LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)

_STARTUP_ISSUES = runtime_support_utils.validate_startup_or_raise(
    _LOGGER,
    _project_root(),
    strict=runtime_support_utils.env_flag("STORY_MAP_STRICT_STARTUP", "MAP_STORY_STRICT_STARTUP"),
)


_MAX_TEXT_LEN = 200
_HELPERS = story_runtime_helpers_utils.create_runtime_helpers(
    runtime_support_utils=runtime_support_utils,
    local_history_qa_agent_cls=LocalHistoryQAAgent,
    story_agent_llm_cls=StoryAgentLLM,
    project_root=_project_root,
    max_text_len=_MAX_TEXT_LEN,
)
_ALLOWED_ORIGINS = _HELPERS["allowed_origins"]
_VENDOR_CACHE = _HELPERS["vendor_cache"]
_VENDOR_LOCK = _HELPERS["vendor_lock"]
_amap_config_js = _HELPERS["amap_config_js"]
_geovis_config_js = _HELPERS["geovis_config_js"]
_local_history_reply = _HELPERS["local_history_reply"]
_local_agent_reply = _HELPERS["local_agent_reply"]
_fetch_vendor_bytes = _HELPERS["fetch_vendor_bytes"]
_resolve_cors_origin = _HELPERS["resolve_cors_origin"]
_get_llm_client = _HELPERS["get_llm_client"]

_GEOCODE_API = story_geocode_api_utils.create_geocode_api(
    geocode_service_utils=geocode_service_utils,
)
_lookup_coords_from_historical_index = _GEOCODE_API["lookup_coords_from_historical_index"]
resolve_place_coord = _GEOCODE_API["resolve_place_coord"]
_batch_split_ancient_modern = _GEOCODE_API["batch_split_ancient_modern"]
_split_ancient_modern = _GEOCODE_API["split_ancient_modern"]
_fuzzy_coord_lookup = _GEOCODE_API["fuzzy_coord_lookup"]

def _print_quality_report(md: str) -> None:
    generation_service_utils.print_quality_report(md)


_validate_input_text = _HELPERS["validate_input_text"]
_format_seconds = _HELPERS["format_seconds"]


_PROFILE_API = story_profile_api_utils.create_profile_api_from_geocode_api(
    parser_utils=parser_utils,
    profile_builder_utils=profile_builder_utils,
    generation_service_utils=generation_service_utils,
    geocode_city=geocode_city,
    geocode_api=_GEOCODE_API,
    render_profile_html=render_profile_html,
    build_info_panel_html=build_info_panel_html,
    render_amap_html=render_amap_html,
)
_build_profile_data = _PROFILE_API["build_profile_data"]
parse_places = _PROFILE_API["parse_places"]
parse_events = _PROFILE_API["parse_events"]
build_points = _PROFILE_API["build_points"]
extract_intro_fields = _PROFILE_API["extract_intro_fields"]
render_html = _PROFILE_API["render_html"]
load_profile_from_md = _PROFILE_API["load_profile_from_md"]
_GENERATION_API = story_generation_api_utils.create_generation_api(
    append_coords_section=append_coords_section,
    parse_places=parse_places,
    parse_events=parse_events,
    build_points=build_points,
    collect_quality_metrics=generation_service_utils.collect_quality_metrics,
    validate_data_quality=generation_service_utils.validate_data_quality,
    print_quality_report=_print_quality_report,
    generation_service_utils=generation_service_utils,
    story_paths=lambda person: _story_paths(person),
    read_text=lambda path: _read_text(path),
    extract_export_data_from_html=lambda html: _extract_export_data_from_html(html),
    write_text=lambda path, content: _write_text(path, content),
    render_profile_html=lambda profile: render_profile_html(profile),
    load_profile_from_md=lambda md, *args, **kwargs: load_profile_from_md(md, *args, **kwargs),
    normalize_markdown_tables=lambda md: parser_utils._normalize_markdown_tables(md),
    compute_total_distance_km=lambda md: compute_total_distance_km(md),
    insert_distance_intro=lambda md, km: insert_distance_intro(md, km),
    save_markdown=lambda person, md: save_markdown(person, md),
    render_html_fn=lambda title, points, **kwargs: render_html(title, points, **kwargs),
    render_amap_html=lambda title, points, info_html: render_amap_html(title, points, info_html),
    save_html=lambda person, html: save_html(person, html),
    format_seconds=lambda seconds: _format_seconds(seconds),
    get_llm_client=lambda **kwargs: _get_llm_client(**kwargs),
    generate_historical_markdown=lambda client, person: generate_historical_markdown(client, person),
    cache_dependency_paths=[
        str(path)
        for path in map_html_renderer_utils.profile_render_dependency_paths()
    ],
    current_profile_signature=lambda: map_html_renderer_utils.profile_template_signature(),
    build_amap_config_js=lambda: runtime_support_utils.build_amap_config_js(),
    build_geovis_config_js=lambda: runtime_support_utils.build_geovis_config_js(),
    refresh_stellar_homepage=lambda person: refresh_stellar_homepage(person),
    available_story_names=lambda: story_person_names(story_md_dir_path()),
    logger=_LOGGER,
)
_GENERATION_TOOLS = _GENERATION_API["tools"]
_GENERATION_TOOL_SPECS = _GENERATION_API["tool_specs"]


def _resolve_targets_from_text(client: StoryAgentLLM, text: str, fallback_to_input: bool) -> List[str]:
    return story_cli_utils.resolve_targets_from_text(
        client=client,
        text=text,
        extract_historical_figures=extract_historical_figures,
        fallback_to_input=fallback_to_input,
    )


def run_interactive() -> None:
    story_cli_utils.run_interactive(
        create_client=StoryAgentLLM,
        validate_input_text=_validate_input_text,
        resolve_targets=_resolve_targets_from_text,
        generate_historical_markdown=generate_historical_markdown,
        enrich_markdown_for_map=lambda md: generation_service_utils.enrich_markdown_for_map(
            md,
            normalize_markdown_tables=parser_utils._normalize_markdown_tables,
            geocode_markdown=append_coords_section,
            compute_total_distance_km=compute_total_distance_km,
            insert_distance_intro=insert_distance_intro,
        ),
        validate_data_quality=generation_service_utils.validate_data_quality,
        print_quality_report=_print_quality_report,
        save_markdown=save_markdown,
        parse_places=parse_places,
        parse_events=parse_events,
        build_points=build_points,
        render_html=render_html,
        render_amap_html=render_amap_html,
        save_html=save_html,
        format_seconds=_format_seconds,
        logger=_LOGGER,
    )


def generate_for_person(
    client: Optional[StoryAgentLLM],
    person: str,
    progress: Optional[callable] = None,
    allow_cache: bool = True,
    event_callback: Optional[callable] = None,
    refresh_homepage: bool = True,
) -> Dict[str, object]:
    return _GENERATION_API["generate_for_person"](
        client,
        person,
        progress=progress,
        allow_cache=allow_cache,
        event_callback=event_callback,
        refresh_homepage=refresh_homepage,
    )


_ARTIFACT_API = story_artifact_api_utils.create_artifact_api(
    artifact_export_service_cls=ArtifactExportService,
    build_geojson_for_profile=export_builder_utils.build_geojson_for_profile,
    build_csv_for_profile=export_builder_utils.build_csv_for_profile,
    build_geojson_for_multi=export_builder_utils.build_geojson_for_multi,
    build_csv_for_multi=export_builder_utils.build_csv_for_multi,
)
_ensure_profile_exports = _ARTIFACT_API["ensure_profile_exports"]
_ensure_multi_exports = _ARTIFACT_API["ensure_multi_exports"]


def _compute_overlaps(people: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return runtime_support_utils.compute_overlaps(people)


def _build_conclusion(results: List[Dict[str, object]], multi: bool) -> str:
    return runtime_support_utils.build_conclusion(results, multi)


_MAX_CONCURRENCY = 5
_COLOR_PALETTE = ("#1e40af", "#c2410c", "#15803d", "#7c3aed", "#0f766e", "#b91c1c")
_RUNTIME_API = story_runtime_api_utils.create_runtime_api(
    app_factory_utils=app_factory_utils,
    logger=_LOGGER,
    allowed_origins=_ALLOWED_ORIGINS,
    resolve_cors_origin=_resolve_cors_origin,
    active_story_map_dir=_active_story_map_dir,
    public_story_map_dirs=_public_story_map_dirs,
    project_root=_project_root,
    fetch_vendor_bytes=_fetch_vendor_bytes,
    vendor_cache=_VENDOR_CACHE,
    vendor_lock=_VENDOR_LOCK,
    amap_config_js=_amap_config_js,
    geovis_config_js=_geovis_config_js,
    update_home_coords=_update_home_coords,
    get_llm_client=_get_llm_client,
    local_agent_reply=_local_agent_reply,
    local_history_reply=_local_history_reply,
    format_seconds=_format_seconds,
    validate_input_text=_validate_input_text,
    extract_historical_figures=extract_historical_figures,
    generate_for_person=generate_for_person,
    ensure_profile_exports=_ensure_profile_exports,
    ensure_multi_exports=_ensure_multi_exports,
    compute_overlaps=_compute_overlaps,
    build_conclusion=_build_conclusion,
    render_multi_html=render_multi_html,
    save_html=save_html,
    relative_path=_relative_path,
    max_concurrency=_MAX_CONCURRENCY,
    color_palette=_COLOR_PALETTE,
)
_APP_RUNTIME = _RUNTIME_API["runtime"]
_PROXY_SERVICE = _RUNTIME_API["proxy_service"]
_STATIC_SERVICE = _RUNTIME_API["static_service"]
_TASK_SERVICE = _RUNTIME_API["task_service"]
_coords_bulk_update = _RUNTIME_API["coords_bulk_update"]
_shutdown_services = _RUNTIME_API["shutdown_services"]


def create_app():
    return _RUNTIME_API["app"]


APP = create_app()


def _run_server(port: int) -> None:
    return story_entrypoints_utils.run_server(
        run_api_server=_run_api_server,
        app=APP,
        port=port,
        logger=_LOGGER,
    )


def main():
    return story_entrypoints_utils.run_main(
        build_arg_parser=story_cli_utils.build_arg_parser,
        run_server_fn=_run_server,
        run_interactive_fn=run_interactive,
        run_person_generation=story_cli_utils.run_person_generation,
        person_text_resolver=lambda args: getattr(args, "person", ""),
        create_client=StoryAgentLLM,
        validate_input_text=_validate_input_text,
        resolve_targets=_resolve_targets_from_text,
        generate_for_person=generate_for_person,
    )


if __name__ == "__main__":
    main()

"""
简要说明：
- 读取人物生平 Markdown，解析“年份”表中的地点与事件列
- 调用 geocode_city 获取 WGS84 坐标（若来源为高德 GCJ-02 则会自动转换）
- 生成可交互 HTML 地图：支持高德多种底图，连线展示顺序，Markdown 弹窗显示大事
"""
import argparse
import atexit
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

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
        save_html,
    )
    from .env_utils import apply_story_map_env_aliases, load_project_env
    from . import export_builders as export_builder_utils
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
    from . import geocode_service as geocode_service_utils
    from . import generation_service as generation_service_utils
    from . import parsers as parser_utils
    from . import profile_builder as profile_builder_utils
    from . import runtime_support as runtime_support_utils
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
        save_html,
    )
    from env_utils import apply_story_map_env_aliases, load_project_env
    import export_builders as export_builder_utils
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
    import geocode_service as geocode_service_utils
    import generation_service as generation_service_utils
    import parsers as parser_utils
    import profile_builder as profile_builder_utils
    import runtime_support as runtime_support_utils
    from story_agents import (
        StoryAgentLLM,
        extract_historical_figures,
        generate_historical_markdown,
        save_markdown,
    )


load_project_env(from_file=__file__, override=True)
apply_story_map_env_aliases()
runtime_support_utils.apply_minimax_env_aliases()

_LOGGER = logging.getLogger("story_map")
if not _LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)


def _lookup_coords_from_historical_index(*names: str) -> Optional[Tuple[float, float]]:
    return geocode_service_utils.lookup_coords_from_historical_index(*names)


def resolve_place_coord(place: str, year: Optional[int] = None, *aliases: str) -> Optional[Tuple[float, float]]:
    return geocode_service_utils.resolve_place_coord(place, year, *aliases)


_resolve_place_coord = resolve_place_coord


_CLIENT_FACTORY = runtime_support_utils.SharedLLMClientFactory(StoryAgentLLM)
_MAX_TEXT_LEN = 200
_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("STORY_MAP_ALLOWED_ORIGINS", "*").split(",") if o.strip()]

_VENDOR_CACHE: Dict[str, Tuple[str, bytes]] = {}
_VENDOR_LOCK = threading.Lock()
_VENDOR_SOURCES: Dict[str, List[str]] = {
    # Frontend pages rely on CDN-hosted assets (React/Babel/Tailwind).
    # In restricted networks these CDNs may be blocked; serving them via the
    # same origin (this server) avoids CORS/DNS issues and makes pages usable.
    "tailwindcss.js": [
        "https://cdn.tailwindcss.com",
    ],
    "react.production.min.js": [
        "https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js",
        "https://unpkg.com/react@18/umd/react.production.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js",
    ],
    "react-dom.production.min.js": [
        "https://cdn.jsdelivr.net/npm/react-dom@18/umd/react-dom.production.min.js",
        "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js",
    ],
    "babel.min.js": [
        "https://cdn.jsdelivr.net/npm/@babel/standalone@7.24.7/babel.min.js",
        "https://unpkg.com/@babel/standalone@7.24.7/babel.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.24.7/babel.min.js",
    ],
}

def _amap_config_js() -> bytes:
    return runtime_support_utils.build_amap_config_js()


def _local_history_reply(messages: object) -> str:
    return runtime_support_utils.local_history_reply(messages)


def _fetch_vendor_bytes(name: str) -> Tuple[str, bytes]:
    return runtime_support_utils.fetch_vendor_bytes(name, _VENDOR_SOURCES)


def _resolve_cors_origin(origin: str) -> Optional[str]:
    return runtime_support_utils.resolve_cors_origin(origin, _ALLOWED_ORIGINS)


def _get_llm_client(event_callback: Optional[callable] = None) -> StoryAgentLLM:
    return _CLIENT_FACTORY.get_client(event_callback=event_callback)


def _batch_split_ancient_modern(
    loc_texts: List[str], event_callback: Optional[callable] = None
) -> Dict[str, Tuple[str, str]]:
    return geocode_service_utils.batch_split_ancient_modern(
        loc_texts,
        event_callback=event_callback,
    )


def _split_ancient_modern(loc_text: str, event_callback: Optional[callable] = None) -> Tuple[str, str]:
    return geocode_service_utils.split_ancient_modern(
        loc_text,
        event_callback=event_callback,
    )


def _fuzzy_coord_lookup(coords_cache: Dict[str, Tuple[float, float]], candidates: List[str]) -> Optional[Tuple[float, float]]:
    return geocode_service_utils.fuzzy_coord_lookup(coords_cache, candidates)


def _validate_input_text(text: object) -> Optional[str]:
    return runtime_support_utils.validate_input_text(text, _MAX_TEXT_LEN)


def _build_profile_data(
    md: str,
    event_callback: Optional[callable] = None,
    *,
    allow_geocode: bool = True,
) -> Optional[Dict[str, object]]:
    return profile_builder_utils.build_profile_data(
        md,
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=_split_ancient_modern,
        batch_split_ancient_modern=_batch_split_ancient_modern,
        fuzzy_coord_lookup=_fuzzy_coord_lookup,
        lookup_coords_from_historical_index=_lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        build_points_fn=build_points,
    )


def parse_places(md: str) -> List[Dict[str, str]]:
    return parser_utils.parse_places(md)


def parse_events(md: str) -> List[Dict[str, str]]:
    return parser_utils.parse_events(md)


def _print_quality_report(md: str) -> None:
    generation_service_utils.print_quality_report(md)


def _format_seconds(sec: float) -> str:
    return runtime_support_utils.format_seconds(sec)


def build_points(
    places: List[Dict[str, str]],
    events: List[Dict[str, str]],
    *,
    allow_geocode: bool = True,
    event_callback: Optional[callable] = None,
) -> List[Dict[str, object]]:
    return profile_builder_utils.build_points(
        places,
        events,
        allow_geocode=allow_geocode,
        lookup_coords_from_historical_index=_lookup_coords_from_historical_index,
        geocode_city=geocode_city,
        event_callback=event_callback,
    )


def extract_intro_fields(md: str) -> Dict[str, str]:
    return profile_builder_utils.extract_intro_fields(md)


_extract_intro_fields = extract_intro_fields


def render_html(title: str, points: List[Dict[str, object]], md: str = "") -> str:
    return generation_service_utils.render_html(
        title,
        points,
        md=md,
        build_profile_data=_build_profile_data,
        extract_intro_fields=extract_intro_fields,
        render_profile_html=render_profile_html,
        build_info_panel_html=build_info_panel_html,
        render_amap_html=render_amap_html,
    )


def load_profile_from_md(
    md: str,
    event_callback: Optional[callable] = None,
    *,
    allow_geocode: bool = True,
) -> Optional[Dict[str, object]]:
    return profile_builder_utils.load_profile_from_md(
        md,
        allow_geocode=allow_geocode,
        event_callback=event_callback,
        split_ancient_modern=_split_ancient_modern,
        batch_split_ancient_modern=_batch_split_ancient_modern,
        fuzzy_coord_lookup=_fuzzy_coord_lookup,
        lookup_coords_from_historical_index=_lookup_coords_from_historical_index,
        resolve_place_coord=resolve_place_coord,
        build_points_fn=build_points,
    )


_load_profile_from_md = load_profile_from_md


def run_interactive() -> None:
    """
    交互模式：
    - 输入人物或一句包含人物的句子
    - 生成并输出地图文件路径
    """
    client = StoryAgentLLM()
    while True:
        try:
            text = input("请输入人物或一句包含人物的句子（q 退出）：").strip()
        except EOFError:
            break
        if not text:
            continue
        err = _validate_input_text(text)
        if err:
            print(err)
            continue
        if text.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        targets = extract_historical_figures(client, text)
        if not targets:
            print("未识别到历史人物")
            continue
        print(f"识别到人物数量：{len(targets)}")
        stats = {"markdown": 0, "html": 0, "failed": 0}
        for person in targets:
            print(f"正在生成 {person} 生平文档，可能需要一些时间...")
            t0 = time.perf_counter()
            t_step = time.perf_counter()
            md = generate_historical_markdown(client, person)
            t_md = time.perf_counter() - t_step
            if not md:
                print(f"未取得：{person}")
                stats["failed"] += 1
                continue
            md = parser_utils._normalize_markdown_tables(md)
            km = compute_total_distance_km(md)
            if isinstance(km, float):
                md = insert_distance_intro(md, km)
            print("正在进行地点地理编码，可能需要一些时间...")
            t_step = time.perf_counter()
            md = append_coords_section(md)
            t_geo = time.perf_counter() - t_step
            _print_quality_report(md)
            saved = save_markdown(person, md)
            print(f"已生成：{saved}")
            t_step = time.perf_counter()
            try:
                places = parse_places(md)
                events = parse_events(md)
                pts = build_points(places, events)
                html = render_html(person, pts, md=md)
            except Exception as exc:
                _LOGGER.warning("render_failed person=%s error=%s", person, exc)
                html = render_amap_html(person, [], "")
            t_render = time.perf_counter() - t_step
            out = save_html(person, html)
            print(out)
            total = time.perf_counter() - t0
            print(
                f"耗时：生平生成 {_format_seconds(t_md)}，地理编码 {_format_seconds(t_geo)}，"
                f"地图渲染 {_format_seconds(t_render)}，总计 {_format_seconds(total)}"
            )
            stats["markdown"] += 1
            stats["html"] += 1
        print(
            f"本次完成：人物 {len(targets)}，文档 {stats['markdown']}，地图 {stats['html']}，失败 {stats['failed']}"
        )


def generate_for_person(
    client: Optional[StoryAgentLLM],
    person: str,
    progress: Optional[callable] = None,
    allow_cache: bool = True,
    event_callback: Optional[callable] = None,
) -> Dict[str, object]:
    return generation_service_utils.generate_for_person(
        client,
        person,
        progress=progress,
        allow_cache=allow_cache,
        event_callback=event_callback,
        story_paths=_story_paths,
        read_text=_read_text,
        extract_export_data_from_html=_extract_export_data_from_html,
        write_text=_write_text,
        render_profile_html=render_profile_html,
        load_profile_from_md=load_profile_from_md,
        normalize_markdown_tables=parser_utils._normalize_markdown_tables,
        compute_total_distance_km=compute_total_distance_km,
        insert_distance_intro=insert_distance_intro,
        append_coords_section=append_coords_section,
        print_quality_report_fn=_print_quality_report,
        save_markdown=save_markdown,
        parse_places=parse_places,
        parse_events=parse_events,
        build_points=build_points,
        render_html_fn=render_html,
        render_amap_html=render_amap_html,
        save_html=save_html,
        format_seconds=_format_seconds,
        get_llm_client=_get_llm_client,
        generate_historical_markdown=generate_historical_markdown,
        logger=_LOGGER,
    )


_generate_for_person = generate_for_person


_ARTIFACT_EXPORTS = ArtifactExportService(
    build_geojson_for_profile=export_builder_utils.build_geojson_for_profile,
    build_csv_for_profile=export_builder_utils.build_csv_for_profile,
    build_geojson_for_multi=export_builder_utils.build_geojson_for_multi,
    build_csv_for_multi=export_builder_utils.build_csv_for_multi,
)


def _ensure_profile_exports(profile: Dict[str, object], base_name: str, allow_cache: bool = True) -> Dict[str, str]:
    return _ARTIFACT_EXPORTS.ensure_profile_exports(profile, base_name, allow_cache=allow_cache)


def _ensure_multi_exports(people: List[Dict[str, object]], base_name: str, allow_cache: bool = True) -> Dict[str, str]:
    return _ARTIFACT_EXPORTS.ensure_multi_exports(people, base_name, allow_cache=allow_cache)


def _compute_overlaps(people: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return runtime_support_utils.compute_overlaps(people)


def _build_conclusion(results: List[Dict[str, object]], multi: bool) -> str:
    return runtime_support_utils.build_conclusion(results, multi)


_MAX_CONCURRENCY = 5
_COLOR_PALETTE = ("#1e40af", "#c2410c", "#15803d", "#7c3aed", "#0f766e", "#b91c1c")
_APP_RUNTIME = app_factory_utils.create_story_map_runtime(
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
    update_home_coords=_update_home_coords,
    get_llm_client=_get_llm_client,
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

_PROXY_SERVICE = _APP_RUNTIME["proxy_service"]
_STATIC_SERVICE = _APP_RUNTIME["static_service"]
_TASK_SERVICE = _APP_RUNTIME["task_service"]
_coords_bulk_update = _APP_RUNTIME["coords_bulk_update"]


def _shutdown_services() -> None:
    _APP_RUNTIME["shutdown"]()


atexit.register(_shutdown_services)


def create_app():
    return _APP_RUNTIME["app"]


APP = create_app()


def _run_server(port: int) -> None:
    _run_api_server(APP, port, _LOGGER)


def main():
    """
    命令行入口：
    - 可指定人物与底图
    - 未指定人物时进入交互模式
    """
    parser = argparse.ArgumentParser(
        description="生成人物生平 Markdown，并导出可交互地图 HTML"
    )
    parser.add_argument("-p", "--person", help="历史人物姓名或一句包含人物的句子", required=False)
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 服务")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 服务端口")
    args = parser.parse_args()
    if args.serve:
        return _run_server(args.port)
    if not args.person:
        return run_interactive()
    err = _validate_input_text(args.person)
    if err:
        print(err)
        return
    client = StoryAgentLLM()
    targets = extract_historical_figures(client, args.person)
    if not targets:
        fallback = str(args.person or "").strip()
        if not fallback:
            print("未识别到人物")
            return
        targets = [fallback]
    stats = {"markdown": 0, "html": 0, "failed": 0}
    for person in targets:
        print(f"正在生成 {person} 生平文档，可能需要一些时间...")
        result = generate_for_person(client, person)
        if not result.get("ok"):
            print(f"未取得：{person}")
            stats["failed"] += 1
            continue
        print(f"已生成：{result.get('markdown_path')}")
        print(result.get("html_path"))
        duration = result.get("duration") or {}
        print(
            "耗时：生平生成 {markdown}，地理编码 {geocode}，地图渲染 {render}，总计 {total}".format(
                markdown=duration.get("markdown", ""),
                geocode=duration.get("geocode", ""),
                render=duration.get("render", ""),
                total=duration.get("total", ""),
            )
        )
        stats["markdown"] += 1
        stats["html"] += 1
    print(
        f"运行完成：人物 {len(targets)}，文档 {stats['markdown']}，地图 {stats['html']}，失败 {stats['failed']}"
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import atexit
from typing import Callable, Dict, List, Tuple


def create_runtime_api(
    *,
    app_factory_utils: object,
    logger: object,
    allowed_origins: List[str],
    resolve_cors_origin: Callable[[str], str | None],
    active_story_map_dir: Callable[[], str],
    public_story_map_dirs: Callable[[], List[str]],
    project_root: Callable[[], str],
    fetch_vendor_bytes: Callable[[str], Tuple[str, bytes]],
    vendor_cache: Dict[str, Tuple[str, bytes]],
    vendor_lock: object,
    amap_config_js: Callable[[], bytes],
    geovis_config_js: Callable[[], bytes],
    update_home_coords: Callable[..., Tuple[int, Dict[str, object]]],
    get_llm_client: Callable[..., object],
    local_agent_reply: Callable[[object], object],
    local_history_reply: Callable[[object], str],
    format_seconds: Callable[[float], str],
    validate_input_text: Callable[[str], str | None],
    extract_historical_figures: Callable[[object, str], List[str]],
    generate_for_person: Callable[..., Dict[str, object]],
    refresh_stellar_homepage: Callable[[str], Dict[str, object]] | None,
    ensure_profile_exports: Callable[..., Dict[str, str]],
    ensure_multi_exports: Callable[..., Dict[str, str]],
    compute_overlaps: Callable[[List[Dict[str, object]]], List[Dict[str, object]]],
    build_conclusion: Callable[[List[Dict[str, object]], bool], str],
    render_multi_html: Callable[[Dict[str, object]], str],
    save_html: Callable[[str, str], str],
    relative_path: Callable[[str], str],
    max_concurrency: int,
    color_palette: Tuple[str, ...],
) -> Dict[str, object]:
    runtime = app_factory_utils.create_story_map_runtime(
        logger=logger,
        allowed_origins=allowed_origins,
        resolve_cors_origin=resolve_cors_origin,
        active_story_map_dir=active_story_map_dir,
        public_story_map_dirs=public_story_map_dirs,
        project_root=project_root,
        fetch_vendor_bytes=fetch_vendor_bytes,
        vendor_cache=vendor_cache,
        vendor_lock=vendor_lock,
        amap_config_js=amap_config_js,
        geovis_config_js=geovis_config_js,
        update_home_coords=update_home_coords,
        get_llm_client=get_llm_client,
        local_agent_reply=local_agent_reply,
        local_history_reply=local_history_reply,
        format_seconds=format_seconds,
        validate_input_text=validate_input_text,
        extract_historical_figures=extract_historical_figures,
        generate_for_person=generate_for_person,
        refresh_stellar_homepage=refresh_stellar_homepage,
        ensure_profile_exports=ensure_profile_exports,
        ensure_multi_exports=ensure_multi_exports,
        compute_overlaps=compute_overlaps,
        build_conclusion=build_conclusion,
        render_multi_html=render_multi_html,
        save_html=save_html,
        relative_path=relative_path,
        max_concurrency=max_concurrency,
        color_palette=color_palette,
    )

    def shutdown_services() -> None:
        runtime["shutdown"]()

    atexit.register(shutdown_services)

    return {
        "runtime": runtime,
        "app": runtime["app"],
        "proxy_service": runtime["proxy_service"],
        "static_service": runtime["static_service"],
        "task_service": runtime["task_service"],
        "coords_bulk_update": runtime["coords_bulk_update"],
        "shutdown_services": shutdown_services,
    }

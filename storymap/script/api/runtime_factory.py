from __future__ import annotations

import threading
from typing import Callable, Dict, List, Tuple, TypedDict

from .app import create_app as _create_api_app
from .proxy import ProxyService
from .static import StaticService
from ..runtime.task_service import TaskService


class StoryMapRuntime(TypedDict):
    app: object
    task_service: TaskService
    proxy_service: ProxyService
    static_service: StaticService
    coords_bulk_update: Callable[[object], Tuple[int, Dict[str, object]]]
    shutdown: Callable[[], None]
    home_coords_lock: threading.Lock


def create_story_map_runtime(
    *,
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
    update_home_coords: Callable[[object, threading.Lock], Tuple[int, Dict[str, object]]],
    get_llm_client: Callable[..., object],
    local_agent_reply: Callable[[object], object],
    local_history_reply: Callable[[object], str],
    format_seconds: Callable[[float], str],
    validate_input_text: Callable[[str], str | None],
    extract_historical_figures: Callable[[object, str], List[str]],
    generate_for_person: Callable[..., Dict[str, object]],
    refresh_stellar_homepage: Callable[[str], Dict[str, object]] | None,
    enqueue_background_job: Callable[..., object] | None,
    ensure_profile_exports: Callable[..., Dict[str, str]],
    ensure_multi_exports: Callable[..., Dict[str, str]],
    compute_overlaps: Callable[[List[Dict[str, object]]], List[Dict[str, object]]],
    build_conclusion: Callable[[List[Dict[str, object]], bool], str],
    render_multi_html: Callable[[Dict[str, object]], str],
    save_html: Callable[[str, str], str],
    relative_path: Callable[[str], str],
    max_concurrency: int,
    color_palette: Tuple[str, ...],
) -> StoryMapRuntime:
    home_coords_lock = threading.Lock()

    proxy_service = ProxyService(
        get_llm_client=get_llm_client,
        local_agent_reply=local_agent_reply,
        local_history_reply=local_history_reply,
        logger=logger,
    )

    static_service = StaticService(
        active_story_map_dir=active_story_map_dir,
        public_story_map_dirs=public_story_map_dirs,
        project_root=project_root,
        fetch_vendor_bytes=fetch_vendor_bytes,
        vendor_cache=vendor_cache,
        vendor_lock=vendor_lock,
    )

    task_service = TaskService(
        logger=logger,
        max_concurrency=max_concurrency,
        color_palette=color_palette,
        project_root=project_root,
        format_seconds=format_seconds,
        validate_input_text=validate_input_text,
        get_llm_client=get_llm_client,
        extract_historical_figures=extract_historical_figures,
        generate_for_person=generate_for_person,
        refresh_stellar_homepage=refresh_stellar_homepage,
        enqueue_background_job=enqueue_background_job,
        ensure_profile_exports=ensure_profile_exports,
        ensure_multi_exports=ensure_multi_exports,
        compute_overlaps=compute_overlaps,
        build_conclusion=build_conclusion,
        render_multi_html=render_multi_html,
        save_html=save_html,
        relative_path=relative_path,
    )

    def coords_bulk_update(data: object) -> Tuple[int, Dict[str, object]]:
        return update_home_coords(data, home_coords_lock)

    app = _create_api_app(
        allowed_origins=allowed_origins,
        resolve_cors_origin=resolve_cors_origin,
        static_service=static_service,
        task_service=task_service,
        proxy_service=proxy_service,
        amap_config_js=amap_config_js,
        geovis_config_js=geovis_config_js,
        coords_bulk_update=coords_bulk_update,
    )

    def shutdown() -> None:
        task_service.shutdown()
        proxy_service.shutdown()

    return {
        "app": app,
        "task_service": task_service,
        "proxy_service": proxy_service,
        "static_service": static_service,
        "coords_bulk_update": coords_bulk_update,
        "shutdown": shutdown,
        "home_coords_lock": home_coords_lock,
    }

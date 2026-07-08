from __future__ import annotations

import os
from typing import Callable, Optional


def public_runtime_map_configs_enabled() -> bool:
    value = (
        os.getenv("MAP_STORY_EMIT_PUBLIC_MAP_CONFIG")
        or os.getenv("STORY_MAP_EMIT_PUBLIC_MAP_CONFIG")
        or ""
    ).strip().lower()
    return value in {"1", "true", "yes", "on"}


def write_runtime_map_configs(
    html_path: str,
    *,
    write_text: Callable[[str, str], None],
    build_amap_config_js: Optional[Callable[[], bytes]] = None,
    build_geovis_config_js: Optional[Callable[[], bytes]] = None,
) -> None:
    if (not html_path) or (not public_runtime_map_configs_enabled()):
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


def try_write_runtime_map_configs(
    html_path: str,
    *,
    write_text: Callable[[str, str], None],
    logger: object,
    build_amap_config_js: Optional[Callable[[], bytes]] = None,
    build_geovis_config_js: Optional[Callable[[], bytes]] = None,
) -> str:
    try:
        write_runtime_map_configs(
            html_path,
            write_text=write_text,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
        )
        return ""
    except Exception as exc:
        logger.warning("runtime_map_config_write_failed html_path=%s error=%s", html_path, exc)
        return str(exc).strip() or "运行时地图配置写入失败"


def runtime_map_configs_missing(html_path: str) -> bool:
    if not public_runtime_map_configs_enabled():
        return False
    if not html_path:
        return True
    output_dir = os.path.dirname(os.path.abspath(html_path))
    return not (
        os.path.exists(os.path.join(output_dir, "amap-config.js"))
        and os.path.exists(os.path.join(output_dir, "geovis-config.js"))
    )

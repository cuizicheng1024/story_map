from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional

from ..generation_pipeline import GenerationStages, build_generation_checkpoint
from .result import GenerationExecutionContext, complete_generation_outcome
from .runtime_config import runtime_map_configs_missing, try_write_runtime_map_configs


def cache_older_than_dependencies(html_path: str, dependency_paths: List[str]) -> bool:
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


def extract_html_template_signature(html: str) -> str:
    text = str(html or "")
    if not text:
        return ""
    m = re.search(r'window\.__TPL_SIG__\s*=\s*"([^"]+)"', text)
    if m:
        return str(m.group(1) or "").strip()
    m = re.search(r'"templateSignature"\s*:\s*"([^"]+)"', text)
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def is_usable_export_profile(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    person = data.get("person")
    return isinstance(person, dict) and bool(str(person.get("name") or "").strip())


def handle_cached_generation(
    *,
    person: str,
    md_path: str,
    html_path: str,
    event_callback: Optional[callable],
    cache_dependency_paths: Optional[List[str]],
    current_profile_signature: Optional[Callable[[], str]],
    read_text: Callable[[str], str],
    extract_export_data_from_html: Callable[[str], Optional[Dict[str, object]]],
    write_text: Callable[[str, str], None],
    render_profile_html: Callable[[Dict[str, object]], str],
    load_profile_from_md: Callable[..., Optional[Dict[str, object]]],
    validate_story_markdown_tool: Callable[[str], Dict[str, object]],
    logger: object,
    build_amap_config_js: Optional[Callable[[], bytes]],
    build_geovis_config_js: Optional[Callable[[], bytes]],
    execution_context: GenerationExecutionContext,
) -> Optional[Dict[str, object]]:
    if not os.path.exists(html_path):
        return None
    cached_html = read_text(html_path)
    cache_stale_by_code = cache_older_than_dependencies(html_path, list(cache_dependency_paths or []))
    cache_stale_by_markdown = False
    cache_stale_by_signature = False
    if os.path.exists(md_path):
        try:
            cache_stale_by_markdown = os.path.getmtime(md_path) > os.path.getmtime(html_path)
        except OSError:
            cache_stale_by_markdown = False
    needs_refresh = (
        ("export-bar" in cached_html)
        or ("amap-config.js" not in cached_html)
        or ("geovis-config.js" not in cached_html)
        or cache_stale_by_code
        or cache_stale_by_markdown
    )
    if not needs_refresh and callable(current_profile_signature):
        expected_signature = str(current_profile_signature() or "").strip()
        actual_signature = extract_html_template_signature(cached_html)
        if expected_signature and actual_signature != expected_signature:
            cache_stale_by_signature = True
            needs_refresh = True
    if (not needs_refresh) and ("window.__EXPORT_DATA__" in cached_html):
        export_data = extract_export_data_from_html(cached_html)
        validation = {"metrics": {}, "issues": []}
        if is_usable_export_profile(export_data) and os.path.exists(md_path):
            md = read_text(md_path)
            if md:
                export_data["markdown"] = md
                validation = validate_story_markdown_tool(md)
        if is_usable_export_profile(export_data):
            config_error = ""
            if runtime_map_configs_missing(html_path):
                config_error = try_write_runtime_map_configs(
                    html_path,
                    write_text=write_text,
                    logger=logger,
                    build_amap_config_js=build_amap_config_js,
                    build_geovis_config_js=build_geovis_config_js,
                )
            return complete_generation_outcome(
                execution_context=execution_context,
                person=person,
                stage=GenerationStages.RENDER_DONE,
                checkpoint=build_generation_checkpoint(source="html_cache", resume_stage=GenerationStages.RENDER_DONE),
                success_payload={
                    "ok": True,
                    "person": person,
                    "markdown_path": md_path if os.path.exists(md_path) else "",
                    "html_path": html_path,
                    "steps": [{"label": "命中缓存", "duration": "0.00s"}],
                    "duration": {"total": "0.00s"},
                    "_profile": export_data,
                    "cached": True,
                },
                steps=[{"label": "命中缓存", "duration": "0.00s"}],
                duration={"total": "0.00s"},
                profile=export_data,
                validation=validation,
                markdown_path=md_path if os.path.exists(md_path) else "",
                html_path=html_path,
                config_error=config_error,
            )
    md = read_text(md_path) if os.path.exists(md_path) else ""
    export_data = extract_export_data_from_html(cached_html)
    if (
        is_usable_export_profile(export_data)
        and (not needs_refresh)
        and (not cache_stale_by_code)
        and (not cache_stale_by_markdown)
        and (not cache_stale_by_signature)
    ):
        if md:
            export_data["markdown"] = md
        html = render_profile_html(export_data)
        write_text(html_path, html)
        config_error = try_write_runtime_map_configs(
            html_path,
            write_text=write_text,
            logger=logger,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
        )
        validation = validate_story_markdown_tool(md) if md else {"metrics": {}, "issues": []}
        return complete_generation_outcome(
            execution_context=execution_context,
            person=person,
            stage=GenerationStages.RENDER_DONE,
            checkpoint=build_generation_checkpoint(source="html_cache", resume_stage=GenerationStages.RENDER_DONE),
            success_payload={
                "ok": True,
                "person": person,
                "markdown_path": md_path if os.path.exists(md_path) else "",
                "html_path": html_path,
                "steps": [{"label": "刷新缓存", "duration": "0.00s"}],
                "duration": {"total": "0.00s"},
                "_profile": export_data,
                "cached": True,
                "refreshed": True,
            },
            steps=[{"label": "刷新缓存", "duration": "0.00s"}],
            duration={"total": "0.00s"},
            profile=export_data,
            validation=validation,
            markdown_path=md_path if os.path.exists(md_path) else "",
            html_path=html_path,
            config_error=config_error,
        )
    if md:
        profile = load_profile_from_md(
            md,
            event_callback=event_callback,
            fallback_person=person,
            allow_geocode=False,
        )
        if profile:
            profile["markdown"] = md
            html = render_profile_html(profile)
            write_text(html_path, html)
            config_error = try_write_runtime_map_configs(
                html_path,
                write_text=write_text,
                logger=logger,
                build_amap_config_js=build_amap_config_js,
                build_geovis_config_js=build_geovis_config_js,
            )
            validation = validate_story_markdown_tool(md)
            return complete_generation_outcome(
                execution_context=execution_context,
                person=person,
                stage=GenerationStages.RENDER_DONE,
                checkpoint=build_generation_checkpoint(source="markdown_file", resume_stage="markdown_saved"),
                success_payload={
                    "ok": True,
                    "person": person,
                    "markdown_path": md_path,
                    "html_path": html_path,
                    "steps": [{"label": "刷新缓存", "duration": "0.00s"}],
                    "duration": {"total": "0.00s"},
                    "_profile": profile,
                    "cached": True,
                    "refreshed": True,
                },
                steps=[{"label": "刷新缓存", "duration": "0.00s"}],
                duration={"total": "0.00s"},
                profile=profile,
                validation=validation,
                markdown_path=md_path,
                html_path=html_path,
                config_error=config_error,
            )
    return None

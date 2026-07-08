"""
============================================================================
  agent.generation_service — 单人物页生成主编排
============================================================================
  对外保持 generate_for_person(client, person, ...) 等既有 API；具体阶段逻辑
  已拆分到 agent.generation.* 子模块。
============================================================================
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional

from .generation.cache import (
    cache_older_than_dependencies as _cache_older_than_dependencies,
    extract_html_template_signature as _extract_html_template_signature,
    handle_cached_generation as _handle_cached_generation,
    is_usable_export_profile as _is_usable_export_profile,
)
from .generation.markdown import enrich_markdown_for_map, generate_markdown_with_retry
from .generation.render import build_profile_from_markdown, render_html, render_story_html
from .generation.result import (
    GenerationExecutionContext,
    build_quality_degraded_result as _build_quality_degraded_result,
    build_render_failure_result as _build_render_failure_result,
    build_runtime_config_degraded_result as _build_runtime_config_degraded_result,
    coerce_validation_dict as _coerce_validation_dict,
    complete_generation_outcome as _complete_generation_outcome,
    sync_runtime_final_validation as _sync_runtime_final_validation,
    validation_issues as _validation_issues,
)
from .generation.runtime_config import (
    public_runtime_map_configs_enabled as _public_runtime_map_configs_enabled,
    runtime_map_configs_missing as _runtime_map_configs_missing,
    try_write_runtime_map_configs as _try_write_runtime_map_configs,
    write_runtime_map_configs as _write_runtime_map_configs,
)
from .generation.validation import (
    _KNOWN_ANCIENT_PLACE_REFERENCE,
    _validate_ancient_place_coords,
    _validate_section_numbers,
    collect_quality_metrics,
    print_quality_report,
    summarize_samples,
    validate_data_quality,
)
from .generation_pipeline import (
    GenerationCheckpointStore,
    GenerationStages,
    build_generation_checkpoint as _build_checkpoint,
    decorate_generation_result as _decorate_result,
    run_generation_with_retry as _generate_markdown_with_retry,
)
from ..runtime.legacy_agent.runtime import extract_agent_runtime_metadata as _extract_agent_runtime_metadata
from ..runtime.legacy_agent.runtime import normalize_runtime_snapshot as _normalize_runtime_snapshot


def extract_agent_runtime_metadata(client: object) -> Dict[str, object]:
    return _extract_agent_runtime_metadata(client)


def normalize_runtime_snapshot(client: object) -> Dict[str, object]:
    return _normalize_runtime_snapshot(client)


def _handle_existing_markdown_generation(
    *,
    person: str,
    md_path: str,
    html_path: str,
    can_resume_from_markdown_checkpoint: bool,
    progress: Optional[callable],
    event_callback: Optional[callable],
    read_text: Callable[[str], str],
    write_text: Callable[[str, str], None],
    load_profile_from_md: Callable[..., Optional[Dict[str, object]]],
    normalize_markdown_tables: Callable[[str], str],
    geocode_markdown_tool: Callable[[str], str],
    parse_story_markdown_tool: Callable[[str], Dict[str, object]],
    validate_story_markdown_tool: Callable[[str], Dict[str, object]],
    render_html_fn: Callable[..., str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
    save_html: Callable[[str, str], str],
    format_seconds: Callable[[float], str],
    logger: object,
    build_amap_config_js: Optional[Callable[[], bytes]],
    build_geovis_config_js: Optional[Callable[[], bytes]],
    execution_context: GenerationExecutionContext,
) -> Optional[Dict[str, object]]:
    if not (os.path.exists(md_path) and ((not os.path.exists(html_path)) or can_resume_from_markdown_checkpoint)):
        return None
    t0 = time.perf_counter()
    steps: List[Dict[str, object]] = []
    md = read_text(md_path)
    resume_checkpoint_source = "checkpoint_store" if can_resume_from_markdown_checkpoint else "markdown_file"
    if not md.strip():
        return execution_context.finalize_result(_decorate_result(
            {"ok": False, "person": person, "error": "Markdown 为空，无法渲染"},
            stage=GenerationStages.BUILD_PROFILE,
            checkpoint=_build_checkpoint(source=resume_checkpoint_source, resume_stage="markdown_saved"),
        ))
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
    execution_context.record_progress(
        stage=GenerationStages.BUILD_PROFILE,
        checkpoint=_build_checkpoint(source=resume_checkpoint_source, resume_stage="markdown_saved"),
        ok=None,
    )
    if progress:
        progress(f"{person} 地图渲染")
    t_step = time.perf_counter()
    html, render_error = render_story_html(
        person=person,
        md=md_geo,
        parse_story_markdown_tool=parse_story_markdown_tool,
        render_html_fn=render_html_fn,
        render_amap_html=render_amap_html,
        logger=logger,
    )
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
    profile = build_profile_from_markdown(
        md=md_geo,
        person=person,
        event_callback=event_callback,
        load_profile_from_md=load_profile_from_md,
    )
    duration = {
        "geocode": format_seconds(t_geo),
        "render": format_seconds(t_render),
        "save": format_seconds(t_save),
        "total": format_seconds(total),
    }
    return _complete_generation_outcome(
        execution_context=execution_context,
        person=person,
        stage=GenerationStages.BUILD_PROFILE,
        checkpoint=_build_checkpoint(source=resume_checkpoint_source, resume_stage="markdown_saved"),
        success_payload={
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
        },
        steps=steps,
        duration=duration,
        profile=profile,
        validation=validation,
        markdown_path=md_path,
        html_path=out,
        used_existing_markdown=True,
        render_error=render_error,
        config_error=config_error,
    )


def _handle_fresh_generation(
    *,
    client: object,
    person: str,
    progress: Optional[callable],
    event_callback: Optional[callable],
    timeout_resolver: Optional[callable],
    write_text: Callable[[str, str], None],
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
    build_amap_config_js: Optional[Callable[[], bytes]],
    build_geovis_config_js: Optional[Callable[[], bytes]],
    execution_context: GenerationExecutionContext,
) -> Dict[str, object]:
    t0 = time.perf_counter()
    if progress:
        progress(f"{person} 生成人物档案")
    t_step = time.perf_counter()
    if client is None:
        client = get_llm_client(event_callback=event_callback, timeout_resolver=timeout_resolver)
    md, retry_count, generation_error = generate_markdown_with_retry(
        client=client,
        person=person,
        generate_historical_markdown=generate_historical_markdown,
        progress=progress,
        logger=logger,
        retry_runner=_generate_markdown_with_retry,
    )
    t_md = time.perf_counter() - t_step
    if not md:
        detail = str(generation_error.get("error") or "").strip() or "未取得内容"
        classification = str(generation_error.get("classification") or "").strip()
        if classification and classification != "unknown":
            detail = f"人物档案生成失败[{classification}]：{detail}"
        return execution_context.finalize_result(_decorate_result(
            {"ok": False, "person": person, "error": detail},
            stage=GenerationStages.MARKDOWN_GENERATION,
            retry_count=retry_count,
            checkpoint=_build_checkpoint(source="none", resume_stage="start"),
            error_info=generation_error,
        ))
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
    execution_context.record_progress(
        stage=GenerationStages.RENDERING,
        checkpoint=_build_checkpoint(source="generated_markdown", resume_stage="markdown_saved"),
        retry_count=retry_count,
        ok=None,
    )
    if progress:
        progress(f"{person} 构建时空结果")
    t_step = time.perf_counter()
    html, render_error = render_story_html(
        person=person,
        md=md,
        parse_story_markdown_tool=parse_story_markdown_tool,
        render_html_fn=render_html_fn,
        render_amap_html=render_amap_html,
        logger=logger,
    )
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
    profile = build_profile_from_markdown(
        md=md,
        person=person,
        event_callback=event_callback,
        load_profile_from_md=load_profile_from_md,
    )
    steps = [
        {"label": "生成人物档案", "duration": format_seconds(t_md)},
        {"label": "解析地点坐标", "duration": format_seconds(t_geo)},
        {"label": "构建时空结果", "duration": format_seconds(t_render)},
        {"label": "保存分析产物", "duration": format_seconds(t_save)},
    ]
    duration = {
        "markdown": format_seconds(t_md),
        "geocode": format_seconds(t_geo),
        "render": format_seconds(t_render),
        "save": format_seconds(t_save),
        "total": format_seconds(total),
    }
    return _complete_generation_outcome(
        execution_context=execution_context,
        person=person,
        stage=GenerationStages.DONE,
        checkpoint=_build_checkpoint(source="generated_markdown", resume_stage="markdown_saved"),
        retry_count=retry_count,
        success_payload={
            "ok": True,
            "status": "ok",
            "degraded": False,
            "person": person,
            "markdown_path": saved,
            "html_path": out,
            "steps": steps,
            "duration": duration,
            "_profile": profile,
            "_validation": validation,
            "_agent_runtime": agent_runtime,
            "cached": False,
        },
        steps=steps,
        duration=duration,
        profile=profile,
        validation=validation,
        markdown_path=saved,
        html_path=out,
        agent_runtime=agent_runtime,
        render_error=render_error,
        config_error=config_error,
    )


def generate_for_person(
    client: object,
    person: str,
    *,
    progress: Optional[callable] = None,
    allow_cache: bool = True,
    event_callback: Optional[callable] = None,
    timeout_resolver: Optional[callable] = None,
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
    checkpoint_store: Optional[GenerationCheckpointStore] = None,
) -> Dict[str, object]:
    md_path, html_path = story_paths(person)
    stored_checkpoint = checkpoint_store.load(person) if checkpoint_store else {}
    stored_checkpoint_data = dict(stored_checkpoint.get("checkpoint") or {}) if isinstance(stored_checkpoint, dict) else {}
    can_resume_from_markdown_checkpoint = (
        bool(stored_checkpoint_data)
        and str(stored_checkpoint_data.get("resume_stage") or "").strip() == "markdown_saved"
        and os.path.exists(md_path)
        and (not os.path.exists(html_path))
    )
    execution_context = GenerationExecutionContext(person=person, checkpoint_store=checkpoint_store)
    execution_context.record_progress(
        stage=GenerationStages.START,
        checkpoint=_build_checkpoint(source="request", resume_stage=GenerationStages.START),
        ok=None,
    )
    if allow_cache:
        cached_result = _handle_cached_generation(
            person=person,
            md_path=md_path,
            html_path=html_path,
            event_callback=event_callback,
            cache_dependency_paths=cache_dependency_paths,
            current_profile_signature=current_profile_signature,
            read_text=read_text,
            extract_export_data_from_html=extract_export_data_from_html,
            write_text=write_text,
            render_profile_html=render_profile_html,
            load_profile_from_md=load_profile_from_md,
            validate_story_markdown_tool=validate_story_markdown_tool,
            logger=logger,
            build_amap_config_js=build_amap_config_js,
            build_geovis_config_js=build_geovis_config_js,
            execution_context=execution_context,
        )
        if cached_result is not None:
            return cached_result
    existing_markdown_result = _handle_existing_markdown_generation(
        person=person,
        md_path=md_path,
        html_path=html_path,
        can_resume_from_markdown_checkpoint=can_resume_from_markdown_checkpoint,
        progress=progress,
        event_callback=event_callback,
        read_text=read_text,
        write_text=write_text,
        load_profile_from_md=load_profile_from_md,
        normalize_markdown_tables=normalize_markdown_tables,
        geocode_markdown_tool=geocode_markdown_tool,
        parse_story_markdown_tool=parse_story_markdown_tool,
        validate_story_markdown_tool=validate_story_markdown_tool,
        render_html_fn=render_html_fn,
        render_amap_html=render_amap_html,
        save_html=save_html,
        format_seconds=format_seconds,
        logger=logger,
        build_amap_config_js=build_amap_config_js,
        build_geovis_config_js=build_geovis_config_js,
        execution_context=execution_context,
    )
    if existing_markdown_result is not None:
        return existing_markdown_result
    return _handle_fresh_generation(
        client=client,
        person=person,
        progress=progress,
        event_callback=event_callback,
        timeout_resolver=timeout_resolver,
        write_text=write_text,
        load_profile_from_md=load_profile_from_md,
        normalize_markdown_tables=normalize_markdown_tables,
        compute_total_distance_km=compute_total_distance_km,
        insert_distance_intro=insert_distance_intro,
        save_markdown=save_markdown,
        geocode_markdown_tool=geocode_markdown_tool,
        parse_story_markdown_tool=parse_story_markdown_tool,
        validate_story_markdown_tool=validate_story_markdown_tool,
        render_html_fn=render_html_fn,
        render_amap_html=render_amap_html,
        save_html=save_html,
        format_seconds=format_seconds,
        get_llm_client=get_llm_client,
        generate_historical_markdown=generate_historical_markdown,
        logger=logger,
        build_amap_config_js=build_amap_config_js,
        build_geovis_config_js=build_geovis_config_js,
        execution_context=execution_context,
    )

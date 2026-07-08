from __future__ import annotations

from typing import Dict, List, Optional

from ..generation_pipeline import GenerationCheckpointStore
from ..generation_pipeline import decorate_generation_result as decorate_result


def coerce_validation_dict(validation: object) -> Dict[str, object]:
    if not isinstance(validation, dict):
        return {}
    return dict(validation)


def sync_runtime_final_validation(
    agent_runtime: Optional[Dict[str, object]],
    validation: object,
) -> Optional[Dict[str, object]]:
    if not isinstance(agent_runtime, dict) or not agent_runtime:
        return agent_runtime
    runtime = dict(agent_runtime)
    state = dict(runtime.get("state") or {})
    final_validation = coerce_validation_dict(validation)
    if final_validation:
        state["validation"] = final_validation
        state["validation_stage"] = "final_output"
    runtime["state"] = state
    return runtime


def validation_issues(validation: object) -> List[str]:
    if not isinstance(validation, dict):
        return []
    return [str(item) for item in list(validation.get("issues") or []) if str(item).strip()]


def build_render_failure_result(
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


def build_quality_degraded_result(
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
    issues = validation_issues(validation)
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


def build_runtime_config_degraded_result(
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
    quality_issues = validation_issues(validation)
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
        "warnings": [summary] + quality_issues,
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


class GenerationExecutionContext:
    def __init__(self, *, person: str, checkpoint_store: Optional[GenerationCheckpointStore] = None):
        self.person = person
        self.checkpoint_store = checkpoint_store

    def record_progress(
        self,
        *,
        stage: str,
        checkpoint: Optional[Dict[str, object]] = None,
        retry_count: int = 0,
        error_info: Optional[Dict[str, object]] = None,
        ok: Optional[bool] = None,
    ) -> None:
        if not self.checkpoint_store:
            return
        self.checkpoint_store.save(
            self.person,
            stage=stage,
            checkpoint=checkpoint,
            retry_count=retry_count,
            error_info=error_info,
            ok=ok,
        )

    def finalize_result(self, result: Dict[str, object]) -> Dict[str, object]:
        if self.checkpoint_store and isinstance(result, dict):
            self.record_progress(
                stage=str(result.get("stage") or "").strip(),
                checkpoint=dict(result.get("checkpoint") or {}) if isinstance(result.get("checkpoint"), dict) else None,
                retry_count=int(result.get("retry_count") or 0),
                error_info={
                    "classification": str(result.get("error_classification") or "").strip(),
                    "retryable": bool(result.get("error_retryable")),
                    "error": str(result.get("error") or "").strip(),
                },
                ok=bool(result.get("ok")),
            )
        return result


def complete_generation_outcome(
    *,
    execution_context: GenerationExecutionContext,
    person: str,
    stage: str,
    checkpoint: Dict[str, object],
    retry_count: int = 0,
    success_payload: Dict[str, object],
    steps: List[Dict[str, object]],
    duration: Dict[str, str],
    profile: object,
    validation: object,
    markdown_path: str = "",
    html_path: str = "",
    used_existing_markdown: bool = False,
    agent_runtime: Optional[Dict[str, object]] = None,
    render_error: str = "",
    config_error: str = "",
) -> Dict[str, object]:
    if render_error:
        return execution_context.finalize_result(decorate_result(
            build_render_failure_result(
                person=person,
                render_error=render_error,
                fallback_html_path=html_path,
                markdown_path=markdown_path,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                agent_runtime=agent_runtime,
                used_existing_markdown=used_existing_markdown,
            ),
            stage=stage,
            retry_count=retry_count,
            checkpoint=checkpoint,
        ))
    if config_error:
        return execution_context.finalize_result(decorate_result(
            build_runtime_config_degraded_result(
                person=person,
                html_path=html_path,
                markdown_path=markdown_path,
                config_error=config_error,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                cached=bool(success_payload.get("cached")),
                refreshed=bool(success_payload.get("refreshed")),
                used_existing_markdown=used_existing_markdown,
                agent_runtime=agent_runtime,
            ),
            stage=stage,
            retry_count=retry_count,
            checkpoint=checkpoint,
        ))
    if validation_issues(validation):
        return execution_context.finalize_result(decorate_result(
            build_quality_degraded_result(
                person=person,
                html_path=html_path,
                markdown_path=markdown_path,
                steps=steps,
                duration=duration,
                profile=profile,
                validation=validation,
                cached=bool(success_payload.get("cached")),
                refreshed=bool(success_payload.get("refreshed")),
                used_existing_markdown=used_existing_markdown,
                agent_runtime=agent_runtime,
            ),
            stage=stage,
            retry_count=retry_count,
            checkpoint=checkpoint,
        ))
    return execution_context.finalize_result(decorate_result(
        success_payload,
        stage=stage,
        retry_count=retry_count,
        checkpoint=checkpoint,
    ))

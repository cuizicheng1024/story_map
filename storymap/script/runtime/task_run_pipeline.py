from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from .task_result_compiler import compile_task_outcome, resolve_terminal_task_outcome


def is_usable_result(result: Dict[str, object]) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


@dataclass(frozen=True)
class TaskRunArtifacts:
    results: List[Dict[str, object]]
    people_payload: List[Dict[str, object]]
    overlaps: List[Dict[str, object]]
    multi_html_path: str
    multi_exports: Dict[str, str]


class TaskRunPipeline:
    def __init__(
        self,
        *,
        color_palette: Sequence[str],
        format_seconds: Callable[[float], str],
        generate_for_person: Callable[..., Dict[str, object]],
        ensure_profile_exports: Callable[..., Dict[str, str]],
        ensure_multi_exports: Callable[..., Dict[str, str]],
        compute_overlaps: Callable[[List[Dict[str, object]]], List[Dict[str, object]]],
        build_conclusion: Callable[[List[Dict[str, object]], bool], str],
        render_multi_html: Callable[[Dict[str, object]], str],
        save_html: Callable[[str, str], str],
        relative_path: Callable[[str], str],
        collect_result_runtime_meta: Callable[[List[Dict[str, object]]], Dict[str, object]],
    ) -> None:
        self._color_palette = tuple(color_palette)
        self._format_seconds = format_seconds
        self._generate_for_person = generate_for_person
        self._ensure_profile_exports = ensure_profile_exports
        self._ensure_multi_exports = ensure_multi_exports
        self._compute_overlaps = compute_overlaps
        self._build_conclusion = build_conclusion
        self._render_multi_html = render_multi_html
        self._save_html = save_html
        self._relative_path = relative_path
        self._collect_result_runtime_meta = collect_result_runtime_meta

    def build_generation_artifacts(
        self,
        *,
        task_id: str,
        client: object,
        targets: List[str],
        blocked_results: List[Dict[str, object]],
        allow_cache: bool,
        ensure_can_continue: Callable[[], None],
        append_progress: Callable[[str, str], None],
        llm_event: Callable[[str], None],
        timeout_seconds: Callable[[], int],
    ) -> TaskRunArtifacts:
        generated_results: List[Dict[str, object]] = []
        people_payload: List[Dict[str, object]] = []
        for idx, person in enumerate(targets):
            def _progress(message: str) -> None:
                ensure_can_continue()
                append_progress(str(message or "").strip(), "")

            ensure_can_continue()
            result = self._generate_for_person(
                client,
                person,
                progress=_progress,
                allow_cache=allow_cache,
                event_callback=llm_event,
                timeout_resolver=timeout_seconds,
                refresh_homepage=False,
            )
            generated_results.append(result)
            if is_usable_result(result) and result.get("_profile"):
                ensure_can_continue()
                profile = result.get("_profile") or {}
                export_allow_cache = allow_cache and (not bool(result.get("refreshed")))
                people_payload.append(
                    {
                        "person": profile.get("person", {}),
                        "locations": profile.get("locations", []),
                        "mapStyle": profile.get("mapStyle", {}),
                        "color": self._color_palette[idx % len(self._color_palette)],
                    }
                )
                result["exports"] = self._ensure_profile_exports(profile, person, allow_cache=export_allow_cache)
        results = list(blocked_results)
        results.extend(generated_results)
        overlaps = self._compute_overlaps(people_payload) if len(people_payload) > 1 else []
        multi_html_path = ""
        multi_exports: Dict[str, str] = {}
        if len(people_payload) > 1:
            ensure_can_continue()
            append_progress("生成合并视图", "")
            title = "多人物合并视图"
            multi_data = {"title": title, "people": people_payload, "overlaps": overlaps}
            multi_html = self._render_multi_html(multi_data)
            multi_name = f"{title}_{task_id[:8]}"
            multi_html_path = self._save_html(multi_name, multi_html)
            multi_exports = self._ensure_multi_exports(people_payload, multi_name, allow_cache=allow_cache)
        return TaskRunArtifacts(
            results=results,
            people_payload=people_payload,
            overlaps=overlaps,
            multi_html_path=multi_html_path,
            multi_exports=multi_exports,
        )

    def build_outcome(
        self,
        *,
        resolved_targets: List[str],
        artifacts: TaskRunArtifacts,
        started_at: float,
    ):
        duration = self._format_seconds(time.perf_counter() - started_at)
        conclusion = self._build_conclusion(artifacts.results, len(artifacts.people_payload) > 1)
        outcome = compile_task_outcome(
            resolved_targets=resolved_targets,
            results=artifacts.results,
            overlaps=artifacts.overlaps,
            duration=duration,
            conclusion=conclusion,
            multi_html_path=artifacts.multi_html_path,
            multi_exports=artifacts.multi_exports,
            relative_path=self._relative_path,
            meta=self._collect_result_runtime_meta(artifacts.results),
        )
        return duration, outcome, resolve_terminal_task_outcome(outcome)

    def apply_terminal_resolution(
        self,
        *,
        task_id: str,
        summary: Dict[str, object],
        successful_people: List[str],
        terminal_resolution: object,
        duration: str,
        duration_seconds: float,
        refresh_stellar_homepage: object,
        update_task: Callable[..., None],
        enqueue_archive_refresh: Callable[[str, List[str]], None],
        append_progress: Callable[[str, str], None],
        record_metrics: Callable[..., None],
        logger: object,
    ) -> None:
        if successful_people and callable(refresh_stellar_homepage):
            summary["archive"] = {
                "state": "queued",
                "label": "排队中",
                "people": successful_people,
                "visible": False,
            }
        append_progress("输出结论", "")
        if str(terminal_resolution.status) == "failed":
            update_task(task_id, status="failed", error=terminal_resolution.error_message, result=summary)
            append_progress(terminal_resolution.progress_label, terminal_resolution.error_message)
            append_progress("完成", terminal_resolution.completion_label)
            record_metrics(failed=1, duration_seconds_total=duration_seconds)
            logger.warning("task_failed id=%s error=%s", task_id, terminal_resolution.error_message)
            return
        if str(terminal_resolution.status) == "partial_failed":
            update_task(task_id, status="partial_failed", error=terminal_resolution.error_message, result=summary)
            enqueue_archive_refresh(task_id, successful_people)
            append_progress(terminal_resolution.progress_label, terminal_resolution.error_message)
            append_progress("完成", terminal_resolution.completion_label)
            record_metrics(partial_failed=1, duration_seconds_total=duration_seconds)
            logger.warning("task_partial_failed id=%s error=%s", task_id, terminal_resolution.error_message)
            return
        update_task(task_id, status="completed", result=summary)
        enqueue_archive_refresh(task_id, successful_people)
        record_metrics(completed=1, duration_seconds_total=duration_seconds)
        logger.info("task_completed id=%s duration=%s", task_id, duration)

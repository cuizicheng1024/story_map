from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ..core.public_url import public_url
from .task_schema import TaskFileEntry, TaskMultiEntry, TaskResultSummary, build_task_result_summary


def _is_usable_result(result: Dict[str, object]) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


def _has_task_blocking_failure(result: Dict[str, object]) -> bool:
    return bool(result.get("homepage_refresh_failed"))


def _extract_error_messages(results: List[Dict[str, object]]) -> List[str]:
    messages: List[str] = []
    for result in results:
        message = str(result.get("error") or "").strip()
        if message and message not in messages:
            messages.append(message)
    return messages


@dataclass(frozen=True)
class CompiledTaskOutcome:
    summary_status: str
    summary: TaskResultSummary
    success_results: List[Dict[str, object]]
    failed_results: List[Dict[str, object]]
    failed_people: List[str]
    successful_people: List[str]


@dataclass(frozen=True)
class TerminalTaskResolution:
    status: str
    error_message: str
    progress_label: str
    completion_label: str
    metric_key: str
    log_method: str


def compile_task_outcome(
    *,
    resolved_targets: List[str],
    results: List[Dict[str, object]],
    overlaps: List[Dict[str, object]],
    duration: str,
    conclusion: str,
    multi_html_path: str,
    multi_exports: Dict[str, str],
    relative_path: Callable[[str], str],
    meta: object,
) -> CompiledTaskOutcome:
    success_results = [result for result in results if _is_usable_result(result) and not _has_task_blocking_failure(result)]
    failed_results = [result for result in results if (not _is_usable_result(result)) or _has_task_blocking_failure(result)]
    failed_people = [str(item.get("person") or "").strip() for item in failed_results if str(item.get("person") or "").strip()]
    if success_results and failed_results:
        summary_status = "partial_failed"
    elif success_results:
        summary_status = "completed"
    else:
        summary_status = "failed"

    files: List[TaskFileEntry] = []
    for result in results:
        if not _is_usable_result(result):
            continue
        file_entry: TaskFileEntry = {
            "markdown": relative_path(result.get("markdown_path", "")),
            "html": relative_path(result.get("html_path", "")),
        }
        html_public_url = public_url(file_entry.get("html", ""))
        if html_public_url:
            file_entry["public_html"] = html_public_url
        exports = result.get("exports") or {}
        if exports.get("geojson"):
            file_entry["geojson"] = relative_path(exports.get("geojson", ""))
            geojson_public_url = public_url(file_entry.get("geojson", ""))
            if geojson_public_url:
                file_entry["public_geojson"] = geojson_public_url
        if exports.get("csv"):
            file_entry["csv"] = relative_path(exports.get("csv", ""))
            csv_public_url = public_url(file_entry.get("csv", ""))
            if csv_public_url:
                file_entry["public_csv"] = csv_public_url
        files.append(file_entry)

    multi_entry: Optional[TaskMultiEntry] = None
    if multi_html_path:
        multi_entry = {
            "html": relative_path(multi_html_path),
            "geojson": relative_path(multi_exports.get("geojson", "")) if multi_exports else "",
            "csv": relative_path(multi_exports.get("csv", "")) if multi_exports else "",
        }
        multi_public_html = public_url(multi_entry.get("html", ""))
        if multi_public_html:
            multi_entry["public_html"] = multi_public_html
        multi_public_geojson = public_url(multi_entry.get("geojson", ""))
        if multi_public_geojson:
            multi_entry["public_geojson"] = multi_public_geojson
        multi_public_csv = public_url(multi_entry.get("csv", ""))
        if multi_public_csv:
            multi_entry["public_csv"] = multi_public_csv

    summary: TaskResultSummary = build_task_result_summary(
        ok=(summary_status == "completed"),
        status=summary_status,
        people=resolved_targets,
        results=results,
        success_count=len(success_results),
        failed_count=len(failed_results),
        failed_people=failed_people,
        multi_html_path=multi_html_path,
        multi_exports=multi_exports,
        overlaps=overlaps,
        duration=duration,
        conclusion=conclusion,
        files=files,
        meta=meta,
        multi=multi_entry,
    )
    successful_people = [
        str(item.get("person") or "").strip()
        for item in success_results
        if str(item.get("person") or "").strip()
    ]
    return CompiledTaskOutcome(
        summary_status=summary_status,
        summary=summary,
        success_results=success_results,
        failed_results=failed_results,
        failed_people=failed_people,
        successful_people=successful_people,
    )


def resolve_terminal_task_outcome(outcome: CompiledTaskOutcome) -> TerminalTaskResolution:
    if outcome.summary_status == "failed":
        messages = _extract_error_messages(outcome.summary.get("results") or [])
        return TerminalTaskResolution(
            status="failed",
            error_message="；".join(messages[:3]) or "未生成成功",
            progress_label="失败",
            completion_label="失败",
            metric_key="failed",
            log_method="warning",
        )
    if outcome.summary_status == "partial_failed":
        messages = _extract_error_messages(outcome.failed_results)
        fallback = f"部分人物生成失败：{'、'.join(outcome.failed_people[:3])}" if outcome.failed_people else "部分人物生成失败"
        return TerminalTaskResolution(
            status="partial_failed",
            error_message="；".join(messages[:3]) or fallback,
            progress_label="部分失败",
            completion_label="部分失败",
            metric_key="partial_failed",
            log_method="warning",
        )
    return TerminalTaskResolution(
        status="completed",
        error_message="",
        progress_label="完成",
        completion_label="完成",
        metric_key="completed",
        log_method="info",
    )


__all__ = [
    "CompiledTaskOutcome",
    "TerminalTaskResolution",
    "compile_task_outcome",
    "resolve_terminal_task_outcome",
]

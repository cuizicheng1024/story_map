from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple


class GenerationStages:
    START = "start"
    MARKDOWN_GENERATION = "markdown_generation"
    BUILD_PROFILE = "build_profile"
    RENDERING = "rendering"
    RENDER_DONE = "render_done"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class GenerationCheckpoint:
    source: str
    resume_stage: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "source": str(self.source or "").strip(),
            "resume_stage": str(self.resume_stage or "").strip(),
        }


@dataclass(frozen=True)
class GenerationFailureInfo:
    classification: str = ""
    retryable: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "classification": str(self.classification or "").strip(),
            "retryable": bool(self.retryable),
            "error": str(self.error or "").strip(),
        }


@dataclass(frozen=True)
class GenerationRetryPolicy:
    max_attempts: int = 2

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = "MAP_STORY_GENERATE_MARKDOWN_ATTEMPTS",
        default_attempts: int = 2,
    ) -> "GenerationRetryPolicy":
        raw = str(os.getenv(env_var, str(default_attempts)) or str(default_attempts)).strip()
        try:
            parsed = int(raw)
        except Exception:
            parsed = default_attempts
        return cls(max_attempts=max(1, parsed))


class GenerationCheckpointStore(Protocol):
    def load(self, person: str) -> Dict[str, object]:
        ...

    def save(
        self,
        person: str,
        *,
        requested_person: str = "",
        stage: str = "",
        checkpoint: Optional[Dict[str, object]] = None,
        retry_count: int = 0,
        error_info: Optional[Dict[str, object]] = None,
        ok: Optional[bool] = None,
    ) -> Dict[str, object]:
        ...

    def clear(self, person: str) -> None:
        ...


class FileGenerationCheckpointStore:
    def __init__(self, file_path: Optional[str] = None):
        self.file_path = Path(file_path) if file_path else _default_checkpoint_store_path()
        self._lock = threading.Lock()

    def load(self, person: str) -> Dict[str, object]:
        key = str(person or "").strip()
        if not key:
            return {}
        payload = self._read_payload()
        item = payload.get(key)
        return dict(item) if isinstance(item, dict) else {}

    def save(
        self,
        person: str,
        *,
        requested_person: str = "",
        stage: str = "",
        checkpoint: Optional[Dict[str, object]] = None,
        retry_count: int = 0,
        error_info: Optional[Dict[str, object]] = None,
        ok: Optional[bool] = None,
    ) -> Dict[str, object]:
        key = str(person or "").strip()
        if not key:
            return {}
        item: Dict[str, object] = {
            "person": key,
            "requested_person": str(requested_person or key).strip(),
            "stage": str(stage or "").strip(),
            "retry_count": max(0, int(retry_count or 0)),
            "updated_at": time.time(),
        }
        if checkpoint:
            item["checkpoint"] = dict(checkpoint)
        if error_info:
            normalized_error = dict(error_info)
            classification = str(normalized_error.get("classification") or "").strip()
            if classification:
                item["error_classification"] = classification
            if "retryable" in normalized_error:
                item["error_retryable"] = bool(normalized_error.get("retryable"))
            message = str(normalized_error.get("error") or "").strip()
            if message:
                item["error"] = message
        if ok is not None:
            item["ok"] = bool(ok)
        with self._lock:
            payload = self._read_payload()
            payload[key] = item
            self._write_payload(payload)
        return item

    def clear(self, person: str) -> None:
        key = str(person or "").strip()
        if not key:
            return
        with self._lock:
            payload = self._read_payload()
            if key not in payload:
                return
            payload.pop(key, None)
            self._write_payload(payload)

    def _read_payload(self) -> Dict[str, Dict[str, object]]:
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, Dict[str, object]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                out[str(key)] = dict(value)
        return out

    def _write_payload(self, payload: Dict[str, Dict[str, object]]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_checkpoint_store_path() -> Path:
    env_path = str(os.getenv("MAP_STORY_GENERATION_CHECKPOINT_JSON", "") or "").strip()
    if env_path:
        return Path(env_path)
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "data" / "runtime" / "generation_checkpoints.json"


def build_generation_checkpoint(*, source: str, resume_stage: str) -> Dict[str, str]:
    return GenerationCheckpoint(source=source, resume_stage=resume_stage).to_dict()


def decorate_generation_result(
    result: Dict[str, object],
    *,
    stage: str,
    retry_count: int = 0,
    checkpoint: Optional[Dict[str, object]] = None,
    error_info: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload = dict(result or {})
    payload["stage"] = str(stage or "").strip()
    payload["retry_count"] = max(0, int(retry_count or 0))
    if checkpoint:
        payload["checkpoint"] = dict(checkpoint)
    if error_info:
        normalized_error = GenerationFailureInfo(
            classification=str(error_info.get("classification") or "").strip(),
            retryable=bool(error_info.get("retryable")),
            error=str(error_info.get("error") or "").strip(),
        ).to_dict()
        if normalized_error["classification"]:
            payload["error_classification"] = normalized_error["classification"]
        payload["error_retryable"] = bool(normalized_error["retryable"])
        if normalized_error["error"]:
            payload.setdefault("error", normalized_error["error"])
    return payload


def extract_generation_failure_info(client: object, error: Optional[Exception] = None) -> Dict[str, object]:
    trace: Dict[str, object] = {}
    latest_trace = getattr(client, "latest_trace", None)
    if callable(latest_trace):
        try:
            raw = latest_trace() or {}
            if isinstance(raw, dict):
                trace = dict(raw)
        except Exception:
            trace = {}
    failure = GenerationFailureInfo(
        classification=str(trace.get("classification") or getattr(error, "classification", "") or "unknown").strip() or "unknown",
        retryable=bool(trace.get("retryable")) if "retryable" in trace else bool(getattr(error, "retryable", False)),
        error=str(trace.get("error") or error or "").strip(),
    )
    if not failure.error and failure.classification == "negative_cache":
        failure = GenerationFailureInfo(
            classification=failure.classification,
            retryable=failure.retryable,
            error="命中失败缓存，请稍后重试",
        )
    return failure.to_dict()


def run_generation_with_retry(
    *,
    client: object,
    person: str,
    generate_historical_markdown,
    progress,
    logger: object,
    retry_policy: Optional[GenerationRetryPolicy] = None,
) -> Tuple[str, int, Dict[str, object]]:
    policy = retry_policy or GenerationRetryPolicy.from_env()
    retry_count = 0
    last_error: Dict[str, object] = {}
    for attempt in range(1, policy.max_attempts + 1):
        if attempt > 1 and progress:
            progress(f"{person} 生成人物档案重试（{attempt}/{policy.max_attempts}）")
        try:
            markdown = generate_historical_markdown(client, person)
        except Exception as exc:
            markdown = ""
            last_error = extract_generation_failure_info(client, exc)
        else:
            last_error = {} if markdown else extract_generation_failure_info(client)
        if markdown:
            return markdown, retry_count, {}
        if attempt >= policy.max_attempts or not last_error.get("retryable"):
            return "", retry_count, last_error
        retry_count += 1
        if progress:
            progress(f"{person} 首轮生成未完成，准备自动重试")
        logger.warning(
            "generate_markdown_retry person=%s attempt=%s classification=%s error=%s",
            person,
            attempt,
            str(last_error.get("classification") or "unknown"),
            str(last_error.get("error") or "empty_result"),
        )
    return "", retry_count, last_error


__all__ = [
    "FileGenerationCheckpointStore",
    "GenerationCheckpoint",
    "GenerationCheckpointStore",
    "GenerationFailureInfo",
    "GenerationRetryPolicy",
    "GenerationStages",
    "build_generation_checkpoint",
    "decorate_generation_result",
    "extract_generation_failure_info",
    "run_generation_with_retry",
]

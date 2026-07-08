"""
============================================================================
  agent.generation_pipeline — 生成阶段、断点续传与失败重试
============================================================================
  本模块负责把 "生成一份人物页" 切成若干阶段 (GenerationStages)，
  并提供两类持久化能力：
    1. GenerationCheckpointStore —— 把当前人物已到达的阶段写盘，下次可以 resume
    2. run_generation_with_retry —— 自动按 GenerationRetryPolicy 重新生成 markdown

  阶段定义（顺序）
    start → markdown_generation → build_profile → rendering → render_done → done
                                                          ↘ failed

----------------------------------------------------------------------------
  一、Tool / Memory Plan（工具与记忆计划）
----------------------------------------------------------------------------
  本模块不直接调用 LLM，仅暴露：
    - GenerationStages               : 字符串常量集，给上层 UI / 日志展示阶段
    - GenerationCheckpoint           : 不可变 dataclass，描述 "从哪里来、可以续到哪里"
    - GenerationFailureInfo          : 失败的分类 / 是否可重试 / 错误文案
    - GenerationRetryPolicy          : 最多重试次数（默认 2，受环境变量调节）
    - FileGenerationCheckpointStore  : 基于 JSON 文件的实现，支持线程锁
    - Protocol: GenerationCheckpointStore  : 上层可注入自定义后端（DB、Redis 等）
    - build_generation_checkpoint    : 快速构造 checkpoint 字典
    - decorate_generation_result     : 把 stage/retry/checkpoint/error_info 注入 result
    - extract_generation_failure_info: 从 LLM client.latest_trace 抽取分类信息
    - run_generation_with_retry      : 调度重试循环

  记忆写入位置（默认）
    - <repo_root>/data/runtime/generation_checkpoints.json
    - 可由 MAP_STORY_GENERATION_CHECKPOINT_JSON 环境变量覆盖
  重试次数
    - 由 MAP_STORY_GENERATE_MARKDOWN_ATTEMPTS 控制，默认 2

----------------------------------------------------------------------------
  二、PDCA 循环（计划 / 执行 / 检查 / 处理）
----------------------------------------------------------------------------
  Plan
    - 调用方需先确定：markdown 是否已存在？HTML 是否已存在？是否有 checkpoint？
      这三条决定了 generation_service 走 缓存 / 复用 / 全量 三条路径中的哪一条
    - 调 GenerationRetryPolicy.from_env() 而非直接实例化，以便响应环境变量
  Do
    - FileGenerationCheckpointStore.save() 在生成过程中被频繁调用 (每个阶段)
    - run_generation_with_retry 在 markdown 生成失败且分类为 retryable 时自循环
  Check
    - run_generation_with_retry 返回值是三元组 (markdown, retry_count, error_info)
      任意一个为空都表示失败，必须读 error_info.classification 才能定位根因
    - 失败分类为 "negative_cache"（命中失败缓存）属于 "不可立即重试"，
      run_generation_with_retry 已经写入 "命中失败缓存，请稍后重试" 文案
  Act
    - 当新增 "失败但可恢复" 的错误类型时，更新 GenerationFailureInfo 的 to_dict()，
      并在 run_generation_with_retry 的 "retryable" 判定中显式列出新分类

----------------------------------------------------------------------------
  三、5M1E 分析（人 / 机 / 料 / 法 / 测 / 环）
----------------------------------------------------------------------------
  Man(人)        : 维护者修改本文件前必须明确 GenerationStages 的顺序语义
                   (resume_stage == "markdown_saved" 是关键判据)
  Machine(机)   : 需要文件系统能原子写 (write_text 会 truncate + write)；
                   在 NFS / 网络盘上可能产生损坏 — 高并发场景建议替换为 DB 后端
  Material(料)  : checkpoint JSON 文件可能存在敏感人物名；写入时已 ensure_ascii=False
                   保留中文，不要误改
  Method(法)    : 复用 dataclass(frozen=True) 保证不可变；Protocol 允许注入
                   不同后端，但所有实现必须自己处理并发锁
  Measurement(测): 没有指标面板；监控请在调用方读取 result["stage"] / result["retry_count"]
  Environment(环): 线程安全 — FileGenerationCheckpointStore 内置 self._lock；
                   跨进程不安全（多个 Python 进程同时写同一 JSON 文件会丢失更新）
============================================================================
"""

from __future__ import annotations

import json
import os
import time
import threading
import uuid
from dataclasses import dataclass
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
        # Atomic write via temporary file to prevent checkpoint corruption if the
        # process crashes mid-write (e.g. OOM, SIGKILL, power loss).
        tmp_path = self.file_path.with_name(f"{self.file_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.file_path)


def _default_checkpoint_store_path() -> Path:
    env_path = str(os.getenv("MAP_STORY_GENERATION_CHECKPOINT_JSON", "") or "").strip()
    if env_path:
        return Path(env_path)
    repo_root = Path(__file__).resolve().parents[3]
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
    # Fallback: classify empty-markdown / network flake as retryable
    classification = str(trace.get("classification") or getattr(error, "classification", "") or "").strip()
    if not classification:
        err_msg = str(trace.get("error") or error or "").strip()
        if not err_msg or "empty" in err_msg.lower():
            classification = "empty_response"
    if not classification:
        classification = "unknown"
    failure = GenerationFailureInfo(
        classification=classification,
        retryable=bool(trace.get("retryable"))
            if "retryable" in trace
            else (
                bool(getattr(error, "retryable", False))
                or classification in {"empty_response", "timeout", "rate_limited", "network_error"}
            ),
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

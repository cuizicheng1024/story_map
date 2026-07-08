from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, TypeVar, cast


F = TypeVar("F", bound=Callable[..., object])

# Reusable executor pool for invoke_tool timeouts. Creating/destroying a
# ThreadPoolExecutor per invocation adds avoidable overhead.
_tool_executor_lock = threading.Lock()
_tool_executor: Optional[ThreadPoolExecutor] = None


def _get_tool_executor() -> ThreadPoolExecutor:
    global _tool_executor
    with _tool_executor_lock:
        if _tool_executor is None:
            _tool_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-")
        return _tool_executor


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, object] = field(default_factory=dict)
    output_schema: Dict[str, object] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    retry_count: int = 0
    cost_tier: str = "low"
    permission: str = "read"
    tags: tuple[str, ...] = ()


@dataclass
class ToolTrace:
    tool_name: str
    agent_step: str
    success: bool
    attempt: int
    duration_ms: int
    timed_out: bool = False
    error: str = ""
    permission: str = ""
    cost_tier: str = ""
    input_summary: str = ""
    output_summary: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _preview_value(value: object, limit: int = 180) -> str:
    text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _check_type(value: object, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def validate_schema(value: object, schema: Optional[Dict[str, object]], *, path: str = "$") -> List[str]:
    if not schema:
        return []
    errors: List[str] = []
    expected_type = str(schema.get("type") or "").strip()
    if expected_type and not _check_type(value, expected_type):
        return [f"{path} 应为 {expected_type}"]
    if expected_type == "object":
        assert isinstance(value, dict)  # narrow for type-checkers
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        if isinstance(required, list):
            for key in required:
                if str(key) not in value:
                    errors.append(f"{path}.{key} 缺失")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                key_str = str(key)
                if key_str not in value or not isinstance(child_schema, dict):
                    continue
                errors.extend(validate_schema(value[key_str], child_schema, path=f"{path}.{key_str}"))
    if expected_type == "array":
        assert isinstance(value, list)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                errors.extend(validate_schema(item, item_schema, path=f"{path}[{idx}]"))
    return errors


def invoke_tool(
    func: Callable[..., object],
    *args: object,
    trace_collector: Optional[List[Dict[str, object]]] = None,
    agent_step: str = "",
    **kwargs: object,
) -> object:
    spec = getattr(func, "__tool__", None)
    if spec is None:
        return func(*args, **kwargs)
    # ── Schema 校验仅针对位置参数，extra kwargs（如 dynasty）绕过校验 ──
    input_payload: object
    if len(args) == 1 and not kwargs:
        input_payload = args[0]
    elif len(args) == 1:
        input_payload = args[0]  # extra kwargs 不参与 schema 校验
    else:
        input_payload = {"args": list(args), "kwargs": dict(kwargs)}
    input_errors = validate_schema(input_payload, spec.input_schema, path="$input")
    if input_errors:
        raise ValueError(f"{spec.name} 输入不符合 schema: {'; '.join(input_errors)}")
    attempts = max(1, int(spec.retry_count) + 1)
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        timed_out = False
        try:
            executor = _get_tool_executor()
            future = executor.submit(func, *args, **kwargs)
            try:
                result = future.result(timeout=max(0.001, float(spec.timeout_seconds)))
            except Exception:
                future.cancel()
                raise
            output_errors = validate_schema(result, spec.output_schema, path="$output")
            if output_errors:
                raise ValueError(f"{spec.name} 输出不符合 schema: {'; '.join(output_errors)}")
            duration_ms = int((time.perf_counter() - started) * 1000)
            if trace_collector is not None:
                trace_collector.append(
                    ToolTrace(
                        tool_name=spec.name,
                        agent_step=str(agent_step or "").strip(),
                        success=True,
                        attempt=attempt,
                        duration_ms=duration_ms,
                        permission=spec.permission,
                        cost_tier=spec.cost_tier,
                        input_summary=_preview_value(input_payload),
                        output_summary=_preview_value(result),
                    ).to_dict()
                )
            return result
        except FutureTimeoutError:
            timed_out = True
            last_error = TimeoutError(f"{spec.name} 超时（>{spec.timeout_seconds}s）")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        if trace_collector is not None:
            trace_collector.append(
                ToolTrace(
                    tool_name=spec.name,
                    agent_step=str(agent_step or "").strip(),
                    success=False,
                    attempt=attempt,
                    duration_ms=duration_ms,
                    timed_out=timed_out,
                    error=str(last_error or ""),
                    permission=spec.permission,
                    cost_tier=spec.cost_tier,
                    input_summary=_preview_value(input_payload),
                ).to_dict()
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{spec.name} 调用失败")


def tool(
    name: str,
    description: str,
    *,
    input_schema: Optional[Dict[str, object]] = None,
    output_schema: Optional[Dict[str, object]] = None,
    timeout_seconds: float = 30.0,
    retry_count: int = 0,
    cost_tier: str = "low",
    permission: str = "read",
    tags: Optional[List[str]] = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        setattr(
            func,
            "__tool__",
            ToolSpec(
                name=name,
                description=description,
                input_schema=dict(input_schema or {}),
                output_schema=dict(output_schema or {}),
                timeout_seconds=float(timeout_seconds),
                retry_count=int(retry_count),
                cost_tier=str(cost_tier or "low"),
                permission=str(permission or "read"),
                tags=tuple(str(item) for item in (tags or [])),
            ),
        )
        return cast(F, func)

    return decorator

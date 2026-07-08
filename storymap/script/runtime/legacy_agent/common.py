"""
故事地图 Agent 通用工具模块。

本模块提供了 legacy_agent 包中多个模块共用的基础设施函数，
包括路径解析、LLM 调用封装、地理编码服务访问、Prompt 文件加载等。

主要功能：
- project_root_path(): 获取项目根目录的绝对路径
- _read_prompt(): 从 docs 目录下加载 Prompt 模板文件
- _llm_think(): 对 LLM 实例的 think 方法进行统一封装，支持运行时参数覆盖
- _llm_supports_runtime_overrides(): 检测 LLM 是否支持 timeout/max_retries 等运行时覆盖参数
- _geocode_service_utils / _geocode_api_utils: 地理编码服务的延迟导入
- _emit(): 向 LLM 实例发送流式消息（状态回调）
- _tool_uses_llm(): 检测自定义工具实现是否声明使用 LLM
- _fact_check_llm_enabled(): 检测是否启用事实校验 LLM
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Dict, List, Optional

from .constants import _TOOL_MANAGED_LLM_MAX_RETRIES


# =============================================================================
# 路径工具
# =============================================================================

def project_root_path() -> Path:
    """
    获取项目根目录的绝对路径。

    基于当前文件的位置向上回溯 4 级目录来确定项目根目录。

    Returns:
        Path: 项目根目录的 Path 对象。
    """
    return Path(__file__).resolve().parents[4]


# =============================================================================
# 地理编码服务导入（延迟导入，避免循环依赖）
# =============================================================================

def _geocode_service_utils():
    """
    获取地理编码服务工具模块（延迟导入）。

    延迟导入策略用于避免模块级别的循环依赖。

    Returns:
        module: geocode_service 工具模块。
    """
    from ...map import geocode_service as geocode_service_utils
    return geocode_service_utils


def _geocode_api_utils():
    """
    获取地理编码 API 工具模块（延迟导入）。

    延迟导入策略用于避免模块级别的循环依赖。

    Returns:
        module: geocode_api 工具模块。
    """
    from ...map import geocode_api as story_geocode_api_utils
    return story_geocode_api_utils


# =============================================================================
# Prompt 文件加载
# =============================================================================

def _read_prompt(relpath: str) -> str:
    """
    从 docs 目录下读取 Prompt 模板文件。

    Args:
        relpath: 相对于 storymap/docs/ 目录的文件路径。

    Returns:
        str: Prompt 文件的完整文本内容（UTF-8 编码）。

    Raises:
        FileNotFoundError: 当文件不存在时由 Path.read_text() 抛出。
    """
    prompt_path = project_root_path() / "storymap" / "docs" / relpath
    return prompt_path.read_text(encoding="utf-8")


# =============================================================================
# LLM 消息发送（流式状态回调）
# =============================================================================

def _emit(llm: object, message: str) -> None:
    """
    向 LLM 实例发送流式状态消息。

    通过调用 LLM 实例的 _emit 回调方法，将中间状态或日志信息传递给上层。

    Args:
        llm: LLM 实例对象，需具有 _emit 回调方法。
        message: 要发送的消息字符串。
    """
    if llm is None:
        return
    callback = getattr(llm, "_emit", None)
    if not callable(callback):
        return
    try:
        callback(message)
    except Exception:
        return


# =============================================================================
# LLM think 方法封装
# =============================================================================

def _llm_supports_runtime_overrides(llm: object) -> bool:
    """
    检测 LLM 实例的 think 方法是否支持运行时参数覆盖。

    判定方式：
    1. 检查 think 方法是否存在且可调用
    2. 检查其签名是否包含 VAR_KEYWORD（**kwargs）参数
    3. 若无 **kwargs，则检查是否同时包含 timeout 和 max_retries 参数

    Args:
        llm: LLM 实例对象。

    Returns:
        bool: True 表示支持运行时参数覆盖，False 表示不支持。
    """
    think = getattr(llm, "think", None)
    if not callable(think):
        return False

    # 获取 think 方法的参数签名
    try:
        signature = inspect.signature(think)
    except (TypeError, ValueError):
        return False

    parameters = signature.parameters.values()

    # 如果签名中包含 **kwargs，则可以传递任意参数
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters):
        return True

    # 否则需要同时包含 timeout 和 max_retries
    names = set(signature.parameters)
    return "timeout" in names and "max_retries" in names


def _llm_think(
    llm: object,
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0,
    timeout_seconds: Optional[int] = None,
    max_retries: int = _TOOL_MANAGED_LLM_MAX_RETRIES,
) -> object:
    """
    对 LLM 实例的 think 方法进行统一封装调用。

    自动检测 LLM 是否支持 timeout/max_retries 等运行时覆盖参数：
    - 若支持，则传递 timeout 和 max_retries
    - 若不支持，则仅传递 temperature（向后兼容）

    Args:
        llm: LLM 实例对象，需具有 think 方法。
        messages: 对话消息列表，每条消息为 {"role": ..., "content": ...} 格式。
        temperature: 采样温度，默认 0（确定性输出）。
        timeout_seconds: 调用超时时间（秒），None 表示无限制。
        max_retries: 最大重试次数，默认为 _TOOL_MANAGED_LLM_MAX_RETRIES。

    Returns:
        object: LLM 的响应结果，若 llm 为 None 或无 think 方法则返回空字符串。
    """
    if llm is None:
        return ""
    think = getattr(llm, "think", None)
    if not callable(think):
        return ""

    # 根据 LLM 的能力选择调用方式
    if _llm_supports_runtime_overrides(llm):
        return think(
            messages,
            temperature=temperature,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
    # 回退到基本调用方式（仅 temperature）
    return think(messages, temperature=temperature)


# =============================================================================
# 事实校验 LLM 开关
# =============================================================================

def _fact_check_llm_enabled(llm: object = None) -> bool:
    """
    检测是否启用了事实校验 LLM。

    通过环境变量 `STORY_AGENT_ENABLE_FACT_CHECK_LLM` 控制开关。

    Args:
        llm: LLM 实例对象（当前未在逻辑中使用，保留为扩展接口）。

    Returns:
        bool: True 表示启用了事实校验 LLM。
    """
    if llm is None:
        return False
    enabled = (os.getenv("STORY_AGENT_ENABLE_FACT_CHECK_LLM") or "").strip().lower()
    return enabled in {"1", "true", "yes", "on"}


# =============================================================================
# 自定义工具实现检测
# =============================================================================

def _tool_uses_llm(custom_impl: object, *, default_uses_llm: bool) -> bool:
    """
    检测自定义工具实现是否声明使用 LLM。

    判定逻辑：
    1. 若 custom_impl 为 None，返回 default_uses_llm 的值
    2. 否则检查 custom_impl 上的 `__story_agent_uses_llm__` 标记属性
    3. 若标记不存在，默认返回 False

    Args:
        custom_impl: 自定义工具实现对象（函数或类）。
        default_uses_llm: 当 custom_impl 为 None 时的默认返回值。

    Returns:
        bool: True 表示该工具使用了 LLM。
    """
    if custom_impl is None:
        return bool(default_uses_llm)
    marker = getattr(custom_impl, "__story_agent_uses_llm__", None)
    if marker is None:
        return False
    return bool(marker)

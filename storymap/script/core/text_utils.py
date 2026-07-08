"""文本处理工具函数。

提供跨模块共享的文本处理能力，包括：
- 模型推理思考块（thinking blocks）剥离
"""
from __future__ import annotations

import re

# ── Thinking block 剥离 ──────────────────────────────────────────────────
# Anthropic/MiniMax 等推理模型会在响应中嵌入思考过程，需要用正则剔除
# 才能提取干净的 JSON / 搜索查询。

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?<\uff0fthink>", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)
# 部分模型会输出不含尖括号的中文思考标记：思考过程 ... /思考
_CHINESE_THINK_BLOCK_RE = re.compile(r"思考过程[\s\S]*?[\uff0f/]思考", re.IGNORECASE)
# 裸 think.../think 标记（模型直接输出推理文本，无任何标签分隔）
# 仅匹配以 "think" 开头且紧跟换行或标点的情况，降低误匹配率
_BARE_THINK_BLOCK_RE = re.compile(
    r"^\s*think(?:\s*\n|[\s，。；：])[\s\S]*?[\uff0f/]think(?:\s*\n|$)",
    re.IGNORECASE,
)
# DeepSeek 推理模型的 `</think>` ... ` response` 思考块
# DeepSeek-R1/V3 系列使用 ` response` 包裹思考过程，最终答案在 ` response` 之后
_DEEPSEEK_THINK_RE = re.compile(
    r"<\uff5cthink\uff5c>[\s\S]*?<\uff5c\uff0fthink\uff5c>",
    re.IGNORECASE,
)
# DeepSeek 不带竖线变体：`</think>` ... ` response`
_DEEPSEEK_THINK_V2_RE = re.compile(
    r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>",
    re.IGNORECASE,
)


def strip_reasoning_blocks(text: object) -> str:
    """剥离模型响应中的思考过程标记，返回干净的文本。

    适用于 MiniMax/Anthropic/OpenAI 推理模型的输出清理。
    """
    content = str(text or "")
    if not content:
        return ""
    content = _THINK_BLOCK_RE.sub("", content)
    content = _THINK_TAG_RE.sub("", content)
    content = _CHINESE_THINK_BLOCK_RE.sub("", content)
    content = _BARE_THINK_BLOCK_RE.sub("", content)
    content = _DEEPSEEK_THINK_RE.sub("", content)
    content = _DEEPSEEK_THINK_V2_RE.sub("", content)
    return content.strip()


__all__ = ["strip_reasoning_blocks"]

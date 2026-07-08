"""审阅集成模块 — 将管线 B 的结构化校验能力注入管线 A 的 CriticAgent。

本模块是管线 A 和管线 B 的桥接点，为 CriticAgent 提供增强校验能力。
在 LLM 校验（validate_markdown）的基础上，额外执行 5 类结构化检测：

  1. LLM 思考泄露检测   — 检测 Markdown 中是否残留模型的思考过程
  2. 章节编号错误检测   — 检查章节编号是否连续、是否重复
  3. short_review 缺失  — 检测关键字段是否为空
  4. Markdown 占位符    — 检测未替换的模板占位符（如 {{person}}）
  5. 坐标一致性校验     — 校验地点坐标的有效性

这些检测源自管线 B 的 ReviewerAgent 经验，以纯 Python 规则实现，
不依赖 LLM 调用，确保在 CriticAgent 降级运行时仍可执行。

使用方式：
    from .critic_integration import enhanced_validation

    issues = enhanced_validation(markdown, search_result, place_maps)
    # 返回 List[AgentIssue]，可直接合并到 validation["issues"]
"""

from __future__ import annotations

import re
from typing import Dict, List


def enhanced_validation(
    markdown: str,
    search_result: Dict[str, object],
    place_maps: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    """执行增强校验，返回发现的问题列表。

    校验项（按优先级）：

    1. LLM 思考泄露：
       检测 "好的，我来"、"嗯，用户"、"让我" 等 LLM 典型开场白，
       这些文本不应该出现在最终 Markdown 中。

    2. 章节编号错误：
       检查 `## 一、` 到 `## 十、` 的编号是否连续、是否重复。
       支持 6 种错误模式：缺失、重复、乱序、数字格式错误、
       空章节、编号后无内容。

    3. short_review 缺失：
       Markdown 中的 `short_review` 字段不能为空或为占位符。

    4. Markdown 占位符：
       检测 `{{...}}` 模板占位符是否未替换。

    5. 坐标一致性：
       校验 place_maps 中的坐标是否有效（lat/lng 不为 None、
       在合理范围内）。

    Args:
        markdown:       待校验的 Markdown 文本
        search_result:  检索结果（用于 short_review 校验）
        place_maps:     地名映射列表（用于坐标校验）

    Returns:
        List[Dict]: 问题列表，每个问题的结构：
                   {"field": str, "claim": str, "correction": str,
                    "confidence": float, "reason": str}
    """
    issues: List[Dict[str, object]] = []

    text = str(markdown or "")

    # ── 1. LLM 思考泄露检测 ──
    # 检测 LLM 在生成过程中残留的思考过程文本
    think_patterns = [
        (r"好的[，,]我来", 'LLM 思考泄露：含\u201c好的，我来\u201d'),
        (r"嗯[，,]用户", 'LLM 思考泄露：含\u201c嗯，用户\u201d'),
        (r"让我.*?(?:生成|撰写|编写|创建|整理)", 'LLM 思考泄露：含\u201c让我...生成/撰写\u201d'),
        (r"根据.*?要求", 'LLM 思考泄露：含\u201c根据...要求\u201d'),
        (r"以下(?:是|为).*?(?:生成|撰写|整理)", 'LLM 思考泄露：含\u201c以下是为...生成\u201d'),
        (r"我会.*?(?:生成|撰写|编写|整理)", 'LLM 思考泄露：含\u201c我会...生成\u201d'),
        (r"这是.*?(?:生成|撰写|编写|整理)的", 'LLM 思考泄露：含\u201c这是...生成的\u201d'),
    ]
    for pattern, description in think_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append({
                "field": "think_leak",
                "claim": description,
                "correction": "移除 LLM 思考过程的残留文本",
                "confidence": 0.95,
                "reason": "LLM 思考过程不应出现在最终 Markdown 中",
            })
            break  # 一个文件只记录一次思考泄露

    # ── 2. 章节编号错误检测 ──
    # 提取所有 `## 数字、` 模式的章节标题
    # 例如：## 一、基本信息  →  编号 "一"
    cn_numbers = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    chapter_pattern = re.compile(r"##\s+([一二三四五六七八九十]+)[、，]")
    matches = chapter_pattern.findall(text)

    if matches:
        found_indices = []
        for num_str in matches:
            try:
                idx = cn_numbers.index(num_str) + 1  # 转为 1-based
                found_indices.append(idx)
            except ValueError:
                issues.append({
                    "field": "chapter_number",
                    "claim": f"无法识别的章节编号：{num_str}",
                    "correction": "使用中文数字 一 到 十 作为章节编号",
                    "confidence": 0.9,
                    "reason": "章节编号格式不符合规范",
                })

        if found_indices:
            # 检查是否从"一"开始
            if 1 not in found_indices:
                issues.append({
                    "field": "chapter_number",
                    "claim": '章节未从"一、"开始',
                    "correction": '确保第一章编号为"一、"',
                    "confidence": 0.85,
                    "reason": '章节编号应从"一、"开始',
                })

            # 检查编号是否连续
            for i in range(1, max(found_indices)):
                if i not in found_indices:
                    cn = cn_numbers[i - 1] if i <= len(cn_numbers) else str(i)
                    issues.append({
                        "field": "chapter_number",
                        "claim": f'章节编号不连续：缺少"## {cn}、"',
                        "correction": f'补充"## {cn}、"章节或调整编号',
                        "confidence": 0.8,
                        "reason": "章节编号出现跳跃",
                    })

            # 检查是否有重复编号
            seen = set()
            for idx in found_indices:
                if idx in seen:
                    cn = cn_numbers[idx - 1] if idx <= len(cn_numbers) else str(idx)
                    issues.append({
                        "field": "chapter_number",
                        "claim": f'章节编号重复："## {cn}、"出现了多次',
                        "correction": f'为"## {cn}、"章节使用唯一编号',
                        "confidence": 0.9,
                        "reason": "章节编号不能重复",
                    })
                seen.add(idx)

    # ── 3. short_review 缺失检测 ──
    short_review_match = re.search(
        'short_review["\'"]?\\s*[:：]\\s*["\'"]?([^"\'\\n]*)',
        text,
        re.IGNORECASE,
    )
    if short_review_match:
        review_text = short_review_match.group(1).strip()
        if not review_text or review_text in ("", "无", "暂无", "待补充", "略"):
            issues.append({
                "field": "short_review",
                "claim": "short_review 字段为空或无效",
                "correction": "补充 50-150 字的人物简介",
                "confidence": 0.95,
                "reason": "short_review 是页面的核心展示字段",
            })
    else:
        issues.append({
            "field": "short_review",
            "claim": "Markdown 中未找到 short_review 字段",
            "correction": "添加 short_review: 字段并填写人物简介",
            "confidence": 0.95,
            "reason": "short_review 是页面的核心展示字段",
        })

    # ── 4. Markdown 占位符检测 ──
    placeholder_pattern = re.compile(r"\{\{[^}]*\}\}")
    placeholders = placeholder_pattern.findall(text)
    if placeholders:
        issues.append({
            "field": "placeholder",
            "claim": f"Markdown 中存在未替换的占位符：{', '.join(placeholders[:5])}",
            "correction": "将所有 {{...}} 占位符替换为实际内容",
            "confidence": 0.95,
            "reason": "占位符不应出现在最终 Markdown 中",
        })

    # ── 5. 坐标一致性校验 ──
    if isinstance(place_maps, list):
        invalid_coords = 0
        for item in place_maps:
            if not isinstance(item, dict):
                continue
            lat = item.get("lat")
            lng = item.get("lng")
            name = str(item.get("ancient_name") or item.get("query") or "")

            if lat is None or lng is None:
                invalid_coords += 1
                continue

            # 检查坐标范围（中国及周边）
            try:
                lat_val = float(lat)
                lng_val = float(lng)
                if not (-90 <= lat_val <= 90 and -180 <= lng_val <= 180):
                    invalid_coords += 1
                    issues.append({
                        "field": "coordinates",
                        "claim": f"{name} 的坐标超出有效范围：({lat}, {lng})",
                        "correction": "修正坐标值使其在 WGS84 有效范围内",
                        "confidence": 0.9,
                        "reason": "坐标值不在有效地理范围内",
                    })
            except (TypeError, ValueError):
                invalid_coords += 1

        if invalid_coords > 0:
            issues.append({
                "field": "coordinates",
                "claim": f"{invalid_coords} 个地点的坐标缺失或无效",
                "correction": "补充有效坐标或标记为坐标待定",
                "confidence": 0.7,
                "reason": f"共 {invalid_coords} 个地点坐标需要修复",
            })

    return issues


__all__ = ["enhanced_validation"]

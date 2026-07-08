"""
===============================================================================
编辑集成模块 — Editor Integration
===============================================================================
将管线 B EditorAgent 的自修复能力注入管线 A 的 EditorAgent，提供生成后
Markdown 内容的自动清理与修复功能。

核心能力：
  1. LLM 思考过程（think-leak）清理 — 14 种正则模式
  2. 章节编号修复 — 6 种已知错误模式 + 通用顺序重编号
  3. Markdown 占位符清理 — 将"待补充"等占位符替换为"待考证"
  4. short_review 空值补充 — 为缺少 short_review 的人物补充回退值

典型用法：
    from .editor_integration import post_process_markdown
    cleaned, stats = post_process_markdown(raw_markdown, person="韩信",
                                           short_review_candidate="兵仙神帅")
===============================================================================
"""

from __future__ import annotations

import re
from typing import Optional

from ...quality.text_rules import cn_to_int, get_think_replacements

# ============================================================================
# 1. 思考过程泄露（think-leak）清理模式
# ============================================================================
# 从 text_rules 模块加载预定义的 think-leak 清理正则替换对。
# 每对为 (匹配模式, 替换文本)，用于清除 LLM 输出的思考过程残留文本。
THINK_PATTERNS: list[tuple[str, str]] = get_think_replacements()

# ============================================================================
# 2. short_review 回退值字典
# ============================================================================
# 当生成的 Markdown 中缺少 short_review 字段时，按人物名查找回退值。
# 这些回退值是对各历史人物的精炼评价概括。
SHORT_REVIEW_FALLBACKS: dict[str, str] = {
    "乐松生": "和平赎买",
    "亚历山大二世": "解放者沙皇",
    "哥伦布": "为上帝和国王陛下效力",
    "唐僖宗": "幸蜀",
    "威廉二世": "德意志帝国末代皇帝",
    "瓦特": "改良蒸汽机，推动工业革命",
    "郑成功": "开辟荆榛逐荷夷",
    "韩信": "兵仙神帅，汉初三杰",
}


# ============================================================================
# 3. 内部辅助函数
# ============================================================================

def _clean_think_text(text: str) -> tuple[str, bool]:
    """清理 LLM 思考过程（think-leak）文本。

    使用预定义的 THINK_PATTERNS 正则模式逐个匹配并替换。
    完成后合并多余空行并去除首尾空白。

    Args:
        text: 待清理的原始 Markdown 文本。

    Returns:
        tuple[str, bool]: (清理后的文本, 是否发生过修改)。
    """
    changed = False
    cleaned = text

    # ── 逐模式替换 ──
    for pattern, replacement in THINK_PATTERNS:
        new_text = re.sub(pattern, replacement, cleaned, flags=re.DOTALL | re.IGNORECASE)
        if new_text != cleaned:
            changed = True
            cleaned = new_text

    # ── 后处理：合并多余空行，去除首尾空白 ──
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned, changed


def _fix_chapter_numbering(markdown: str) -> tuple[str, bool]:
    """修复章节编号错误。

    分两步处理：
      1. 已知模式修复 — 针对 6 种已知的高频编号错误模式进行定向替换
      2. 通用重编号 — 检测所有 ## 级标题的中文序号，若不连续则按顺序重编

    Args:
        markdown: 待修复的 Markdown 文本。

    Returns:
        tuple[str, bool]: (修复后的文本, 是否发生过修改)。
    """
    changed = False
    md = markdown

    # ========================================================================
    # 第一步：已知模式修复
    # ========================================================================
    # 每条 fix 包含多个标题，按顺序排列：
    #   fix[0] — 第一个标题（通常正确）
    #   fix[1] — 第二个标题（可能重复/错误）
    #   fix[2] — 第二个标题的正确形式
    #   fix[3] — 第三个标题（可能错误）
    #   fix[4] — 第三个标题的正确形式
    #   ...依此类推
    # 修复策略：将第二个及之后重复出现的旧标题替换为新标题。
    fixes = [
        ("## 二、人生足迹地图说明", "## 二、人生历程与重要地点（按时间顺序）",
         "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
        ("## 四、生平时间线", "## 四、补充说明",
         "## 四、补充说明", None, "## 五、补充说明"),
        ("## 三、地点坐标", "## 三、生平时间线",
         "## 三、生平时间线", None, "## 四、生平时间线"),
        ("## 二、人生足迹概览", "## 二、人生历程与重要地点（按时间顺序）",
         "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
        ("## 二、作品", "## 二、人生历程与重要地点（按时间顺序）",
         "## 三、人生历程与重要地点（按时间顺序）", "## 三、生平时间线", "## 四、生平时间线"),
        ("## 三、人生历程与重要地点（按时间顺序）", "## 三、人生历程与重要地点（按时间顺序）",
         "## 三、人生历程与重要地点（按时间顺序）", None, "## 三、生平时间线",
         "## 四、生平时间线"),
    ]

    for fix in fixes:
        # 如果第二个重复标题存在，将其替换为正确形式
        if len(fix) >= 3 and fix[2] is not None:
            old = fix[1]
            new = fix[2]
            if md.count(old) > 1:
                # 保留第一次出现，替换第二次及之后的出现
                parts = md.split(old, 1)
                if len(parts) == 2:
                    md = parts[0] + old + parts[1].replace(old, new)
                    changed = True

    # ========================================================================
    # 第二步：通用重编号
    # ========================================================================
    # 提取所有 ## 级标题，检测中文序号是否连续。
    # 若不连续，按顺序重新分配中文数字编号。
    headings = re.findall(r"^## (.)[、，](.+)$", md, re.MULTILINE)
    if headings and len(headings) >= 2:
        expected = 1
        for cn, title in headings:
            num = cn_to_int(cn)
            if num is None:
                continue
            if num != expected:
                # 将阿拉伯数字期望值映射为中文数字
                cn_expected_map = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}
                new_cn = cn_expected_map.get(expected, str(expected))
                old_line = f"## {cn}、{title}"
                new_line = f"## {new_cn}、{title}"
                md = md.replace(old_line, new_line, 1)
                changed = True
            expected += 1

    return md, changed


def _clean_placeholders(text: str) -> tuple[str, bool]:
    """清理 Markdown 中的占位符文本。

    将 LLM 生成内容中残留的占位符（如"**待补充**"、"暂无可用"）统一替换为"待考证"，
    避免最终页面中出现无意义的占位符。

    Args:
        text: 待清理的 Markdown 文本。

    Returns:
        tuple[str, bool]: (清理后的文本, 是否发生过修改)。
    """
    changed = False
    placeholders = [
        r"\*\*待补充\*\*",
        r"待补充",
        r"暂无可用",
    ]
    cleaned = text
    for ph in placeholders:
        new_text = re.sub(ph, "待考证", cleaned)
        if new_text != cleaned:
            changed = True
            cleaned = new_text
    return cleaned, changed


def _populate_short_review(markdown: str, person: str, candidate: str = "") -> tuple[str, bool]:
    """补充缺失的 short_review 字段。

    在"### 基本信息"小节之后插入 short_review 字段。
    优先使用 candidate 参数，其次使用 SHORT_REVIEW_FALLBACKS 字典中的回退值。
    若 Markdown 中已存在 short_review 字段，则跳过。

    Args:
        markdown:  待处理的 Markdown 文本。
        person:    历史人物姓名，用于在回退字典中查找。
        candidate: 候选 short_review 文本，优先级最高。

    Returns:
        tuple[str, bool]: (处理后的文本, 是否插入过 short_review)。
    """
    changed = False
    md = markdown

    # 已有 short_review → 无需处理
    if "short_review" in md.lower():
        return md, False

    # 确定要插入的文本
    review_text = candidate or SHORT_REVIEW_FALLBACKS.get(person, "")
    if not review_text:
        return md, False

    # 在 "### 基本信息" 之后插入
    info_section = "### 基本信息"
    if info_section not in md:
        return md, False

    # 构建插入块
    insert_block = f"\n### short_review\n{review_text}\n"
    idx = md.index(info_section) + len(info_section)

    # 找到基本信息段结束位置（下一个 ## 或 ### 标题）
    next_section = re.search(r"\n##[#]? ", md[idx:])
    if next_section:
        md = md[:idx + next_section.start()] + insert_block + md[idx + next_section.start():]
    else:
        md += insert_block
    return md, True


# ============================================================================
# 4. 公开 API
# ============================================================================

def post_process_markdown(
    markdown: str,
    *,
    person: str = "",
    short_review_candidate: str = "",
) -> tuple[str, dict]:
    """对生成的 Markdown 执行管线 B 的自动修复流程。

    按顺序执行以下四个清理步骤：
      1. 清理 think-leak（LLM 思考过程残留文本）
      2. 修复章节编号（已知模式 + 通用重编号）
      3. 清理占位符（"待补充" → "待考证"）
      4. 补充 short_review（缺失时插入回退值）

    Args:
        markdown:               待修复的原始 Markdown 文本。
        person:                 历史人物姓名（keyword-only）。
        short_review_candidate: 候选 short_review 值，优先级高于回退字典（keyword-only）。

    Returns:
        tuple[str, dict]: (修复后的 Markdown 文本, 修复统计信息字典)。
            统计字典包含以下键：
              - think_leak:        是否清理过 think-leak 文本
              - chapter_fix:       是否修复过章节编号
              - placeholder_fix:   是否清理过占位符
              - short_review_added:是否补充过 short_review
    """
    stats = {
        "think_leak": False,
        "chapter_fix": False,
        "placeholder_fix": False,
        "short_review_added": False,
    }

    md = markdown

    # 步骤 1：清理 think-leak
    md, changed = _clean_think_text(md)
    stats["think_leak"] = changed

    # 步骤 2：修复章节编号
    md, changed = _fix_chapter_numbering(md)
    stats["chapter_fix"] = changed

    # 步骤 3：清理占位符
    md, changed = _clean_placeholders(md)
    stats["placeholder_fix"] = changed

    # 步骤 4：补充 short_review
    md, changed = _populate_short_review(md, person, short_review_candidate)
    stats["short_review_added"] = changed

    return md, stats


__all__ = [
    "SHORT_REVIEW_FALLBACKS",
    "post_process_markdown",
]

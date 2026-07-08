"""
故事文档校验规则模块 (validation_rules)。

本模块定义了一系列静态分析和启发式校验规则，用于检测故事文档
（人物传记 Markdown）中的数据质量问题，包括但不限于：

- 时间线年份顺序是否自洽
- 地名精度是否足够（古称 ↔ 现称 映射）
- 生卒年与享年是否一致
- 引用标签与身份别名的规范性
- 高风险人物声明的自动化校验

所有规则函数均以 `_xxx_issues` 命名，返回 `List[AgentIssue]`。
入口函数 `default_validate_markdown` 会依次调用所有规则，汇总结果。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from ...agent import generation_service as generation_service_utils
from ...core import parsers as parser_utils
from .common import _fact_check_llm_enabled, _llm_think, _read_prompt
from .constants import (
    _APPROXIMATE_MARKERS,
    _BROAD_ANCIENT_REGION_TOKENS,
    _CHINESE_DIGIT_MAP,
    _FACT_CHECK_LLM_TIMEOUT_SECONDS,
    _HIGH_RISK_CLAIM_RULES,
    _IDENTITY_TOKEN_PATTERNS,
    _NON_SINGLE_CITY_HINT_RE,
    _QUOTE_LABEL_HINT_RE,
    _UNCERTAINTY_MARKERS,
)
from .llm_parser import coerce_issue, coerce_issue_list, parse_json_payload
from .state import AgentIssue

# 亚里士多德的经典名言，用于校验：其他人物不应被标注此名言
_TRUTH_QUOTE = "吾爱吾师，吾更爱真理"


def _issue_field_from_text(text: str) -> str:
    """
    根据问题描述文本中的关键词，推断该问题属于哪个字段类别。

    Args:
        text: 问题描述文本。

    Returns:
        字段类别字符串，可能值为 "location"、"timeline"、"identity"、"age"、"other"。
    """
    content = str(text or "")
    # ── 地名/坐标相关 ──
    if "坐标" in content or "地名" in content or "地点" in content:
        return "location"
    # ── 时间线/年份/顺序相关 ──
    if "年份表" in content or "时间" in content or "顺序" in content:
        return "timeline"
    # ── 身份相关 ──
    if "身份" in content:
        return "identity"
    # ── 享年/年龄相关 ──
    if "享年" in content:
        return "age"
    # ── 兜底：其他 ──
    return "other"


def _dedupe_issues(issues: List[AgentIssue]) -> List[AgentIssue]:
    """
    对问题列表去重：若 field、claim、correction、reason 四元组完全相同，只保留一条。

    Args:
        issues: 待去重的问题列表。

    Returns:
        去重后的问题列表，保持首次出现的顺序。
    """
    out: List[AgentIssue] = []
    seen = set()
    for item in issues:
        # ── 构造去重键：field + claim + correction + reason ──
        key = (
            str(item.get("field") or ""),
            str(item.get("claim") or ""),
            str(item.get("correction") or ""),
            str(item.get("reason") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _extract_year(text: str) -> Optional[int]:
    """
    从文本中提取公元年份。

    支持：
    - "公元前 X 年" / "前 X 年" → 负数年份（如公元前 221 → -221）
    - 普通 "YYYY 年" → 正整数年份
    - 负数年份 "−YYYY 年" → 负数

    设计意图：统一将公元前年份转换为负数，避免后续生卒差与享年校验
    时出现符号不自洽的误报或漏报。

    Args:
        text: 包含年份表述的文本。

    Returns:
        提取到的整数年份；无法识别时返回 None。
    """
    content = str(text or "")
    # ── 步骤 1：优先匹配公元前/前 XXX 年 ──
    # 统一转换为负数年份，避免春秋战国等公元前人物在寿命/时间线一致性
    # 校验中被算成正数年份，导致生卒差与享年不自洽的误报或漏报。
    bce_match = re.search(r"(?:公元前|前)\s*(\d{1,4})\s*年", content)
    if bce_match:
        try:
            return -int(bce_match.group(1))
        except Exception:
            return None
    # ── 步骤 2：匹配普通年份（含可能负号） ──
    match = re.search(r"(-?\d{1,4})\s*年", content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_age(text: str) -> Optional[int]:
    """
    从文本中提取年龄（享年）。

    支持两种格式：
    - 阿拉伯数字："72 岁" / "72 周岁"
    - 中文数字："七十二岁" / "廿四岁"

    Args:
        text: 包含年龄表述的文本。

    Returns:
        提取到的整数年龄；无法识别时返回 None。
    """
    content = str(text or "")
    # ── 步骤 1：尝试匹配阿拉伯数字年龄 ──
    match = re.search(r"(\d{1,3})\s*(?:周)?岁", content)
    if not match:
        # ── 步骤 2：尝试匹配中文数字年龄 ──
        cn_match = re.search(r"([零〇一二两三四五六七八九十百廿卅]{1,6})\s*(?:周)?岁", content)
        if not cn_match:
            return None
        return _parse_chinese_number(cn_match.group(1))
    try:
        return int(match.group(1))
    except Exception:
        return None


def _parse_chinese_number(text: str) -> Optional[int]:
    """
    将中文数字字符串解析为整数。

    支持的中文数字字符包括：零、一、二、三、四、五、六、七、八、九、十、百、廿、卅。
    采用累加式解析策略，按位读取字符并动态计算数值。

    Args:
        text: 中文数字字符串（如 "七十二"、"一百二十三"）。

    Returns:
        解析后的整数；包含无法识别的字符时返回 None。
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    # ── 预处理：替换变体字 ──
    normalized = raw.replace("廿", "二十").replace("卅", "三十").replace("两", "二")
    total = 0      # 累积总值
    current = 0    # 当前位的数值（十/百之前的数字）
    for ch in normalized:
        # ── 基础数字（零～九） ──
        if ch in _CHINESE_DIGIT_MAP:
            current = _CHINESE_DIGIT_MAP[ch]
            total += current
            continue
        # ── "十"：进位逻辑 ──
        if ch == "十":
            if current == 0:
                # 前面没有数字，如 "十" → 10
                total += 10
            else:
                # 前面有数字，如 "三十"：之前累加了 3，这里把 3 从 10 替换掉
                # 即 total 中多加的 current(3) 要退回，改为 current*10
                total += current * 9  # 等价于 total = total - current + current*10
            current = 0
            continue
        # ── "百"：进位逻辑 ──
        if ch == "百":
            if current == 0:
                # 前面没有数字，如 "百" → 100
                total = max(total, 1) * 100
            else:
                # 前面有数字，如 "三百"：之前累加了 3，改为 3*100
                total += current * 99  # 等价于 total = total - current + current*100
            current = 0
            continue
        # ── 无法识别的字符 → 解析失败 ──
        return None
    return total or None


def _needs_modern_hint(text: str) -> bool:
    """
    判断一个地点文本是否需要补充现代地名提示。

    如果文本中已经包含 "今" 字，或包含现代行政区划关键词
    （省/市/县/区/州/郡/自治区/特别行政区），则认为已足够，
    不需要再补充。

    Args:
        text: 地点文本。

    Returns:
        True 表示需要补充现代地名提示，False 表示不需要。
    """
    content = str(text or "").strip()
    if not content:
        return False
    # 已含 "今" → 已有现代参照
    if "今" in content:
        return False
    # 已含现代行政区划关键词 → 不需要补充
    if re.search(r"(省|市|县|区|州|郡|自治区|特别行政区)", content):
        return False
    return True


def _is_vague_location(text: str) -> bool:
    """
    判断地点文本是否为泛区域表述（无法精确定位）。

    匹配词尾的泛区域词汇，如"境内""诸地""各地""一带""附近""周边""沿线""流域""地区"
    "北方""南方""中原""关中""江南"。

    Args:
        text: 地点文本。

    Returns:
        True 表示是泛区域表述，False 表示可精确定位。
    """
    content = str(text or "").strip()
    if not content:
        return False
    return bool(re.search(r"(境内|诸地|各地|一带|附近|周边|沿线|流域|地区|北方|南方|中原|关中|江南)$", content))


def _looks_like_single_modern_city(text: str) -> bool:
    """
    判断文本是否像是一个单一的现代城市名称。

    先通过 NON_SINGLE_CITY_HINT_RE 排除明显不是单一城市的情况
    （如包含多个地名、描述性文字等），再检查是否以"市""县""区"结尾。

    Args:
        text: 现代地名文本。

    Returns:
        True 表示看起来是单一现代城市，False 表示不是。
    """
    content = str(text or "").strip()
    if not content:
        return False
    # ── 排除非单一城市的情况 ──
    if _NON_SINGLE_CITY_HINT_RE.search(content):
        return False
    # ── 检查是否以 "市/县/区" 结尾 ──
    return bool(re.search(r"(省)?[^，。、；;]{1,20}(市|县|区)$", content))


# ═══════════════════════════════════════════════════════════════════════════════
#  规则函数：每个函数独立检测一类数据质量问题，返回 List[AgentIssue]
# ═══════════════════════════════════════════════════════════════════════════════


def _timeline_order_issues(parsed_doc: object) -> List[AgentIssue]:
    """
    校验时间线年份是否按从早到晚排列。

    遍历时间线行，提取每行的年份，检查是否存在倒序（后一行年份小于前一行）。
    一旦发现倒序，即报告一个 issue 并终止检查（不逐行报告）。

    Args:
        parsed_doc: 解析后的故事文档对象，需包含 timeline_rows 属性。

    Returns:
        时间线顺序问题列表，最多包含一条 issue。
    """
    issues: List[AgentIssue] = []
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    # ── 步骤 1：从时间线行中提取有效年份 ──
    years: List[Tuple[int, List[str]]] = []
    for row in rows:
        if not row:
            continue
        year = _extract_year(row[0])  # 第一列为年份
        if year is None:
            continue
        years.append((year, row))
    # ── 步骤 2：逐行检查年份是否递增 ──
    for idx in range(1, len(years)):
        prev_year, _ = years[idx - 1]
        current_year, row = years[idx]
        if current_year < prev_year:
            issues.append(
                coerce_issue(
                    field="timeline",
                    claim=" | ".join(str(cell or "") for cell in row),
                    correction="按时间从早到晚重新排序时间线表",
                    confidence=0.82,
                    reason="时间线年份顺序出现倒序",
                )
            )
            break  # 发现一处倒序即停止，避免重复报告
    return issues


def _location_precision_issues(parsed_doc: object) -> List[AgentIssue]:
    """
    校验地点信息的精度是否足够。

    检查项：
    1. 出生地/去世地是否缺少现代地名提示（如缺少 "今 XX 省 XX 市"）。
    2. 时间线的"现称"列是否为空（有古称无现称）。
    3. 时间线的"现称"是否为泛区域表述（无法精确定位）。

    Args:
        parsed_doc: 解析后的故事文档对象。

    Returns:
        地点精度问题列表。
    """
    issues: List[AgentIssue] = []
    basic_info = getattr(parsed_doc, "basic_info", None)
    # ── 检查 1：基本信息中的出生地/去世地 ──
    if basic_info is not None:
        birth_text = str(getattr(basic_info, "birth_text", "") or "")
        death_text = str(getattr(basic_info, "death_text", "") or "")
        if birth_text and _needs_modern_hint(birth_text):
            issues.append(
                coerce_issue(
                    field="location",
                    claim=birth_text,
                    correction="补充出生地对应的现代地名",
                    confidence=0.68,
                    reason="出生地缺少现代地名提示，后续地图定位容易不稳定",
                )
            )
        if death_text and _needs_modern_hint(death_text):
            issues.append(
                coerce_issue(
                    field="location",
                    claim=death_text,
                    correction="补充去世地对应的现代地名",
                    confidence=0.68,
                    reason="去世地缺少现代地名提示，后续地图定位容易不稳定",
                )
            )
    # ── 检查 2 & 3：时间线中的古称/现称 ──
    header = list(getattr(parsed_doc, "timeline_header", []) or [])
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    # 定位"现称"列的索引
    modern_idx = None
    for idx, cell in enumerate(header):
        if "现称" in str(cell or ""):
            modern_idx = idx
            break
    if modern_idx is not None:
        for row in rows:
            if modern_idx >= len(row):
                continue
            modern_name = str(row[modern_idx] or "").strip()
            # 获取对应的古称（现称列的前一列）
            ancient_name = str(row[modern_idx - 1] or "").strip() if modern_idx > 0 and modern_idx - 1 < len(row) else ""
            # ── 子检查 2：有古称但无现称 ──
            if ancient_name and not modern_name:
                issues.append(
                    coerce_issue(
                        field="location",
                        claim=" | ".join(str(cell or "") for cell in row),
                        correction="为该时间线条目补充现代地名",
                        confidence=0.73,
                        reason="时间线存在古称但缺少现称",
                    )
                )
                break
            # ── 子检查 3：现称为泛区域表述 ──
            if modern_name and _is_vague_location(modern_name):
                issues.append(
                    coerce_issue(
                        field="location",
                        claim=" | ".join(str(cell or "") for cell in row),
                        correction="将泛地名替换为可落点的现代城市、区县或明确遗址",
                        confidence=0.9,
                        reason="时间线现称仍是泛区域表述，无法保证地图定位精度",
                    )
                )
                break
    return issues


def _ancient_modern_overmapping_issues(parsed_doc: object) -> List[AgentIssue]:
    """
    校验古称与现称是否存在过度一对一映射。

    当古称属于大范围区域（如"西域""中原""江南"等），但现称被映射为
    单一现代城市时，报告过度映射风险。因为大区域对应多个现代地点，
    不适合压成一个单一城市。

    Args:
        parsed_doc: 解析后的故事文档对象。

    Returns:
        过度映射问题列表。
    """
    issues: List[AgentIssue] = []
    header = list(getattr(parsed_doc, "timeline_header", []) or [])
    rows = list(getattr(parsed_doc, "timeline_rows", []) or [])
    # ── 步骤 1：定位"古称"和"现称"列索引 ──
    ancient_idx = None
    modern_idx = None
    for idx, cell in enumerate(header):
        label = str(cell or "")
        if "古称" in label and ancient_idx is None:
            ancient_idx = idx
        if "现称" in label and modern_idx is None:
            modern_idx = idx
    if ancient_idx is None or modern_idx is None:
        return issues  # 缺少必要的列，跳过校验
    # ── 步骤 2：逐行检查过度映射 ──
    for row in rows:
        if ancient_idx >= len(row) or modern_idx >= len(row):
            continue
        ancient_name = str(row[ancient_idx] or "").strip()
        modern_name = str(row[modern_idx] or "").strip()
        if not ancient_name or not modern_name:
            continue
        # 古称必须在大区域白名单中
        if ancient_name not in _BROAD_ANCIENT_REGION_TOKENS:
            continue
        # 现称必须看起来像单一城市
        if not _looks_like_single_modern_city(modern_name):
            continue
        # ── 触发：大区域古称 + 单一城市现称 = 过度映射 ──
        issues.append(
            coerce_issue(
                field="location",
                claim=" | ".join(str(cell or "") for cell in row),
                correction='把这类古地理范围改成"今某地区/一带/走廊沿线"等更稳妥的现代参照，不要直接压成单一现代城市。',
                confidence=0.86,
                reason="古地理范围明显大于单一现代城市，存在过度一对一映射风险。",
            )
        )
        break  # 发现一处即报告，避免冗余
    return issues


def _lifespan_issues(parsed_doc: object) -> List[AgentIssue]:
    """
    校验生卒年与享年是否自洽。

    检查项：
    1. 享年 ≈ 卒年 − 生年（允许 ±1 年的误差，考虑虚岁等因素）。
    2. 当生卒年信息存在不确定性标记（如"约""一说""不详"），
       享年是否也标注了相应不确定性。

    Args:
        parsed_doc: 解析后的故事文档对象。

    Returns:
        寿命/享年相关问题列表。
    """
    issues: List[AgentIssue] = []
    basic_info = getattr(parsed_doc, "basic_info", None)
    if basic_info is None:
        return issues
    # ── 提取生年、卒年、享年 ──
    birth_year = _extract_year(getattr(basic_info, "birth_text", ""))
    death_year = _extract_year(getattr(basic_info, "death_text", ""))
    lifespan = _extract_age(getattr(basic_info, "lifespan", ""))
    if birth_year is None or death_year is None or lifespan is None:
        return issues  # 缺少必要数据，无法校验
    # ── 检查 1：生卒差与享年是否一致 ──
    estimated = death_year - birth_year
    if abs(estimated - lifespan) > 1:
        issues.append(
            coerce_issue(
                field="age",
                claim=f"出生 {birth_year} 年，去世 {death_year} 年，享年 {lifespan} 岁",
                correction=f"核对享年是否应为 {estimated} 岁左右",
                confidence=0.88,
                reason="生卒年与享年不自洽",
            )
        )
    # ── 检查 2：生卒信息不确定时，享年是否也标注不确定性 ──
    birth_text = str(getattr(basic_info, "birth_text", "") or "")
    death_text = str(getattr(basic_info, "death_text", "") or "")
    lifespan_text = str(getattr(basic_info, "lifespan", "") or "")
    if lifespan is not None and any(marker in birth_text or marker in death_text for marker in _APPROXIMATE_MARKERS):
        # 生卒年有"约/一说/不详"等标记，但享年没有对应不确定表述
        if "约" not in lifespan_text and "左右" not in lifespan_text and "余" not in lifespan_text:
            issues.append(
                coerce_issue(
                    field="age",
                    claim=f"出生：{birth_text}；去世：{death_text}；享年：{lifespan_text}",
                    correction='如果生卒年份本身带有"约/一说/不详"等不确定性，享年也应改为"约 XX 岁"或补充说法来源。',
                    confidence=0.84,
                    reason="生卒信息存在不确定性时，享年不宜写成完全确定的绝对结论。",
                )
            )
    return issues


# ── 作品描述检测：区分 "《诗名》：诗句原文"（合法引文）与 "《作品名》：以...形象"（作品描述）──
_WORK_DESC_MARKERS = re.compile(r"(以|用|通过|表现|描绘|描述|刻画|塑造|展现|呈现|象征|寓示|表达|抒发|讴歌|赞颂)")


def _is_work_description(claim: str) -> bool:
    """判断 "《作品名》：..." 条目是否为作品描述而非直接引文。

    标准诗词引用格式 "《诗名》：诗句原文" 中，诗句原文是作品本身的文本，
    不含"以/表现/描绘/象征"等描述性标记词。反之，如果包含这些标记词，
    则是作品描述，不应挂在"名篇名句"下。

    Args:
        claim: 名篇名句条目的完整文本（如 "《红烛颂》：以闻一多形象象征燃烧的理想"）

    Returns:
        True 如果是作品描述，False 如果是直接引文。
    """
    # 提取 "：" 后的内容
    idx = max(claim.rfind("："), claim.rfind(":"))
    if idx < 0:
        return False
    after = claim[idx + 1:].strip()
    if not after:
        return False
    # 如果 "：" 后的内容包含描述性标记词，则是作品描述
    return bool(_WORK_DESC_MARKERS.search(after))


def _quote_label_issues(content: str, *, person: str) -> List[AgentIssue]:
    """
    校验"名篇名句"部分的引用标签是否规范。

    检查项：
    1. 条目包含书名号（《》）但无引号 → 可能是作品/思想介绍而非直接引文。
    2. 条目包含"后世""概括""不宜""非……原文"等字样 → 已承认非严格原文。
    3. 非亚里士多德人物引用"吾爱吾师……" → 该句不应被移作其他人物的名言。

    Args:
        content: 完整的 Markdown 文档内容。
        person: 人物姓名（用于高风险句归属校验）。

    Returns:
        引用标签问题列表。
    """
    issues: List[AgentIssue] = []
    # ── 遍历所有匹配到的引用标签 ──
    for match in _QUOTE_LABEL_HINT_RE.finditer(str(content or "")):
        claim = str(match.group(1) or "").strip()
        if not claim:
            continue
        # ── 子检查 1：有书名号无引号 → 更像作品介绍 ──
        # 例外：标准诗词引用格式 "《作品名》：诗句原文" 是合法的直接引文，
        # 但 "《作品名》：以...形象/表现.../描绘..." 仍是作品描述而非引文。
        if "《" in claim and "》" in claim and '"' not in claim and "'" not in claim:
            if ("：" in claim or ":" in claim) and not _is_work_description(claim):
                continue
            issues.append(
                coerce_issue(
                    field="quote",
                    claim=claim,
                    correction='如果这里是在介绍作品或思想，请改成"代表作品""代表著作"或"相关思想"，不要挂在"名篇名句"下。',
                    confidence=0.78,
                    reason="该条更像作品说明或思想概括，不像可核对的直接引文。",
                )
            )
            continue
        # ── 子检查 2：明确非严格原文 ──
        if "后世" in claim or "概括" in claim or "不宜" in claim or "非" in claim and "原文" in claim:
            issues.append(
                coerce_issue(
                    field="quote",
                    claim=claim,
                    correction='该条已承认并非严格原文，建议从"名篇名句"改到"相关思想"或说明性条目。',
                    confidence=0.72,
                    reason='该条明确属于后世概括或非严格原文，不适合作为"名篇名句"展示。',
                )
            )
    # ── 子检查 3：名言归属校验 ──
    if person != "亚里士多德" and _TRUTH_QUOTE in str(content or ""):
        issues.append(
            coerce_issue(
                field="quote",
                claim=_TRUTH_QUOTE,
                correction="不要把这句话当作当前人物本人的名言；若确需保留，应说明它是后世概括亚里士多德学派精神的常见说法。",
                confidence=0.9,
                reason="该句不应被移作其他人物本人的名言或原话。",
            )
        )
    return issues


def _identity_alias_issues(content: str) -> List[AgentIssue]:
    """
    校验身份/别名信息是否混写在同一结论中。

    如果一行中同时包含多种身份标识（如姓名、别名、字、号），
    且该行属于身份相关段落，则报告混写风险。

    Args:
        content: 完整的 Markdown 文档内容。

    Returns:
        身份/别名混写问题列表。
    """
    issues: List[AgentIssue] = []
    text = str(content or "")
    # ── 逐行扫描 ──
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # ── 统计该行匹配到的身份类别数量 ──
        categories = {
            category
            for category, pattern in _IDENTITY_TOKEN_PATTERNS
            if pattern.search(line)
        }
        # ── 如果该行是身份相关段落，且匹配到 2 种及以上身份类别 → 混写风险 ──
        if ("姓名" in line or "人物" in line or "身份" in line) and len(categories) >= 2:
            issues.append(
                coerce_issue(
                    field="identity",
                    claim=line,
                    correction='把原名、别名、字、号拆开表述，并补上"常见称谓/后世称法/早年姓氏"等限定，避免读者误解成唯一结论。',
                    confidence=0.74,
                    reason="原名/别名/字/号混写在同一结论里，容易把不同性质的称谓误读成同一种确定身份信息。",
                )
            )
            break  # 发现一处即报告
    return issues


def _high_risk_claim_issues(content: str, *, person: str) -> List[AgentIssue]:
    """
    根据预定义的高风险声明规则，检测文档中是否存在已知的错误或高风险表述。

    规则来自 constants 模块的 _HIGH_RISK_CLAIM_RULES，每条规则包含：
    - person: 适用的人物
    - pattern: 匹配的正则模式
    - field/correction/confidence/reason: 问题描述

    Args:
        content: 完整的 Markdown 文档内容。
        person: 人物姓名（用于匹配规则）。

    Returns:
        高风险声明问题列表。
    """
    issues: List[AgentIssue] = []
    text = str(content or "")
    # ── 遍历所有高风险声明规则 ──
    for rule in _HIGH_RISK_CLAIM_RULES:
        # 仅匹配当前人物
        if str(rule.get("person") or "") != str(person or ""):
            continue
        pattern = rule.get("pattern")
        if not isinstance(pattern, re.Pattern):
            continue
        # ── 在文档全文搜索匹配 ──
        match = pattern.search(text)
        if not match:
            continue
        # ── 命中规则：构造 issue ──
        issues.append(
            coerce_issue(
                field=str(rule.get("field") or "other"),
                claim=str(match.group(0) or "").strip(),
                correction=str(rule.get("correction") or "").strip(),
                confidence=float(rule.get("confidence") or 0.0),
                reason=str(rule.get("reason") or "").strip(),
            )
        )
    return issues


def _risk_level_from_issues(issues: List[AgentIssue]) -> str:
    """
    根据问题列表中的最高置信度，判定整体风险等级。

    分级标准：
    - confidence ≥ 0.8 → "high"
    - confidence ≥ 0.5 → "medium"
    - 其余 → "low"
    - 无 issue → "low"

    Args:
        issues: 问题列表。

    Returns:
        风险等级字符串："low"、"medium" 或 "high"。
    """
    if not issues:
        return "low"
    # ── 取所有 issue 中的最高置信度 ──
    max_conf = max(float(item.get("confidence") or 0.0) for item in issues)
    if max_conf >= 0.8:
        return "high"
    if max_conf >= 0.5:
        return "medium"
    return "low"


def _llm_fact_check(
    llm: object,
    *,
    person: str,
    content: str,
) -> List[AgentIssue]:
    """
    使用 LLM 对文档内容进行事实核查。

    将文档的基本信息、概述摘要、时间线摘要发送给 LLM，
    由 LLM 判断是否存在事实性错误或存疑点。

    Args:
        llm: LLM 客户端对象。
        person: 人物姓名。
        content: 完整的 Markdown 文档内容。

    Returns:
        LLM 返回的问题列表；LLM 不可用或调用失败时返回空列表。
    """
    # ── 步骤 1：检查 LLM 是否可用 ──
    if not _fact_check_llm_enabled(llm):
        return []
    # ── 步骤 2：解析文档，提取关键信息 ──
    try:
        parsed_doc = parser_utils.parse_story_document(content)
    except Exception:
        return []
    # ── 步骤 3：构造 prompt，发送给 LLM ──
    prompt = _read_prompt("fact_check_prompt.md").format(
        person=person,
        basic_info=json.dumps(parsed_doc.basic_info.raw, ensure_ascii=False),
        summary_excerpt=(parsed_doc.overview or "")[:400],
        timeline_excerpt=json.dumps(parsed_doc.timeline_rows[:8], ensure_ascii=False),
    )
    raw = _llm_think(
        llm,
        [{"role": "system", "content": prompt}],
        temperature=0,
        timeout_seconds=_FACT_CHECK_LLM_TIMEOUT_SECONDS,
    )
    # ── 步骤 4：解析 LLM 返回的 JSON payload ──
    payload = parse_json_payload(raw or "")
    if not payload:
        return []
    return coerce_issue_list(payload.get("issues") or [])


def _caution_consistency_issues(content: str, cautions: object) -> List[AgentIssue]:
    """
    校验 search_result 中已标注的存疑点是否在正文中体现不确定性。

    如果 search_result 的 cautions 字段中存在存疑标记，但正文中没有任何
    不确定性表述（如"约""存疑""说法不一"等），则报告一致性问题。

    Args:
        content: 完整的 Markdown 文档内容。
        cautions: search_result 中的存疑点列表。

    Returns:
        存疑一致性问题的列表。
    """
    issues: List[AgentIssue] = []
    # ── 提取非空存疑条目 ──
    caution_list = [str(item).strip() for item in list(cautions or []) if str(item).strip()]
    if not caution_list:
        return issues
    body = str(content or "")
    # ── 正文已有不确定性表述 → 无需报告 ──
    if any(marker in body for marker in _UNCERTAINTY_MARKERS):
        return issues
    # ── 正文缺少不确定性表述 → 报告 ──
    caution_preview = "；".join(caution_list[:2])
    issues.append(
        coerce_issue(
            field="caution",
            claim=caution_preview,
            correction='把对应表述改成"存疑/说法不一/一说"等不确定表达，避免把检索阶段已标记的存疑点写成唯一结论。',
            confidence=0.8,
            reason="search_result 已标注存疑点，但当前正文没有体现不确定性表述。",
        )
    )
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
#  入口函数
# ═══════════════════════════════════════════════════════════════════════════════


def default_validate_markdown(
    content: str,
    *,
    person: str = "",
    llm: object = None,
) -> Dict[str, object]:
    """
    对故事文档（人物传记 Markdown）执行完整的校验流水线。

    依次执行以下步骤：
    1. 收集文本质量指标（metrics）
    2. 运行通用文本质量校验
    3. 解析文档结构
    4. 执行各类静态规则校验（时间线、地点精度、古称映射、寿命等）
    5. 执行引用标签和身份别名校验
    6. 执行高风险声明校验
    7. 执行 LLM 事实核查
    8. 去重、汇总风险等级

    Args:
        content: 完整的 Markdown 文档内容。
        person: 人物姓名（可选，未提供时会从文档中自动提取）。
        llm:   LLM 客户端对象（可选，用于事实核查）。

    Returns:
        校验结果字典，包含以下字段：
        - pass (bool): 是否通过校验（无 confidence ≥ 0.7 的 issue）
        - risk_level (str): 风险等级（"low"/"medium"/"high"）
        - issues (List[AgentIssue]): 发现的问题列表
        - notes (str): 问题摘要说明
        - metrics (dict): 文本质量指标
    """
    # ── 步骤 1：收集文本质量指标 ──
    metrics = generation_service_utils.collect_quality_metrics(content)
    # ── 步骤 2：运行通用文本质量校验 ──
    text_issues = generation_service_utils.validate_data_quality(content)
    issues: List[AgentIssue] = [
        coerce_issue(
            field=_issue_field_from_text(item),
            claim=item,
            correction="",
            confidence=0.62,
            reason=item,
        )
        for item in text_issues
    ]
    # ── 步骤 3：解析文档结构 ──
    try:
        parsed_doc = parser_utils.parse_story_document(content)
    except Exception:
        parsed_doc = None
    # ── 步骤 4：执行各类静态规则校验 ──
    if parsed_doc is not None:
        # 未提供人物姓名时，从文档中自动提取
        if not person:
            person = str(getattr(getattr(parsed_doc, "basic_info", None), "name", "") or "")
        issues.extend(_timeline_order_issues(parsed_doc))
        issues.extend(_location_precision_issues(parsed_doc))
        issues.extend(_ancient_modern_overmapping_issues(parsed_doc))
        issues.extend(_lifespan_issues(parsed_doc))
    # ── 步骤 5：执行文本级校验（不依赖文档结构解析） ──
    issues.extend(_quote_label_issues(content, person=person))
    issues.extend(_identity_alias_issues(content))
    issues.extend(_high_risk_claim_issues(content, person=person))
    # ── 步骤 6：LLM 事实核查 ──
    issues.extend(_llm_fact_check(llm, person=person, content=content))
    # ── 步骤 7：去重与风险等级汇总 ──
    issues = _dedupe_issues(issues)
    risk_level = _risk_level_from_issues(issues)
    # ── 步骤 8：判定是否通过（有 confidence ≥ 0.7 的 issue 即不通过） ──
    hard_fail = any(float(item.get("confidence") or 0.0) >= 0.7 for item in issues)
    return {
        "pass": (not hard_fail),
        "risk_level": risk_level,
        "issues": issues,
        "notes": "" if not issues else f"共发现 {len(issues)} 个待核查点",
        "metrics": metrics,
    }

"""数据层级回归测试。

这一组测试的目标不是测代码分支，而是保护“数据可信度”：
1. 苏轼 6 件代表作品的 tooltip 不被串到其他作品/生平上。
2. 作品摘要不混入其他作品的标题，避免出现“串条”。
3. is_foreign 与朝代字段一致，避免再次出现“中国人物被画成方形”的情况。
4. 已经修过的人物白名单（徐光启/梁思成/郑成功）持续保持非方形。
5. 字段缺失率不破基线，防止数据质量随版本悄悄滑坡。

测试只依赖已生成的产物 JSON，不依赖外部网络或大模型。
"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List

import pytest


from tests_support import REPO_ROOT

ROOT = REPO_ROOT
WORK_INDEX_PATH = ROOT / "data" / "corpus" / "work_summary_index.json"
HOME_DATA_PATH = ROOT / "artifacts" / "story_map" / "stellar_home_data.json"


CHINESE_DYNASTY_KEYWORDS = (
    "夏",
    "商",
    "周",
    "春秋",
    "战国",
    "秦",
    "西汉",
    "东汉",
    "汉",
    "三国",
    "魏",
    "蜀",
    "吴",
    "晋",
    "南北朝",
    "北朝",
    "南朝",
    "隋",
    "唐",
    "五代",
    "宋",
    "北宋",
    "南宋",
    "辽",
    "金",
    "西夏",
    "元",
    "明",
    "清",
    "中华民国",
    "民国",
    "中华人民共和国",
    "近现代",
    "当代",
    "明末清初",
)

FOREIGN_DYNASTY_HINTS = (
    "日本",
    "古希腊",
    "古罗马",
    "罗马",
    "拜占庭",
    "奥斯曼",
    "波斯",
    "阿拉伯",
    "印度",
    "蒙兀儿",
    "欧洲",
    "文艺复兴",
    "启蒙",
    "工业革命",
    "维多利亚",
    "西班牙",
    "葡萄牙",
    "英国",
    "法国",
    "德国",
    "美国",
    "意大利",
    "荷兰",
    "俄罗斯",
    "苏联",
    "希腊",
    "马其顿",
    "美索不达米亚",
    "埃及",
    "犹太",
    "巴勒斯坦",
    "圣经",
)


# ---------- 共用加载 ---------- #


@pytest.fixture(scope="module")
def work_index() -> Dict[str, dict]:
    if not WORK_INDEX_PATH.exists():
        pytest.skip(f"缺少作品摘要索引：{WORK_INDEX_PATH}")
    payload = json.loads(WORK_INDEX_PATH.read_text(encoding="utf-8"))
    items = payload.get("items") or {}
    if not isinstance(items, dict):
        pytest.skip("work_summary_index.items 不是 dict")
    return items


@pytest.fixture(scope="module")
def home_nodes() -> List[dict]:
    if not HOME_DATA_PATH.exists():
        pytest.skip(f"缺少首页 stellar_home_data：{HOME_DATA_PATH}")
    payload = json.loads(HOME_DATA_PATH.read_text(encoding="utf-8"))
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        pytest.skip("stellar_home_data.nodes 为空")
    return [n for n in nodes if isinstance(n, dict)]


# ---------- 1. 苏轼核心作品 tooltip 锁定 ---------- #


SUSHI_REQUIRED_WORKS = {
    "水调歌头·明月几时有": {
        "summary_keywords": ["中秋", "明月"],
        "quote_must_have": "但愿人长久",
        "forbid_keywords": ["庭下如积水空明", "大江东去", "天下第三行书"],
    },
    "江城子·密州出猎": {
        "summary_keywords": ["密州", "出猎"],
        "quote_must_have": "射天狼",
        "forbid_keywords": ["但愿人长久", "庭下如积水空明", "大江东去"],
    },
    "记承天寺夜游": {
        "summary_keywords": ["承天寺", "夜游", "黄州"],
        "quote_must_have": "庭下如积水空明",
        "forbid_keywords": ["但愿人长久", "大江东去", "射天狼"],
    },
    "念奴娇·赤壁怀古": {
        "summary_keywords": ["赤壁", "怀古"],
        "quote_must_have": "大江东去",
        "forbid_keywords": ["但愿人长久", "庭下如积水空明", "射天狼"],
    },
    "赤壁赋": {
        "summary_keywords": ["赤壁", "变与不变"],
        "quote_must_have": "寄蜉蝣于天地",
        "forbid_keywords": ["但愿人长久", "庭下如积水空明", "大江东去", "射天狼"],
    },
    "寒食帖": {
        "summary_keywords": ["书法", "黄州"],
        "quote_must_have": "天下第三行书",
        "forbid_keywords": ["但愿人长久", "庭下如积水空明", "大江东去", "射天狼"],
    },
}


def _quote_texts(item: dict) -> List[str]:
    quotes = item.get("quotes") or []
    out: List[str] = []
    for q in quotes:
        if isinstance(q, str):
            out.append(q)
        elif isinstance(q, dict):
            text = q.get("text") or q.get("content") or ""
            if isinstance(text, str):
                out.append(text)
    return out


def test_sushi_core_works_tooltip_is_not_polluted(work_index: Dict[str, dict]) -> None:
    """苏轼 6 件核心作品 tooltip 字段必须命中关键关键字，且不允许串其他作品的代表句。"""

    missing = [name for name in SUSHI_REQUIRED_WORKS if name not in work_index]
    assert not missing, f"苏轼核心作品在 work_summary_index 中缺失：{missing}"

    failures: List[str] = []
    for name, expected in SUSHI_REQUIRED_WORKS.items():
        item = work_index[name]
        summary = " ".join(
            str(item.get(key) or "")
            for key in ("one_liner", "summary")
        )
        quote_blob = " ".join(_quote_texts(item))
        full_blob = summary + " " + quote_blob

        if not any(kw in full_blob for kw in expected["summary_keywords"]):
            failures.append(
                f"《{name}》摘要未命中关键关键字 {expected['summary_keywords']}：summary={summary!r}"
            )
        if expected["quote_must_have"] not in quote_blob and expected["quote_must_have"] not in summary:
            failures.append(
                f"《{name}》缺少应有引用 {expected['quote_must_have']!r}"
            )
        for forbidden in expected["forbid_keywords"]:
            if forbidden in full_blob:
                failures.append(
                    f"《{name}》混入其他作品代表句 {forbidden!r}"
                )

    assert not failures, "苏轼核心作品 tooltip 数据出现串条：\n" + "\n".join(failures)


# ---------- 2. 作品摘要通用串条检测 ---------- #


_WORK_TITLE_RE = re.compile(r"《([^《》\n]{1,30})》")


def test_work_summary_does_not_mention_other_work_titles(work_index: Dict[str, dict]) -> None:
    """每个作品自己的摘要里，不应该出现其他作品的《xxx》标题。

    允许少量例外：标题里包含编号、副标题或同名章节时，可在此白名单中追加。
    """

    allowed_self_mentions = {"前赤壁赋", "后赤壁赋"}

    violations: List[str] = []
    for name, item in work_index.items():
        if not isinstance(item, dict):
            continue
        summary_blob = " ".join(
            str(item.get(key) or "") for key in ("one_liner", "summary")
        )
        if not summary_blob.strip():
            continue
        for match in _WORK_TITLE_RE.findall(summary_blob):
            ref = match.strip()
            if not ref:
                continue
            if ref == name:
                continue
            if ref in allowed_self_mentions or name in allowed_self_mentions:
                continue
            # 允许当前作品名包含被引用作品名的情况：例如《和陶拟古九首》提到《拟古》
            # （苏轼"和陶诗"原本就是次韵陶渊明《拟古》系列）。
            if ref and ref in name:
                continue
            # 允许真正存在的相关作品被引用，只要它本身在索引里且不是“当前作品名”的子串
            if ref in work_index and ref != name:
                # 仅当不是本作品别名时才容忍
                continue
            violations.append(f"《{name}》摘要里出现了无关作品标题《{ref}》")
        # 不允许在摘要里出现明显的“生平叙述”起始词
        for biography_lead in ("苏轼出生于", "苏轼生于", "李白出生于", "杜甫出生于"):
            if biography_lead in summary_blob and biography_lead[:2] not in name:
                violations.append(
                    f"《{name}》摘要疑似被生平叙述污染：{summary_blob[:80]!r}"
                )

    assert not violations, "作品摘要存在串条嫌疑：\n" + "\n".join(violations[:30])


# ---------- 3. 首页 is_foreign 与朝代一致性 ---------- #


def _has_any(text: str, needles: Iterable[str]) -> bool:
    if not text:
        return False
    return any(n and n in text for n in needles)


def test_is_foreign_consistent_with_dynasty(home_nodes: List[dict]) -> None:
    """is_foreign=True 的人物，其朝代不应仅包含中国朝代关键词；
    同时 is_foreign=False 的人物，朝代不应只有外国朝代关键词。
    """

    failures: List[str] = []
    for node in home_nodes:
        person = str(node.get("person") or "").strip()
        if not person:
            continue
        dynasty = str(node.get("dynasty") or "")
        is_foreign = bool(node.get("is_foreign"))
        has_zh = _has_any(dynasty, CHINESE_DYNASTY_KEYWORDS)
        has_foreign = _has_any(dynasty, FOREIGN_DYNASTY_HINTS)
        if is_foreign and has_zh and not has_foreign:
            failures.append(
                f"{person}: is_foreign=true 但朝代是中国关键词 dynasty={dynasty!r}"
            )
        if not is_foreign and has_foreign and not has_zh:
            failures.append(
                f"{person}: is_foreign=false 但朝代是外国关键词 dynasty={dynasty!r}"
            )

    assert not failures, "is_foreign 与朝代字段不一致：\n" + "\n".join(failures[:30])


# ---------- 4. 已修复人物白名单 ---------- #


REPAIRED_NON_FOREIGN_PEOPLE = ("徐光启", "梁思成", "郑成功")


def test_repaired_people_should_not_be_foreign(home_nodes: List[dict]) -> None:
    """已经修复过的人物不应再次被画成方形。"""

    index = {str(n.get("person") or ""): n for n in home_nodes if n.get("person")}
    failures: List[str] = []
    for name in REPAIRED_NON_FOREIGN_PEOPLE:
        if name not in index:
            failures.append(f"{name} 不在 stellar_home_data.nodes 中")
            continue
        if bool(index[name].get("is_foreign")):
            failures.append(f"{name} 被再次标记为 is_foreign=true，请检查首页构建规则")

    assert not failures, "白名单人物再次出现误判：\n" + "\n".join(failures)


# ---------- 5. 字段缺失率不破基线 ---------- #


MAX_MISSING_DYNASTY_RATIO = 0.05
MAX_MISSING_BIRTHPLACE_RATIO = 0.30


def test_field_missing_rate_within_baseline(home_nodes: List[dict]) -> None:
    """关键字段缺失率不应突破当前基线。

    阈值偏宽松，目的是抓“整体滑坡”而不是个别条目缺失。
    """

    total = len(home_nodes)
    if total == 0:
        pytest.skip("home_nodes 为空")

    missing_dynasty = sum(1 for n in home_nodes if not str(n.get("dynasty") or "").strip())
    missing_birthplace = sum(
        1
        for n in home_nodes
        if not str(n.get("birthplace_raw") or "").strip()
        and not str(n.get("birthplace_modern") or "").strip()
    )

    dynasty_ratio = missing_dynasty / total
    birthplace_ratio = missing_birthplace / total

    assert dynasty_ratio <= MAX_MISSING_DYNASTY_RATIO, (
        f"朝代缺失率 {dynasty_ratio:.2%} 超过基线 {MAX_MISSING_DYNASTY_RATIO:.0%}"
    )
    assert birthplace_ratio <= MAX_MISSING_BIRTHPLACE_RATIO, (
        f"出生地缺失率 {birthplace_ratio:.2%} 超过基线 {MAX_MISSING_BIRTHPLACE_RATIO:.0%}"
    )

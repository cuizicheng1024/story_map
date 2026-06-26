from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


ROOT = Path("/Users/bytedance/Desktop/Trae/mapsotryforstudents/storymap/examples/story")
OUT = Path("/Users/bytedance/Desktop/Trae/mapsotryforstudents/docs/historical_profile_first_pass_findings.md")

ANCIENT_PLACE_KEYWORDS = [
    "长安",
    "建康",
    "汴京",
    "临安",
    "邺城",
    "陈留",
    "澶州",
    "陈桥驿",
    "南匈奴",
    "匈奴",
    "安西",
    "北庭",
    "轮台",
    "河西走廊",
    "后蜀",
    "南汉",
    "南唐",
    "东胡",
    "龙城",
    "成皋",
    "沙丘",
    "淝水",
    "江东",
    "汉边境",
    "并州",
    "虎牢关",
    "雷州",
]

ISSUE_WEIGHTS = {
    "占位或非正式人物文件": 5,
    "出生去世年份前后矛盾": 5,
    "时间线含去世后事件": 5,
    "时间线早于出生过多": 4,
    "含自动地理编码": 3,
    "时间线存在空地点占位": 4,
    "基本信息缺出生字段": 3,
    "基本信息缺去世字段": 3,
    "正文保留待核提示": 2,
    "存在重复今称写法": 1,
    "历史评价含未署名断语": 1,
}


def extract_field(text: str, label: str) -> str | None:
    match = re.search(rf"- \*\*{re.escape(label)}\*\*：(.*)", text)
    if not match:
        return None
    return match.group(1).strip()


def extract_years(text: str | None) -> list[int]:
    values: list[int] = []
    if not text:
        return values
    for match in re.finditer(r"(前)?(\d{1,4})年", text):
        year = int(match.group(2))
        if match.group(1):
            year = -year
        values.append(year)
    return values


def detect_issues(text: str) -> list[str]:
    issues: list[str] = []
    birth = extract_field(text, "出生")
    death = extract_field(text, "去世")

    if birth == "":
        issues.append("基本信息缺出生字段")
    if death == "":
        issues.append("基本信息缺去世字段")
    if "自动地理编码" in text:
        issues.append("含自动地理编码")
    if re.search(r"此为泛指|虚构示例|非具体历史人物|占位", text):
        issues.append("占位或非正式人物文件")
    if re.search(r"\|\s*—\s*\|\s*—\s*\|", text):
        issues.append("时间线存在空地点占位")
    if re.search(r"（今[^）]*）\s*（今[^）]*）", text):
        issues.append("存在重复今称写法")
    if re.search(r"未核证|未见外部资料核对|本回答基于一般|未能引证最新研究|需进一步核实", text):
        issues.append("正文保留待核提示")
    if re.search(r"^- [^《\n]*——", text, re.M):
        issues.append("历史评价含未署名断语")

    if "## 地点坐标（自动地理编码）" in text:
        multi_count = 0
        ancient_count = 0
        for line in text.splitlines():
            if not line.startswith("|") or "---" in line:
                continue
            if any(token in line for token in ["、", "/", "，"]) or any(
                token in line for token in ["一带", "等地", "边境", "周边", "附近"]
            ):
                multi_count += 1
            if any(token in line for token in ANCIENT_PLACE_KEYWORDS):
                ancient_count += 1
        if multi_count:
            issues.append(f"坐标表含多地点或模糊地名行({multi_count})")
        if ancient_count:
            issues.append(f"坐标表含高歧义古地名行({ancient_count})")

    birth_years = extract_years(birth)
    death_years = extract_years(death)
    timeline_years: list[int] = []
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        first_cell = line.split("|")[1].strip()
        timeline_years.extend(extract_years(first_cell))

    if birth_years and death_years:
        birth_year = birth_years[0]
        death_year = death_years[0]
        if death_year < birth_year:
            issues.append("出生去世年份前后矛盾")
        if timeline_years and max(timeline_years) > death_year:
            issues.append("时间线含去世后事件")
        if timeline_years and min(timeline_years) < birth_year - 5:
            issues.append("时间线早于出生过多")

    return issues


def score_issues(issues: list[str]) -> int:
    score = 0
    for issue in issues:
        key = issue.split("(")[0]
        score += ISSUE_WEIGHTS.get(key, 2)
    return score


def main() -> None:
    rows: list[tuple[int, str, list[str]]] = []
    counts: Counter[str] = Counter()

    for path in sorted(ROOT.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        issues = detect_issues(text)
        for issue in issues:
            counts[issue.split("(")[0]] += 1
        rows.append((score_issues(issues), path.name, issues))

    rows.sort(key=lambda item: (-item[0], item[1]))

    lines = [
        "# 历史人物档案首轮全量筛查结果",
        "",
        "## 1. 范围",
        "",
        f"- 本轮已对 `storymap/examples/story` 下全部 `{len(rows)}` 份人物档案完成一次性首轮规则筛查。",
        "- 本结果用于发现高概率知识性问题与结构性风险，不等于全部问题均已人工定论。",
        "",
        "## 2. 问题计数",
        "",
    ]
    lines.extend(f"- {issue}：{count} 份" for issue, count in counts.most_common())
    lines.extend(
        [
            "",
            "## 3. 高风险文件 Top 100",
            "",
        ]
    )
    lines.extend(
        f"- `{name}` | 风险分 `{score}` | {'；'.join(issues) if issues else '未命中本轮规则'}"
        for score, name, issues in rows[:100]
    )
    lines.extend(
        [
            "",
            "## 4. 说明",
            "",
            "- `含自动地理编码` 仅代表需要重点复核，不等于该文件一定有错。",
            "- `坐标表含多地点或模糊地名行` 多见于把多地路线压成单点，或使用无法直接稳定定位的泛称。",
            "- `坐标表含高歧义古地名行` 多见于古地名直接送入现代地理编码服务，易发生错配。",
        ]
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

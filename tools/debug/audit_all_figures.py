#!/usr/bin/env python3
"""
全量历史人物数据审计脚本
检查 storymap/examples/story/ 目录下所有 .md 文件
"""

import os
import re
import sys
from collections import defaultdict

STORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storymap", "examples", "story")

# 标准章节模式
SECTION_PATTERNS = {
    1: re.compile(r"^##\s*一[、，,]\s*人物档案"),
    2: re.compile(r"^##\s*二[、，,]\s*人生(历程|足迹)"),
    3: re.compile(r"^##\s*三[、，,]\s*生平时间线"),
    4: re.compile(r"^##\s*四[、，,]\s*补充说明"),
}

# 关键字段名（不包含生平概述，它需要特殊处理）
KEY_FIELDS = ["姓名", "时代", "出生", "去世", "主要身份", "主要成就"]

# 中国范围
CHINA_LAT_MIN, CHINA_LAT_MAX = 18, 54
CHINA_LON_MIN, CHINA_LON_MAX = 73, 135


def find_coordinate_table_section(lines):
    """找到坐标表格的起止行号。支持多种 section header。"""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s*地点坐标", stripped):
            return i
    return None


def parse_markdown_table(lines, start_line):
    """
    从 start_line 开始解析 markdown 表格。
    支持一个坐标 section 下包含多个子表（用 ---|---|--- 分隔）。
    返回: list of dicts, 每个 dict 包含表头对应的列值。
    """
    # 跳过 section header 行
    i = start_line + 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    if i >= len(lines):
        return [], i

    # 读取表头
    header_line = lines[i].strip()
    if not header_line.startswith("|"):
        return [], i
    headers = [h.strip() for h in header_line.split("|")[1:-1]]
    i += 1

    # 跳过分隔行
    if i < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i].strip()):
        i += 1

    rows = []
    current_headers = list(headers)

    # 预扫描：检测后续是否有子表分隔及列数变化
    def _detect_columns(line):
        """解析一行的单元格列表。"""
        return [c.strip() for c in line.strip().split("|")[1:-1]]

    def _is_separator(line):
        return bool(re.match(r"^\|[\s\-:|]+\|$", line.strip()))

    while i < len(lines):
        row_line = lines[i].strip()
        if not row_line.startswith("|"):
            break

        # 跳过分隔行
        if _is_separator(row_line):
            # 向前看：分隔行之后是否是新子表（列数不同）
            peek = i + 1
            while peek < len(lines):
                peek_line = lines[peek].strip()
                if not peek_line.startswith("|"):
                    break
                if _is_separator(peek_line):
                    peek += 1
                    continue
                peek_cells = _detect_columns(peek_line)
                if len(peek_cells) != len(current_headers) and len(peek_cells) >= 2:
                    # 列数变化，推断新的表头
                    if len(peek_cells) == 3:
                        # 常见模式: | 现称 | 纬度 | 经度 |
                        current_headers = ["现称", "纬度", "经度"]
                    elif len(peek_cells) == 4:
                        # 常见模式: | 现称 | 现代搜索地名 | 纬度 | 经度 |
                        current_headers = ["现称", "现代搜索地名", "纬度", "经度"]
                    else:
                        current_headers = [f"col_{j}" for j in range(len(peek_cells))]
                    i = peek
                    break
                else:
                    i = peek
                    break
            else:
                i += 1
            continue

        cells = _detect_columns(row_line)
        if len(cells) == len(current_headers):
            row_dict = {current_headers[j]: cells[j] for j in range(len(current_headers))}
            rows.append(row_dict)
        elif len(cells) > 0:
            # 尝试匹配
            row_dict = {}
            for j in range(min(len(current_headers), len(cells))):
                row_dict[current_headers[j]] = cells[j]
            rows.append(row_dict)
        i += 1

    return rows, i


def find_column_index(headers, candidates):
    """在 headers 中找到第一个匹配 candidates 的列索引。"""
    for i, h in enumerate(headers):
        for c in candidates:
            if c in h:
                return i
    return None


def extract_coordinates(rows):
    """从表格行中提取坐标列表。返回 [(现称, lat, lon, raw_lat_str, raw_lon_str), ...]"""
    if not rows:
        return []

    headers = list(rows[0].keys())
    name_col = find_column_index(headers, ["现称"])
    lat_col = find_column_index(headers, ["纬度", "lat"])
    lon_col = find_column_index(headers, ["经度", "lon", "lng"])

    if lat_col is None or lon_col is None:
        return []

    coords = []
    for row in rows:
        name = row.get(headers[name_col], "") if name_col is not None else ""
        lat_str = row.get(headers[lat_col], "").strip()
        lon_str = row.get(headers[lon_col], "").strip()
        coords.append((name, lat_str, lon_str))
    return coords


def try_parse_float(s):
    """尝试将字符串解析为 float，失败返回 None。"""
    if not s or s.strip() == "":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_key_field_value(content, field_name):
    """从人物档案基本信息区域提取字段值。支持单行和多行值。"""
    # 匹配 `- **字段名**：值` 或 `- **字段名**:值`
    # 多行值：后续行以缩进开头（空格或 -）且不是新字段
    pattern = rf"-\s*\*+\s*{re.escape(field_name)}\s*\*+\s*[：:]\s*(.*?)(?=\n-\s*\*+\s*\S|\n###|\n##|\n\n\n|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        value = match.group(1).strip()
        # 清理多行值中的前导空白
        value = re.sub(r"\n\s+", " ", value)
        return value if value else None
    return None


def find_all_sections(lines):
    """找到所有 ## 级别的章节标题及其行号。返回 [(行号, 标题), ...]"""
    sections = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s", stripped):
            sections.append((i, stripped))
    return sections


def audit_file(filepath):
    """审计单个 .md 文件，返回结果字典。"""
    filename = os.path.basename(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    results = {
        "file": filename,
        "issues": [],
    }

    # ========== 1. 轨迹点数量统计 ==========
    coord_section_start = find_coordinate_table_section(lines)
    coord_rows = []
    coord_count = 0
    if coord_section_start is not None:
        coord_rows, _ = parse_markdown_table(lines, coord_section_start)
        # 过滤掉可能重复的分隔行
        valid_rows = []
        for r in coord_rows:
            if set(r.keys()) == {"---"} or all(v == "---" for v in r.values()):
                continue
            valid_rows.append(r)
        coord_count = len(valid_rows)
    results["coord_count"] = coord_count
    if coord_count <= 2:
        results["issues"].append(f"[轨迹点过少] 坐标表仅有 {coord_count} 个轨迹点")

    # ========== 2. 坐标缺失检查 ==========
    coords = extract_coordinates(coord_rows)
    for name, lat_str, lon_str in coords:
        lat = try_parse_float(lat_str)
        lon = try_parse_float(lon_str)
        if lat is None or lon is None:
            results["issues"].append(f"[坐标缺失] 地点 '{name}' 坐标为空或无法解析 (lat='{lat_str}', lon='{lon_str}')")
        elif lat == 0.0 and lon == 0.0:
            results["issues"].append(f"[坐标缺失] 地点 '{name}' 坐标为 (0, 0)，明显错误")

    # ========== 3. 章节编号检查 ==========
    found_sections = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        for num, pattern in SECTION_PATTERNS.items():
            if pattern.match(stripped):
                found_sections[num] = stripped
                break

    # 检查使用了编号的章节（有编号则必须连续）
    numbered_sections_present = sorted(found_sections.keys())
    if numbered_sections_present:
        expected = list(range(1, max(numbered_sections_present) + 1))
        missing = [n for n in expected if n not in found_sections]
        if missing:
            results["issues"].append(
                f"[章节缺失] 缺少编号为 {missing} 的章节（现有: {numbered_sections_present}）"
            )
        # 检查顺序
        for n in numbered_sections_present:
            expected_pattern = SECTION_PATTERNS[n]
            actual = found_sections[n]
            # 只检查编号是否在正确位置
            pass

    # 也检查非编号格式（无编号的章节），看是否有格式混用
    all_sections = find_all_sections(lines)
    section_titles = [s[1] for s in all_sections]
    has_numbered = any(re.match(r"^##\s*[一二三四五六七八九十]、", s) for s in section_titles)
    has_unnumbered = any(re.match(r"^##\s*(人物档案|人生历程|生平时间线|补充说明|人生足迹)", s) for s in section_titles)
    if has_numbered and has_unnumbered:
        results["issues"].append("[章节混用] 同时存在编号章节和无编号章节，格式不统一")

    # ========== 4. 空字段检查 ==========
    # 提取人物档案区域（用 negative lookbehind 确保 ## 不是 ### 的一部分）
    profile_match = re.search(
        r"(?:##\s*(?:一[、，,]\s*)?人物档案.*?)(?=(?<!#)##\s|\Z)", content, re.DOTALL
    )
    profile_text = profile_match.group(0) if profile_match else content

    for field in KEY_FIELDS:
        value = extract_key_field_value(profile_text, field)
        if value is None:
            results["issues"].append(f"[空字段] 关键字段 '{field}' 未找到或格式异常")
        elif value.strip() == "" or value.strip() in ("无", "暂无", "待补充", "不详", "未知"):
            results["issues"].append(f"[空字段] 关键字段 '{field}' 值为空: '{value}'")

    # 生平概述特殊处理 — 可能在 - **生平概述**：字段 或 ### 生平概述 小节
    overview_found = False
    # 先检查 bullet 格式
    if extract_key_field_value(profile_text, "生平概述"):
        overview_found = True
    # 再检查 ### 小节格式
    if not overview_found:
        overview_match = re.search(
            r"###\s*生平概述\s*\n(.+?)(?=\n(?<!#)##|\n---|\Z)", content, re.DOTALL
        )
        if overview_match and overview_match.group(1).strip():
            overview_found = True
    if not overview_found:
        results["issues"].append("[空字段] 关键字段 '生平概述' 未找到内容")

    # ========== 5. 坐标合理性检查（中国范围） ==========
    # 判断人物是否是中国人物
    is_chinese_figure = False
    era = extract_key_field_value(profile_text, "时代")
    if era:
        # 使用更精确的模式匹配，避免子串误匹配（如"公元前"中的"元"匹配元朝）
        chinese_era_patterns = [
            r"春秋", r"战国", r"秦朝|秦国|秦代|秦末|先秦", r"汉朝|汉代|汉末|东汉|西汉|后汉|汉初",
            r"三国", r"晋朝|晋代|东晋|西晋|晋末", r"南北朝",
            r"隋朝|隋代|隋末", r"唐朝|唐代|唐末|盛唐|晚唐",
            r"五代(?!十国)", r"宋朝|宋代|北宋|南宋|宋末|宋初", r"辽朝|辽代|辽国",
            r"金朝|金代|金国|金末", r"元朝|元代|元末|元初", r"明朝|明代|明末|南明|明初",
            r"清朝|清代|清末|后金|清初", r"民国", r"商朝|商代|商周",
            r"周朝|西周|东周", r"夏朝|夏代",
            r"中华人民共和国", r"太平天国",
            r"现当代", r"近现代",
            # 单独"中国"只在没有其他修饰时匹配
            r"(?:^|[（(])中国[）)]|中国$",
        ]
        for pattern in chinese_era_patterns:
            if re.search(pattern, era):
                is_chinese_figure = True
                break

    for name, lat_str, lon_str in coords:
        lat = try_parse_float(lat_str)
        lon = try_parse_float(lon_str)
        if lat is None or lon is None:
            continue
        # 只检查中国人物或坐标不在全球常规范围的情况
        if is_chinese_figure:
            if not (CHINA_LAT_MIN <= lat <= CHINA_LAT_MAX and CHINA_LON_MIN <= lon <= CHINA_LON_MAX):
                results["issues"].append(
                    f"[坐标越界] 中国人物 '{name}' 坐标 ({lat}, {lon}) 不在中国范围 "
                    f"(纬度 {CHINA_LAT_MIN}-{CHINA_LAT_MAX}, 经度 {CHINA_LON_MIN}-{CHINA_LON_MAX})"
                )

    # ========== 6. 重复位置检查 ==========
    lat_lon_seen = {}
    for name, lat_str, lon_str in coords:
        lat = try_parse_float(lat_str)
        lon = try_parse_float(lon_str)
        if lat is None or lon is None:
            continue
        key = (round(lat, 4), round(lon, 4))
        if key in lat_lon_seen:
            results["issues"].append(
                f"[重复坐标] '{name}' 与 '{lat_lon_seen[key]}' 坐标相同 ({lat}, {lon})"
            )
        else:
            lat_lon_seen[key] = name

    return results


def main():
    if not os.path.isdir(STORY_DIR):
        print(f"错误: 目录不存在: {STORY_DIR}")
        sys.exit(1)

    md_files = sorted([
        f for f in os.listdir(STORY_DIR) if f.endswith(".md")
    ])

    print(f"=== 全量历史人物数据审计 ===\n")
    print(f"扫描目录: {STORY_DIR}")
    print(f"文件总数: {len(md_files)}\n")

    all_results = []
    for md_file in md_files:
        filepath = os.path.join(STORY_DIR, md_file)
        result = audit_file(filepath)
        all_results.append(result)

    # ========== 汇总输出 ==========

    # 1. 轨迹点数量统计
    print("=" * 70)
    print("1. 轨迹点数量统计")
    print("=" * 70)
    low_count_files = [r for r in all_results if r["coord_count"] <= 2]
    if low_count_files:
        print(f"\n轨迹点 ≤ 2 的人物 ({len(low_count_files)} 个):")
        for r in sorted(low_count_files, key=lambda x: x["coord_count"]):
            print(f"  - {r['file']}: {r['coord_count']} 个轨迹点")
    else:
        print("\n所有人物轨迹点均 ≥ 3 个。")

    # 分布统计
    coord_distribution = defaultdict(int)
    for r in all_results:
        coord_distribution[r["coord_count"]] += 1
    print(f"\n轨迹点分布:")
    for k in sorted(coord_distribution.keys()):
        print(f"  {k} 个点: {coord_distribution[k]} 人")

    # 2. 坐标缺失
    print("\n" + "=" * 70)
    print("2. 坐标缺失检查")
    print("=" * 70)
    coord_issue_files = [r for r in all_results if any("坐标缺失" in iss for iss in r["issues"])]
    if coord_issue_files:
        print(f"\n存在坐标缺失的文件 ({len(coord_issue_files)} 个):")
        for r in coord_issue_files:
            print(f"  - {r['file']}:")
            for iss in r["issues"]:
                if "坐标缺失" in iss:
                    print(f"      {iss}")
    else:
        print("\n未发现坐标缺失问题。")

    # 3. 章节编号检查
    print("\n" + "=" * 70)
    print("3. 章节编号检查")
    print("=" * 70)
    section_issue_files = [r for r in all_results if any("章节" in iss for iss in r["issues"])]
    if section_issue_files:
        print(f"\n存在章节问题的文件 ({len(section_issue_files)} 个):")
        for r in section_issue_files:
            print(f"  - {r['file']}:")
            for iss in r["issues"]:
                if "章节" in iss:
                    print(f"      {iss}")
    else:
        print("\n未发现章节编号问题。")

    # 4. 空字段检查
    print("\n" + "=" * 70)
    print("4. 空字段检查")
    print("=" * 70)
    empty_field_files = [r for r in all_results if any("空字段" in iss for iss in r["issues"])]
    if empty_field_files:
        print(f"\n存在空字段的文件 ({len(empty_field_files)} 个):")
        for r in empty_field_files:
            print(f"  - {r['file']}:")
            for iss in r["issues"]:
                if "空字段" in iss:
                    print(f"      {iss}")
    else:
        print("\n未发现空字段问题。")

    # 5. 坐标合理性
    print("\n" + "=" * 70)
    print("5. 坐标合理性检查（中国范围）")
    print("=" * 70)
    out_of_range_files = [r for r in all_results if any("坐标越界" in iss for iss in r["issues"])]
    if out_of_range_files:
        print(f"\n坐标越界的人物 ({len(out_of_range_files)} 个):")
        for r in out_of_range_files:
            print(f"  - {r['file']}:")
            for iss in r["issues"]:
                if "坐标越界" in iss:
                    print(f"      {iss}")
    else:
        print("\n未发现坐标越界问题。")

    # 6. 重复位置
    print("\n" + "=" * 70)
    print("6. 重复位置检查")
    print("=" * 70)
    dup_files = [r for r in all_results if any("重复坐标" in iss for iss in r["issues"])]
    if dup_files:
        print(f"\n存在重复坐标的文件 ({len(dup_files)} 个):")
        for r in dup_files:
            print(f"  - {r['file']}:")
            for iss in r["issues"]:
                if "重复坐标" in iss:
                    print(f"      {iss}")
    else:
        print("\n未发现重复坐标问题。")

    # 汇总
    print("\n" + "=" * 70)
    print("审计汇总")
    print("=" * 70)
    total_issues = sum(len(r["issues"]) for r in all_results)
    files_with_issues = sum(1 for r in all_results if r["issues"])
    print(f"  文件总数: {len(md_files)}")
    print(f"  有问题文件数: {files_with_issues}")
    print(f"  问题总数: {total_issues}")
    print(f"  轨迹点 ≤ 2: {len(low_count_files)} 人")
    print(f"  坐标缺失: {len(coord_issue_files)} 人")
    print(f"  章节问题: {len(section_issue_files)} 人")
    print(f"  空字段: {len(empty_field_files)} 人")
    print(f"  坐标越界: {len(out_of_range_files)} 人")
    print(f"  重复坐标: {len(dup_files)} 人")

    # 无问题文件列表
    clean_files = [r for r in all_results if not r["issues"]]
    if clean_files:
        print(f"\n  完全无问题文件 ({len(clean_files)} 个):")
        for r in clean_files:
            print(f"    - {r['file']}")

    print("\n审计完成。")


if __name__ == "__main__":
    main()

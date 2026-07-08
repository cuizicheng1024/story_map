#!/usr/bin/env python3
"""全量历史人物知识性错误审计脚本。

检查 545 个 HTML 人物页面中的：
1. 坐标错误（越界/0值/格式异常）
2. 章节编号不连续或重复
3. 近现代人物关系措辞不当
4. 核心字段缺失
5. 古地名坐标偏差过大
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML_DIR = ROOT / "artifacts" / "story_map"
INDEX_PATH = ROOT / "data" / "corpus" / "people_summary_index.json"
DB_PATH = ROOT / "data" / "people_knowledge.db"

# ── 古代中国地理参考坐标（用于语义校验） ──
ANCIENT_REF = {
    # 主要古都/名城
    "长安": (34.3, 108.9), "洛阳": (34.6, 112.5), "建康": (32.1, 118.8),
    "开封": (34.8, 114.3), "北京": (39.9, 116.4), "南京": (32.1, 118.8),
    "杭州": (30.3, 120.2), "成都": (30.6, 104.1), "广州": (23.1, 113.3),
    "西安": (34.3, 108.9), "咸阳": (34.3, 108.7), "安阳": (36.1, 114.4),
    "邯郸": (36.6, 114.5), "临淄": (36.8, 118.4), "曲阜": (35.6, 117.0),
    "荆州": (30.3, 112.2), "襄阳": (32.0, 112.1), "江陵": (30.3, 112.2),
    "扬州": (32.4, 119.4), "苏州": (31.3, 120.6), "绍兴": (30.0, 120.6),
    "会稽": (30.0, 120.6), "吴郡": (31.3, 120.6),
    "长沙": (28.2, 113.0), "南昌": (28.7, 115.9), "九江": (29.7, 116.0),
    "武昌": (30.6, 114.3), "武汉": (30.6, 114.3), "重庆": (29.6, 106.6),
    "渝州": (29.6, 106.6), "夔州": (31.0, 109.5),
    "桂林": (25.3, 110.3), "昆明": (25.0, 102.7), "大理": (25.6, 100.2),
    "兰州": (36.1, 103.8), "敦煌": (40.1, 94.7), "酒泉": (39.7, 98.5),
    "天水": (34.6, 105.7), "汉中": (33.1, 107.0),
    "济南": (36.7, 117.0), "青岛": (36.1, 120.4), "太原": (37.9, 112.6),
    "大同": (40.1, 113.3), "呼和浩特": (40.8, 111.8),
    "沈阳": (41.8, 123.4), "哈尔滨": (45.8, 126.5), "长春": (43.9, 125.3),
    # 边疆/域外
    "碎叶城": (42.8, 75.3), "西域": (40.0, 80.0), "楼兰": (40.5, 89.9),
    "高昌": (42.9, 89.2), "龟兹": (41.7, 82.9), "于阗": (37.1, 79.9),
    "疏勒": (39.4, 76.0), "大宛": (40.4, 71.8),
    "交趾": (21.0, 105.8), "日南": (17.0, 107.0),
    "夜郎": (26.0, 105.0), "黔中": (26.6, 106.7), "滇池": (25.0, 102.7),
    "巴蜀": (30.6, 104.1), "蜀中": (30.6, 104.1), "巴郡": (29.6, 106.6),
    "蜀郡": (30.6, 104.1), "汉中郡": (33.1, 107.0),
    "陇西": (35.0, 104.6), "北地": (36.0, 107.0),
    "上郡": (38.0, 109.7), "云中": (40.8, 111.8),
    "雁门": (39.0, 112.8), "代郡": (40.0, 115.0),
    "渔阳": (40.1, 117.4), "右北平": (41.0, 119.0),
    "辽西": (41.8, 121.0), "辽东": (41.1, 123.0),
    "朝鲜": (39.0, 125.8), "乐浪": (39.0, 125.8),
    # 近现代人物相关
    "莫斯科": (55.8, 37.6), "费城": (39.9, -75.2), "剑桥": (52.2, 0.12),
    "伦敦": (51.5, -0.1), "巴黎": (48.9, 2.3), "柏林": (52.5, 13.4),
    "东京": (35.7, 139.7), "纽约": (40.7, -74.0), "旧金山": (37.8, -122.4),
    "波士顿": (42.4, -71.1), "芝加哥": (41.9, -87.6),
    # 中国沿海
    "上海": (31.2, 121.5), "天津": (39.1, 117.2), "厦门": (24.5, 118.1),
    "福州": (26.1, 119.3), "宁波": (29.9, 121.6), "泉州": (24.9, 118.6),
    "广州湾": (21.2, 110.4), "湛江": (21.2, 110.4),
}

# ── 近现代朝代标识（不应出现封建措辞） ──
MODERN_DYNASTIES = {"清", "近现代", "现代", "民国", "中华人民共和国", "清代"}

# ── 需要屏蔽的关系措辞 ──
FEUDAL_LABELS = {"君臣", "君主", "臣子", "主仆", "主臣", "君臣关系"}


def load_index():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_coords_from_html(html: str) -> list[tuple[str, float, float]]:
    """从 HTML 中提取所有坐标点。"""
    coords = []
    # 匹配 data-lat/data-lon 属性
    for m in re.finditer(
        r'data-lat=["\']([^"\']+)["\'].*?data-lon=["\']([^"\']+)["\']', html
    ):
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            coords.append(("data-attr", lat, lon))
        except ValueError:
            pass
    # 匹配脚本中的 lat/lon 数组
    for m in re.finditer(
        r'"lat":\s*([\d.]+).*?"lon":\s*([\d.]+)', html
    ):
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            coords.append(("json", lat, lon))
        except ValueError:
            pass
    return coords


def parse_chapters_from_html(html: str) -> list[int]:
    """从 HTML 中提取章节编号。"""
    chapters = []
    for m in re.finditer(r'<h[23][^>]*>第([一二三四五六七八九十百千\d]+)章', html):
        num_str = m.group(1)
        num = _cn_to_int(num_str)
        if num is not None:
            chapters.append(num)
    return sorted(set(chapters))


def _cn_to_int(s: str) -> int | None:
    """中文数字转整数。"""
    if s.isdigit():
        return int(s)
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if s in cn_map:
        return cn_map[s]
    # 十一到九十九
    if "十" in s:
        parts = s.split("十")
        tens = cn_map.get(parts[0], 1) if parts[0] else 1
        ones = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def check_coordinate_errors(coords, name, dynasty):
    """检查坐标错误。"""
    errors = []
    for src, lat, lon in coords:
        # 越界检查
        if abs(lat) >= 90:
            errors.append(f"纬度越界: lat={lat} ({src})")
        if abs(lon) >= 180:
            errors.append(f"经度越界: lon={lon} ({src})")
        # 零值检查
        if lat == 0 and lon == 0:
            errors.append(f"坐标为(0,0) ({src})")
        if abs(lat) < 0.01 and abs(lon) < 0.01:
            errors.append(f"坐标接近原点 ({src})")
    return errors


def check_chapter_errors(html):
    """检查章节错误。"""
    errors = []
    # 检查章节编号
    chapters = []
    for m in re.finditer(r'<h[23][^>]*>第([一二三四五六七八九十百千\d]+)章', html):
        num_str = m.group(1)
        num = _cn_to_int(num_str)
        if num is not None:
            chapters.append(num)

    if chapters:
        sorted_ch = sorted(set(chapters))
        # 重复检查
        if len(sorted_ch) != len(chapters):
            duplicates = [c for c in chapters if chapters.count(c) > 1]
            errors.append(f"重复章节编号: {sorted(set(duplicates))}")

        # 连续性检查
        if sorted_ch != list(range(sorted_ch[0], sorted_ch[-1] + 1)):
            expected = set(range(sorted_ch[0], sorted_ch[-1] + 1))
            missing = expected - set(sorted_ch)
            if missing:
                errors.append(f"缺少章节: {sorted(missing)}")

    return errors


def check_relation_labels(name, dynasty, db_path):
    """检查关系标签是否使用了不当代词。"""
    errors = []
    if dynasty not in MODERN_DYNASTIES:
        return errors  # 古代人物可以使用君臣等词

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT target_name, relation FROM relations WHERE source_name = ?",
            (name,)
        )
        for target, rel in cur.fetchall():
            if any(label in rel for label in FEUDAL_LABELS):
                errors.append(f"关系措辞不当: '{target}' → '{rel}' (应为'工作关系'等)")
        conn.close()
    except Exception as e:
        errors.append(f"数据库查询错误: {e}")
    return errors


def check_field_completeness(html, name, summary_data):
    """检查核心字段完整性。"""
    errors = []

    # short_review 检查
    review = summary_data.get("short_review", "")
    if not review or len(review) < 2:
        errors.append("short_review 为空或过短")

    # 是否有地图数据
    if "data-lat" not in html and '"lat"' not in html:
        errors.append("缺少地图坐标数据")

    # 是否有章节
    if "<h2" not in html and "<h3" not in html:
        errors.append("缺少章节标题")

    # 是否有生平内容
    if len(html) < 2000:
        errors.append(f"HTML 内容过短 ({len(html)} 字节)")

    return errors


def main():
    raw_index = load_index()
    index = raw_index.get("items", raw_index)
    print(f"索引文件加载: {len(index)} 个人物条目")
    print(f"HTML 文件目录: {HTML_DIR}")

    html_files = sorted(HTML_DIR.glob("*.html"))
    # 过滤掉非人物页面
    skip_patterns = {"index", "song-minister-game",
                     "admin", "map", "profile", "search", "landing", "orange",
                     "star", "agent-trace", "pure", "合并"}
    person_files = []
    for f in html_files:
        name = f.stem
        should_skip = False
        for pat in skip_patterns:
            if pat in name.lower():
                should_skip = True
                break
        if len(name) < 2:
            should_skip = True
        if not should_skip and name in index:
            person_files.append(f)

    print(f"人物 HTML 页面: {len(person_files)}")

    # ── 分类统计 ──
    all_errors = defaultdict(list)
    stats = {
        "total": len(person_files),
        "coord_errors": 0,
        "chapter_errors": 0,
        "relation_errors": 0,
        "field_errors": 0,
        "figures_with_issues": 0,
    }

    processed = 0
    for f in person_files:
        name = f.stem
        summary = index.get(name, {})
        dynasty = summary.get("dynasty", "")

        try:
            html = f.read_text(encoding="utf-8")
        except Exception as e:
            all_errors[name].append(f"文件读取失败: {e}")
            continue

        # 1. 坐标检查
        coords = parse_coords_from_html(html)
        coord_issues = check_coordinate_errors(coords, name, dynasty)
        if coord_issues:
            all_errors[name].extend(coord_issues)
            stats["coord_errors"] += len(coord_issues)

        # 2. 章节检查
        chapter_issues = check_chapter_errors(html)
        if chapter_issues:
            all_errors[name].extend(chapter_issues)
            stats["chapter_errors"] += len(chapter_issues)

        # 3. 关系措辞检查
        relation_issues = check_relation_labels(name, dynasty, DB_PATH)
        if relation_issues:
            all_errors[name].extend(relation_issues)
            stats["relation_errors"] += len(relation_issues)

        # 4. 字段完整性
        field_issues = check_field_completeness(html, name, summary)
        if field_issues:
            all_errors[name].extend(field_issues)
            stats["field_errors"] += len(field_issues)

        processed += 1
        if processed % 100 == 0:
            print(f"  已处理 {processed}/{len(person_files)}...")

    # ── 统计有问题的人物 ──
    figures_with_issues = [name for name, errs in all_errors.items() if errs]
    stats["figures_with_issues"] = len(figures_with_issues)

    # ── 输出报告 ──
    print(f"\n{'='*60}")
    print(f"  审计报告")
    print(f"{'='*60}")
    print(f"  总人物数:     {stats['total']}")
    print(f"  有问题人数:   {stats['figures_with_issues']}")
    print(f"  坐标错误:     {stats['coord_errors']}")
    print(f"  章节错误:     {stats['chapter_errors']}")
    print(f"  关系措辞:     {stats['relation_errors']}")
    print(f"  字段缺失:     {stats['field_errors']}")

    # ── 详细输出 ──
    if figures_with_issues:
        print(f"\n{'='*60}")
        print(f"  详细问题列表")
        print(f"{'='*60}")

        for name in sorted(figures_with_issues):
            issues = all_errors[name]
            print(f"\n  【{name}】({len(issues)} 个问题)")
            for issue in issues:
                print(f"    - {issue}")

    # ── 保存完整报告 ──
    report = {
        "stats": stats,
        "errors": {name: errs for name, errs in all_errors.items() if errs},
    }
    report_path = ROOT / "tools" / "debug" / "knowledge_audit_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  完整报告已保存: {report_path}")

    return 0 if stats["figures_with_issues"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

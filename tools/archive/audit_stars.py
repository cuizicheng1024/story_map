"""找出不够格的近现代人物"""
import json

with open("data/corpus/people_summary_index.json", encoding="utf-8") as f:
    psi = json.load(f)
items = psi.get("items", {})

suspect = []
for name, info in items.items():
    ident = info.get("identities", "")
    intro = info.get("intro", "")
    status = info.get("status", "")
    ach = info.get("achievements", "")
    a_len = len(ach)

    # (A) achievements = "" or very short + not a major figure
    if a_len < 15:
        major_kw = [
            "数学", "物理", "化学", "生物", "天文学", "地质", "哲学",
            "皇帝", "国王", "总统", "主席", "总理", "将军", "元帅",
            "革命", "起义", "创立", "开辟", "统一", "发明"
        ]
        if not any(k in ident + status + intro for k in major_kw):
            suspect.append(("empty_ach", name, ident[:60], a_len))

    # (B) 教研室主任 / 中学教师 / 教材编者（除非是真正的大教育家）
    if ("教研室" in ident or "教研员" in ident or "特级教师" in ident):
        if "院士" not in ident and "奠基" not in status:
            suspect.append(("teacher", name, ident[:60], a_len))

    # (C) 政治人物但成就为空或仅一句话
    if "政治" in ident and a_len < 30:
        suspect.append(("minor_politician", name, ident[:60], a_len))

    # (D) 劳动模范 / 道德模范（非科学家/非艺术家）
    if ("劳动模范" in ident or "道德模范" in ident or "先进工作者" in ident):
        suspect.append(("model_worker", name, ident[:60], a_len))

    # (E) 打乒乓球 / 体育明星
    if "体育" in ident or "运动员" in ident:
        suspect.append(("sports", name, ident[:60], a_len))

print("=== 建议删除 / 重新评估 ===")
for category, name, ident, a_len in sorted(suspect):
    print(f"  [{category}] {name}: {ident} (ach={a_len}ch)")

print(f"\n总计: {len(suspect)} 人")

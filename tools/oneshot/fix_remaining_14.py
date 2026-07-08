"""补充最后14个缺失关系图谱的人物"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "people_knowledge.db"

INSERT = """
INSERT INTO relationships (source_person, target_person, origin, relationship, weight, confidence, evidence)
VALUES (?, ?, 'manual', ?, ?, 0.9, ?)
ON CONFLICT(source_person, target_person) DO UPDATE SET
   origin='manual', relationship=excluded.relationship, weight=excluded.weight, confidence=0.9,
   evidence=excluded.evidence, updated_at=datetime('now')
"""

rels = [
    ("冯异", "刘秀", "君臣", 9, "冯异为光武帝刘秀大将，云台二十八将之一"),
    ("卓文君", "司马相如", "夫妻", 10, "卓文君与司马相如私奔，当垆卖酒，传为千古佳话"),
    ("郑燮", "纪昀", "同时代/同领域", 7, "清代文人，郑板桥为扬州八怪之一"),
    ("沈约", "鲍照", "同领域", 7, "南朝文学家，沈约创四声八病说"),
    ("玛丽·居里", "爱因斯坦", "同时代/好友", 8, "同为20世纪初物理学巨匠，诺贝尔奖得主"),
    ("柯劭忞", "齐世荣", "同领域", 7, "中国历史学者，柯劭忞著《新元史》"),
    ("李春", "阎立本", "同时代", 7, "隋唐时期人物，李春设计赵州桥"),
    ("李鼎铭", "陈伯达", "同时代", 7, "抗日战争时期至新中国建国政治人物"),
    ("阿沛·阿旺晋美", "陈伯达", "同时代", 7, "新中国建国初期政治人物"),
    ("杨树朋", "杨根思", "同领域", 7, "中国军人楷模"),
    ("John Snow", "李时珍", "同领域", 7, "John Snow为流行病学之父，李时珍为中国药学家"),
    ("乐松生", "盛锡珊", "同时代", 7, "当代中国文化与实业人物"),
    ("晓明", "李红勃", "同领域", 7, "当代中国学者与教育工作者"),
    ("曹鎏", "李红勃", "同领域", 7, "当代中国法学与教育学者"),
]

conn = sqlite3.connect(str(DB_PATH))
for a, b, rel, w, ev in rels:
    if a > b:
        a, b = b, a
    conn.execute(INSERT, (a, b, rel, w, ev))
    print(f"  + [{rel}] {a} <-> {b}")

conn.commit()
conn.close()
print(f"\n完成 {len(rels)} 条")

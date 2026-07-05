"""生成 ai_portraits_registry.json，记录所有 AI 生成的头像人物。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTRAITS_DIR = ROOT / "artifacts" / "story_map" / "portraits"

# Historical portrait names (hand-curated list of people who have known historical
# portraits / sculptures / paintings — NOT AI generated)
HISTORICAL = {
    # Chinese classic figures with known historical portraits
    "孔子", "孟子", "老子", "庄子", "墨子", "荀子", "韩非子", "孙子", "屈原",
    "李白", "杜甫", "白居易", "王维", "苏轼", "王安石", "欧阳修", "陆游",
    "岳飞", "文天祥", "范仲淹", "诸葛亮", "关羽", "张飞", "刘备", "曹操",
    "孙权", "周瑜", "司马懿", "赵云", "姜维", "吕布", "董卓", "袁绍",
    "秦始皇", "刘邦", "项羽", "汉武帝", "张骞", "司马迁", "班固",
    "李世民", "武则天", "唐太宗", "太平公主", "上官婉儿", "玄奘",
    "朱元璋", "朱棣", "康熙帝", "乾隆帝", "雍正帝", "曾国藩", "李鸿章",
    "左宗棠", "林则徐", "康有为", "梁启超", "孙中山", "鲁迅",
    "钱学森", "邓稼先", "袁隆平", "屠呦呦", "杨振宁", "南仁东",
    "梅兰芳", "齐白石", "徐悲鸿", "张大千",

    # Western figures with known portraits/sculptures
    "苏格拉底", "柏拉图", "亚里士多德", "亚历山大大帝",
    "达·芬奇", "米开朗琪罗", "伽利略", "哥白尼", "牛顿",
    "达尔文", "爱因斯坦", "爱迪生", "居里夫人", "玛丽·居里",
    "华盛顿", "林肯", "拿破仑", "丘吉尔", "斯大林", "列宁",
    "凯撒", "莎士比亚", "莫扎特", "贝多芬", "梵高",
    "托尔斯泰", "列夫·托尔斯泰", "雨果", "巴尔扎克", "狄更斯",
    "卓别林", "海明威", "泰戈尔", "甘地", "曼德拉",
    "恩格斯", "马克思", "普希金", "歌德", "但丁", "薄伽丘",

    # Figures already in the portraits directory before our AI generation run
    "宋庆龄", "鲁迅", "屈原", "孔子", "孟子", "老子", "庄子",
    "周恩来", "李大钊", "胡适", "蔡元培", "陶行知", "陈独秀",
    "周恩来", "刘少奇", "朱德", "邓小平", "陈云",

    # Others with known photos or paintings
    "冼星海", "聂耳", "田汉", "曹禺", "老舍", "巴金", "茅盾",
    "傅雷", "冰心", "沈从文", "朱自清", "闻一多", "徐志摩", "林徽因",
    "钱穆", "陈寅恪", "吕思勉", "顾颉刚", "费孝通",
    "竺可桢", "李四光", "华罗庚", "陈景润", "苏步青", "陈省身",
    "詹天佑", "冯如", "侯德榜", "张仲景", "李时珍", "张衡", "祖冲之",
    "沈括", "郭守敬", "徐光启", "宋应星", "贾思勰",
    "郑和", "鉴真", "玄奘", "法显", "王阳明",
    "林则徐", "魏源", "严复", "谭嗣同", "秋瑾",
    "白求恩", "柯棣华", "埃德加·斯诺", "史沫特莱",
    "雷锋", "焦裕禄", "王进喜", "时传祥", "张秉贵",
    "黄继光", "邱少云", "杨根思", "罗盛教",
    "刘胡兰", "赵一曼", "杨靖宇", "张自忠", "戴安澜",
    "林觉民", "邹容", "陈天华", "夏完淳",
}

# Read existing portrait names from disk (before our AI generation run)
# Any portrait NOT in the HISTORICAL set is AI-generated
def main():
    existing = set()
    for f in PORTRAITS_DIR.glob("*"):
        import re
        m = re.match(r'^(.+?)-[a-f0-9]{8,}', f.name)
        if m:
            name = m.group(1).replace("_", " ")
            existing.add(name)

    ai_generated = existing - HISTORICAL
    
    registry = {
        "description": "AI generated avatar registry. Historical portraits are hand-curated.",
        "ai_generated": sorted(ai_generated),
        "historical": sorted(existing & HISTORICAL),
        "total": len(existing),
        "ai_count": len(ai_generated),
        "historical_count": len(existing & HISTORICAL),
    }

    out_path = ROOT / "artifacts" / "story_map" / "ai_portraits_registry.json"
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), "utf-8")
    
    print(f"Registry written: {out_path}")
    print(f"  Total portraits: {len(existing)}")
    print(f"  Historical: {len(existing & HISTORICAL)}")
    print(f"  AI-generated: {len(ai_generated)}")

if __name__ == "__main__":
    main()

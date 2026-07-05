"""
批量补充三国人物作品信息。

用法：
    python3 tools/batch_supplement_works.py
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ========== 第一步：补充 work_summary_llm.json ==========

NEW_WORK_SUMMARIES = {
    # ---- 曹操 ----
    "短歌行": {
        "one_liner": "曹操四言诗代表作，以酒宴为背景抒写求贤若渴、及时建功的雄心，格调慷慨悲凉，是建安风骨的典范之作。",
        "genre": "四言诗",
        "authors": ["曹操"],
        "quotes": [
            "对酒当歌，人生几何！譬如朝露，去日苦多。",
            "山不厌高，海不厌深。周公吐哺，天下归心。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "蒿里行": {
        "one_liner": "曹操借乐府旧题写成的五言诗，以关东义军讨董为背景，真实记录军阀混战导致的民生惨状，被誉为'汉末实录，真诗史也'。",
        "genre": "乐府诗",
        "authors": ["曹操"],
        "quotes": [
            "白骨露于野，千里无鸡鸣。生民百遗一，念之断人肠。",
            "关东有义士，兴兵讨群凶。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "龟虽寿": {
        "one_liner": "曹操《步出夏门行》组诗末章，以神龟、腾蛇起兴，抒写老当益壮、积极进取的豪迈情怀，是全组诗的哲理升华。",
        "genre": "四言诗",
        "authors": ["曹操"],
        "quotes": [
            "老骥伏枥，志在千里。烈士暮年，壮心不已。",
            "盈缩之期，不但在天。养怡之福，可得永年。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "步出夏门行": {
        "one_liner": "曹操北征乌桓途中所作乐府组诗，含《观沧海》《冬十月》《土不同》《龟虽寿》四章，借山水景物抒写统一天下的雄心与哲思。",
        "genre": "乐府组诗",
        "authors": ["曹操"],
        "quotes": [],
        "era": "东汉末年",
        "quote_policy": "summary_only"
    },
    "让县自明本志令": {
        "one_liner": "曹操发布的令文（《述志令》），陈述自己从举孝廉到统一北方的心迹，表示让还三县食邑，以消除他人对其有'不逊之志'的猜疑。",
        "genre": "令文",
        "authors": ["曹操"],
        "quotes": [
            "设使国家无有孤，不知当几人称帝，几人称王。",
            "江湖未静，不可让位；至于邑土，可得而辞。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "求贤令": {
        "one_liner": "曹操发布的求贤令，明确提出'唯才是举'的用人原则，打破门第限制，不拘品行小节网罗天下人才。",
        "genre": "令文",
        "authors": ["曹操"],
        "quotes": [
            "自古受命及中兴之君，曷尝不得贤人君子与之共治天下者乎？",
            "唯才是举，吾得而用之。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "薤露行": {
        "one_liner": "曹操借乐府挽歌旧题写成的五言诗，叙述大将军何进谋诛宦官失败、董卓乱政焚毁洛阳的史实，对汉末朝政腐败给予沉痛批判。",
        "genre": "乐府诗",
        "authors": ["曹操"],
        "quotes": [
            "贼臣持国柄，杀主灭宇京。荡覆帝基业，宗庙以燔丧。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "苦寒行": {
        "one_liner": "曹操征伐高干途中所作五言诗，描写太行山行军之苦与将士思乡之情，以写景起兴，悲壮苍凉，是建安军旅诗的代表作。",
        "genre": "五言诗",
        "authors": ["曹操"],
        "quotes": [
            "北上太行山，艰哉何巍巍！羊肠坂诘屈，车轮为之摧。",
            "悲彼东山诗，悠悠使我哀。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },

    # ---- 曹丕 ----
    "典论·论文": {
        "one_liner": "曹丕所著《典论》中的一篇，是中国文学批评史上第一篇专门论述文学问题的论文，提出'文以气为主'和文章是'经国之大业，不朽之盛事'等著名论断。",
        "genre": "论文",
        "authors": ["曹丕"],
        "quotes": [
            "盖文章，经国之大业，不朽之盛事。",
            "文以气为主，气之清浊有体，不可力强而致。",
            "文人相轻，自古而然。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "燕歌行": {
        "one_liner": "曹丕所作七言乐府诗，描写思妇秋夜怀念远方征人的缠绵情感，是中国现存最早的完整七言诗，开后世七言歌行之先河。",
        "genre": "七言乐府诗",
        "authors": ["曹丕"],
        "quotes": [
            "秋风萧瑟天气凉，草木摇落露为霜。",
            "牵牛织女遥相望，尔独何辜限河梁。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },

    # ---- 曹植 ----
    "洛神赋": {
        "one_liner": "曹植辞赋代表作，描写人神相恋的幻灭哀婉，以华丽辞藻和丰富想象塑造洛水女神的绝美形象，是中国文学史上浪漫主义辞赋的巅峰之作。",
        "genre": "辞赋",
        "authors": ["曹植"],
        "quotes": [
            "翩若惊鸿，婉若游龙。荣曜秋菊，华茂春松。",
            "凌波微步，罗袜生尘。",
            "恨人神之道殊兮，怨盛年之莫当。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "白马篇": {
        "one_liner": "曹植五言诗名篇，以游侠少年自况，描绘边塞游侠精于骑射、勇于征战、捐躯报国的高超武艺与豪迈品格，寄托诗人建功立业的理想。",
        "genre": "五言诗",
        "authors": ["曹植"],
        "quotes": [
            "白马饰金羁，连翩西北驰。借问谁家子？幽并游侠儿。",
            "捐躯赴国难，视死忽如归。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "七步诗": {
        "one_liner": "传为曹植在曹丕逼迫下所作的五言诗，以'煮豆燃豆萁'比喻兄弟相残的残酷，短短四句蕴涵深刻的悲剧意蕴。",
        "genre": "五言诗",
        "authors": ["曹植"],
        "quotes": [
            "煮豆燃豆萁，豆在釜中泣。本是同根生，相煎何太急？"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "赠白马王彪": {
        "one_liner": "曹植长篇五言赠别诗，写于与异母弟曹彪被迫分别之际，抒发骨肉分离之痛与政治迫害之愤，是建安诗歌中抒情长篇的最高成就。",
        "genre": "五言诗",
        "authors": ["曹植"],
        "quotes": [
            "丈夫志四海，万里犹比邻。",
            "变故在斯须，百年谁能持？"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "名都篇": {
        "one_liner": "曹植所作五言乐府诗，描写都市贵游子弟斗鸡走马、宴饮行乐的繁华生活，在表面的纵横豪荡中暗含年华虚度的忧患意识。",
        "genre": "五言乐府诗",
        "authors": ["曹植"],
        "quotes": [
            "名都多妖女，京洛出少年。宝剑直千金，被服丽且鲜。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
    "美女篇": {
        "one_liner": "曹植五言诗，以美貌女子独处闺房求贤士而不得来暗喻自己怀才不遇的处境，借香草美人的比兴手法抒发政治失意的悲慨。",
        "genre": "五言诗",
        "authors": ["曹植"],
        "quotes": [
            "美女妖且闲，采桑歧路间。",
            "佳人慕高义，求贤良独难。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },

    # ---- 诸葛亮 ----
    "出师表": {
        "one_liner": "诸葛亮北伐前上呈后主刘禅的奏表（前出师表），分析时局、规劝后主亲贤远佞，表达北定中原、兴复汉室的赤诚忠心，情辞恳切，千古传诵。",
        "genre": "奏表",
        "authors": ["诸葛亮"],
        "quotes": [
            "臣本布衣，躬耕于南阳，苟全性命于乱世，不求闻达于诸侯。",
            "亲贤臣，远小人，此先汉所以兴隆也。",
            "鞠躬尽瘁，死而后已。"
        ],
        "era": "三国·蜀汉",
        "quote_policy": "preferred"
    },
    "前出师表": {
        "one_liner": "即《出师表》，诸葛亮建兴五年（227年）北伐前上呈后主刘禅的奏表，分析时局、规劝后主亲贤远佞，表达北定中原、兴复汉室的赤诚忠心。",
        "genre": "奏表",
        "authors": ["诸葛亮"],
        "quotes": [],
        "era": "三国·蜀汉",
        "quote_policy": "summary_only"
    },
    "后出师表": {
        "one_liner": "传为诸葛亮建兴六年（228年）再次上呈刘禅的奏表，以'汉贼不两立'申明北伐决心，以'鞠躬尽瘁，死而后已'表达不渝之心（作者真伪有争议）。",
        "genre": "奏表",
        "authors": ["诸葛亮"],
        "quotes": [
            "汉贼不两立，王业不偏安。",
            "臣鞠躬尽瘁，死而后已。"
        ],
        "era": "三国·蜀汉",
        "quote_policy": "preferred"
    },
    "诫子书": {
        "one_liner": "诸葛亮晚年写给八岁儿子诸葛瞻的家训短文，以'静以修身、俭以养德'为核心，论述修身治学之道，言简意深，是古代家训名篇。",
        "genre": "家训",
        "authors": ["诸葛亮"],
        "quotes": [
            "非淡泊无以明志，非宁静无以致远。",
            "夫学须静也，才须学也，非学无以广才，非志无以成学。"
        ],
        "era": "三国·蜀汉",
        "quote_policy": "preferred"
    },
    "隆中对": {
        "one_liner": "诸葛亮与刘备的著名战略对话（载于《三国志·诸葛亮传》），分析天下大势，提出占据荆、益二州，联孙抗曹，进而统一天下的战略蓝图。",
        "genre": "策论",
        "authors": ["诸葛亮"],
        "quotes": [
            "自董卓已来，豪杰并起，跨州连郡者不可胜数。",
            "若跨有荆、益，保其岩阻，西和诸戎，南抚夷越，外结好孙权，内修政理。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },

    # ---- 孔融 ----
    "荐祢衡表": {
        "one_liner": "孔融上疏汉献帝推荐天才文士祢衡的奏表（《荐祢衡疏》），以铺排文辞盛赞祢衡博学多才，并自陈不如，辞气激切，是汉末骈文的典范。",
        "genre": "奏疏",
        "authors": ["孔融"],
        "quotes": [
            "鸷鸟累百，不如一鹗。使衡立朝，必有可观。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "与曹操论盛孝章书": {
        "one_liner": "孔融写给曹操的书信，为遭受孙权迫害的好友盛宪（字孝章）求援，以交友之道和爱贤之义晓以大义，是建安书信文学的代表作。",
        "genre": "书信",
        "authors": ["孔融"],
        "quotes": [
            "岁月不居，时节如流。五十之年，忽焉已至。",
            "今之少年，喜谤前辈，或能讥评孝章。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "临终诗": {
        "one_liner": "孔融被曹操下狱后在狱中所作五言诗，感叹言多致祸、祸起于疏漏，以'谗邪害公正'控诉政治迫害，悲凉沉郁。",
        "genre": "五言诗",
        "authors": ["孔融"],
        "quotes": [
            "言多令事败，器漏苦不密。",
            "谗邪害公正，浮云翳白日。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },

    # ---- 蔡文姬 ----
    "悲愤诗": {
        "one_liner": "蔡文姬所作五言长篇叙事诗，自述汉末战乱中被掳入匈奴、历经离乱十二年后归汉、面临别子之痛的血泪经历，是中国早期文人叙事诗的代表作。",
        "genre": "五言叙事诗",
        "authors": ["蔡文姬"],
        "quotes": [
            "人生几何时，怀忧终年岁？",
            "马边悬男头，马后载妇女。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },
    "胡笳十八拍": {
        "one_liner": "传为蔡文姬所作长篇琴曲歌词，共十八段，以第一人称倾诉被掳匈奴十二年的孤苦悲愤与归汉别子的撕心裂肺之痛（作者归属存疑）。",
        "genre": "琴曲歌词",
        "authors": ["蔡文姬"],
        "quotes": [
            "天不仁兮降乱离，地不仁兮使我逢此时。",
            "胡笳动兮边马鸣，孤雁归兮声嘤嘤。"
        ],
        "era": "东汉末年",
        "quote_policy": "preferred"
    },

    # ---- 法正 ----
    "蜀科": {
        "one_liner": "法正与诸葛亮、伊籍、刘巴、李严等人共同制定的蜀汉基本法律，体现严刑峻法治理蜀地的方针，奠定了蜀汉法治的基础。",
        "genre": "法典",
        "authors": ["法正", "诸葛亮"],
        "quotes": [],
        "era": "三国·蜀汉",
        "quote_policy": "summary_only"
    },

    # ---- 曹丕补充 ----
    "寡妇诗": {
        "one_liner": "曹丕代言寡妇口吻所作五言闺怨诗，以霜露、秋月起兴，细腻刻画'守长夜、下罗帷'的孤寂，体现了建安诗人关注民生的一面。",
        "genre": "五言诗",
        "authors": ["曹丕"],
        "quotes": [
            "霜露纷兮交下，木叶落兮凄凄。"
        ],
        "era": "三国·曹魏",
        "quote_policy": "preferred"
    },
}


def main():
    # ---- 1. 更新 work_summary_llm.json ----
    work_path = PROJECT_ROOT / "data" / "corpus" / "work_summary_llm.json"

    with open(work_path, "r", encoding="utf-8") as f:
        work_data = json.load(f)

    added_count = 0
    for title, info in NEW_WORK_SUMMARIES.items():
        if title not in work_data:
            work_data[title] = info
            added_count += 1
            print(f"  + work_summary: {title}")

    with open(work_path, "w", encoding="utf-8") as f:
        json.dump(work_data, f, ensure_ascii=False, indent=2)

    print(f"\nwork_summary_llm.json: 新增 {added_count} 条作品摘要\n")

    # ---- 2. 更新 people_summary_index.json ----
    people_path = PROJECT_ROOT / "data" / "corpus" / "people_summary_index.json"

    with open(people_path, "r", encoding="utf-8") as f:
        people_data = json.load(f)

    items = people_data.get("items", {})

    # - 曹操：添加作品列表
    if "曹操" in items:
        items["曹操"]["works"] = [
            "短歌行", "观沧海", "蒿里行", "龟虽寿", "步出夏门行",
            "让县自明本志令", "求贤令", "薤露行", "苦寒行", "遗令"
        ]
        print("  曹操: works = " + str(items["曹操"]["works"]))

    # - 诸葛亮：修正作品列表
    if "诸葛亮" in items:
        items["诸葛亮"]["works"] = [
            "出师表", "后出师表", "诫子书", "隆中对"
        ]
        print("  诸葛亮: works = " + str(items["诸葛亮"]["works"]))

    # - 曹丕：补充作品
    if "曹丕" in items:
        existing = set(items["曹丕"].get("works", []))
        existing.update(["燕歌行", "寡妇诗"])
        items["曹丕"]["works"] = sorted(existing)
        print("  曹丕: works = " + str(items["曹丕"]["works"]))

    # - 曹植：补充作品
    if "曹植" in items:
        existing = set(items["曹植"].get("works", []))
        existing.update(["七步诗", "赠白马王彪", "名都篇", "美女篇"])
        items["曹植"]["works"] = sorted(existing)
        print("  曹植: works = " + str(items["曹植"]["works"]))

    # - 孔融：添加作品列表
    if "孔融" in items:
        items["孔融"]["works"] = [
            "荐祢衡表", "与曹操论盛孝章书", "临终诗"
        ]
        print("  孔融: works = " + str(items["孔融"]["works"]))

    # - 蔡文姬：补充摘要（已在 work_summary_llm 中添加），works 已有
    if "蔡文姬" in items:
        print(f"  蔡文姬: works = {items['蔡文姬']['works']} (已有)")

    # - 刘禅：删除出师表（属于诸葛亮）
    if "刘禅" in items:
        old = items["刘禅"].get("works", [])
        items["刘禅"]["works"] = []
        print(f"  刘禅: works {old} → []")

    # - 关羽：删除三国演义
    if "关羽" in items:
        old = items["关羽"].get("works", [])
        items["关羽"]["works"] = []
        print(f"  关羽: works {old} → []")

    with open(people_path, "w", encoding="utf-8") as f:
        json.dump(people_data, f, ensure_ascii=False, indent=2)

    print("\npeople_summary_index.json 更新完成！")


if __name__ == "__main__":
    main()

"""补全最后的26个顽固失败作品摘要（手动编写）"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "corpus" / "work_summary_llm.json"

MANUAL = {
    "〈西游记〉漫话": {
        "one_liner": "林庚以诗人视角漫谈《西游记》的学术随笔，从童话精神、喜剧色彩等独特角度解读这部古典神魔小说，文笔灵动，富于创见。",
        "genre": "学术随笔",
        "authors": ["林庚"],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "与妻书": {
        "one_liner": "林觉民于1911年黄花岗起义前写给妻子陈意映的绝笔信，以'意映卿卿如晤'开篇，将儿女情长与家国大义熔铸一体，是中国近代最感人的革命书信之一。",
        "genre": "书信",
        "authors": ["林觉民"],
        "quotes": ["吾至爱汝，即此爱汝一念，使吾勇于就死也。"],
        "era": "清末",
        "quote_policy": "preferred"
    },
    "东西文化及其哲学": {
        "one_liner": "梁漱溟的中西印文化比较代表作，系统比较中国、西方、印度三种文化路径，提出世界文化三期重现说，是新儒家的重要哲学著作。",
        "genre": "哲学著作",
        "authors": ["梁漱溟"],
        "quotes": ["中国文化是以意欲自为调和、持中为其根本精神的。"],
        "era": "现代",
        "quote_policy": "preferred"
    },
    "五蠹": {
        "one_liner": "《韩非子》中最具战斗性的篇章，将学者、言谈者、带剑者、患御者、商工之民斥为危害国家的'五蠹'，主张以法治国、奖励耕战，集中体现了韩非的法家思想。",
        "genre": "论说文",
        "authors": ["韩非子"],
        "quotes": ["故明主之国，无书简之文，以法为教；无先王之语，以吏为师。"],
        "era": "战国",
        "quote_policy": "preferred"
    },
    "关于和平解放西藏办法的协议": {
        "one_liner": "1951年中央人民政府与西藏地方政府签订的十七条协议，确认西藏和平解放、驱逐帝国主义势力、西藏回到祖国大家庭，由阿沛·阿旺晋美代表西藏地方政府签字。",
        "genre": "条约/协议",
        "authors": [],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "十七条协议": {
        "one_liner": "即和平解放西藏办法的协议，1951年签署，共十七条，确立西藏和平解放的原则与具体步骤，阿沛·阿旺晋美为西藏地方政府首席全权代表。",
        "genre": "条约/协议",
        "authors": [],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "剪辑错了的故事": {
        "one_liner": "茹志鹃1979年创作的短篇小说，以意识流手法将革命历史与现实错位拼接，反思'大跃进'时期的浮夸风，是反思文学的代表作之一。",
        "genre": "短篇小说",
        "authors": ["茹志鹃"],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "叶甫盖尼·奥涅金": {
        "one_liner": "普希金的长篇诗体小说，描写彼得堡贵族青年奥涅金的苦闷、爱情与决斗，塑造了俄国文学中第一个'多余人'形象，被誉为俄国生活的百科全书。",
        "genre": "诗体小说",
        "authors": ["普希金"],
        "quotes": [],
        "era": "19世纪",
        "quote_policy": "summary_only"
    },
    "哦，香雪": {
        "one_liner": "铁凝的成名作短篇小说，以北方山村少女香雪在火车停靠一分钟内用鸡蛋换铅笔盒的纯真故事，展现改革开放初期乡村少女对文明与美的渴望。",
        "genre": "短篇小说",
        "authors": ["铁凝"],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "天演论": {
        "one_liner": "严复翻译赫胥黎《进化论与伦理学》的中文译本，以'物竞天择，适者生存'为核心观点，将进化论引入中国，深刻影响了近代中国的思想启蒙与社会变革。",
        "genre": "译著",
        "authors": ["严复"],
        "quotes": ["物竞天择，适者生存。"],
        "era": "清末",
        "quote_policy": "preferred"
    },
    "太极图说": {
        "one_liner": "周敦颐撰写的理学奠基之作，以简约文字阐释宇宙生成论，提出'无极而太极'的本体论命题，构建'太极→阴阳→五行→万物'的宇宙模式，为宋明理学奠定形而上学基础。",
        "genre": "哲学著作",
        "authors": ["周敦颐"],
        "quotes": ["无极而太极。太极动而生阳，动极而静；静而生阴，静极复动。"],
        "era": "北宋",
        "quote_policy": "preferred"
    },
    "寒食": {
        "one_liner": "韩翃所作七绝名篇，以'春城无处不飞花'描绘长安寒食时节的暮春景象与宫中传烛的风俗画面，委婉含蓄，是唐代节令诗的精品。",
        "genre": "七言绝句",
        "authors": ["韩翃"],
        "quotes": ["春城无处不飞花，寒食东风御柳斜。日暮汉宫传蜡烛，轻烟散入五侯家。"],
        "era": "唐代",
        "quote_policy": "preferred"
    },
    "寻子遇仙记": {
        "one_liner": "卓别林的第一部长片电影（1921年），流浪汉夏尔洛收养弃儿，在底层社会演绎动人父子情，融合了幽默与悲悯，是默片时代经典。",
        "genre": "电影",
        "authors": ["卓别林"],
        "quotes": [],
        "era": "20世纪初",
        "quote_policy": "summary_only"
    },
    "将进酒": {
        "one_liner": "李白最具震撼力的歌行体名篇，以'君不见黄河之水天上来'开篇，豪饮高歌中抒发怀才不遇的激愤与人生须尽欢的旷达，气势磅礴，千古传诵。",
        "genre": "乐府/歌行",
        "authors": ["李白"],
        "quotes": ["天生我材必有用，千金散尽还复来。", "君不见黄河之水天上来，奔流到海不复回。"],
        "era": "唐代",
        "quote_policy": "preferred"
    },
    "布朗德": {
        "one_liner": "易卜生创作的诗剧，讲述牧师布朗德以极端'全有或全无'的理想主义精神追求信仰与道德纯粹，最终在雪崩中毁灭的悲剧，探讨理想与现实的尖锐冲突。",
        "genre": "诗剧",
        "authors": ["易卜生"],
        "quotes": [],
        "era": "19世纪",
        "quote_policy": "summary_only"
    },
    "康熙字典": {
        "one_liner": "清康熙年间张玉书、陈廷敬等奉敕编纂的大型汉字字典，收录四万七千余字，按部首分部排列，是古代收字最多的字典，对中国语言文字学影响深远。",
        "genre": "辞书",
        "authors": [],
        "quotes": [],
        "era": "清代",
        "quote_policy": "summary_only"
    },
    "悬崖上的一课": {
        "one_liner": "莫顿·亨特的散文名篇，叙述作者幼年时在父亲的鼓励下从悬崖上一步一步走下来的经历，以此阐述将大困难分解为小步骤去解决的人生哲理。",
        "genre": "散文",
        "authors": ["莫顿·亨特"],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "文木山房集": {
        "one_liner": "吴敬梓的诗文集，收录其生平所作诗、词、赋作品，与其长篇小说《儒林外史》相参照，可以窥见其文学才华与处世态度。",
        "genre": "诗文集",
        "authors": ["吴敬梓"],
        "quotes": [],
        "era": "清代",
        "quote_policy": "summary_only"
    },
    "易传": {
        "one_liner": "程颐对《周易》的义理阐释之作，以理学思想注解卦爻，强调'体用一源，显微无间'，将《周易》从占卜之书提升为儒家哲学经典，是程朱理学的核心著作之一。",
        "genre": "经学注疏",
        "authors": ["程颐"],
        "quotes": ["体用一源，显微无间。"],
        "era": "北宋",
        "quote_policy": "preferred"
    },
    "最后的晚餐": {
        "one_liner": "达·芬奇为米兰感恩圣母修道院餐厅创作的壁画，描绘耶稣在最后的晚餐宣布门徒中将有一人出卖他的戏剧性瞬间，以精妙构图和人物心理刻画成为文艺复兴艺术巅峰。",
        "genre": "壁画",
        "authors": ["达·芬奇"],
        "quotes": [],
        "era": "文艺复兴",
        "quote_policy": "summary_only"
    },
    "机器人": {
        "one_liner": "阿西莫夫机器人系列短篇小说集，包含《我，机器人》等名篇，首次系统提出机器人三定律，开创科幻文学中的机器人伦理主题。",
        "genre": "科幻小说",
        "authors": ["阿西莫夫"],
        "quotes": [],
        "era": "20世纪",
        "quote_policy": "summary_only"
    },
    "白毛女": {
        "one_liner": "贺敬之、丁毅执笔创作的中国第一部新歌剧，讲述贫农女儿喜儿被地主迫害逃入深山变为'白毛女'后获救重生的故事，深刻反映旧社会把人变成鬼、新社会把鬼变成人的主题。",
        "genre": "歌剧",
        "authors": ["贺敬之"],
        "quotes": ["旧社会把人逼成鬼，新社会把鬼变成人。"],
        "era": "现代",
        "quote_policy": "preferred"
    },
    "百合花": {
        "one_liner": "茹志鹃的成名作短篇小说，以解放战争为背景，通过小通讯员与新媳妇之间关于一条百合花被子的动人细节，歌颂纯朴真挚的人性美和军民鱼水情。",
        "genre": "短篇小说",
        "authors": ["茹志鹃"],
        "quotes": [],
        "era": "现代",
        "quote_policy": "summary_only"
    },
    "神策军碑": {
        "one_liner": "全称《皇帝巡幸左神策军纪圣德碑》，由柳公权奉敕书写，以楷书刻石，笔力遒劲，筋骨分明，是柳体楷书的巅峰代表作，现存拓本藏于国家图书馆。",
        "genre": "碑文/书法",
        "authors": ["柳公权"],
        "quotes": [],
        "era": "唐代",
        "quote_policy": "summary_only"
    },
    "蒙娜丽莎": {
        "one_liner": "达·芬奇创作的肖像油画，描绘一位佛罗伦萨女性含蓄而神秘的微笑，采用渐隐法处理轮廓，是世界上最著名的绘画作品之一，现藏于巴黎卢浮宫。",
        "genre": "油画",
        "authors": ["达·芬奇"],
        "quotes": [],
        "era": "文艺复兴",
        "quote_policy": "summary_only"
    },
    "风声": {
        "one_liner": "以抗日战争时期重庆情报战为背景的谍战文学作品（指麦家小说或相关电影），讲述潜伏在日伪高层的特工在密室审讯中传递情报的惊险故事。",
        "genre": "小说",
        "authors": [],
        "quotes": [],
        "era": "当代",
        "quote_policy": "summary_only"
    },
}


def main():
    with open(OUT_PATH, "r", encoding="utf-8") as f:
        cache = json.load(f)

    count = 0
    for title, info in MANUAL.items():
        if title not in cache:
            cache[title] = info
            count += 1
            print(f"  + {title}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n新增 {count} 条，文件总计 {len(cache)} 条")


if __name__ == "__main__":
    main()

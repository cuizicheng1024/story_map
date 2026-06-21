import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from tools.homepage_search import normalize_search_text, pinyin_variants
except Exception:
    from homepage_search import normalize_search_text, pinyin_variants

from storymap.script import parsers as parser_utils
from storymap.script import profile_builder
from storymap.script.project_paths import data_corpus_output_path, story_person_names


SUMMARY_INDEX_FILENAME = "work_summary_index.json"
_AUTHORING_HINT_RE = re.compile(
    r"(著有|著成|撰写|创作|写下|写有|写作|作有|作了|所著|所作|其《|其所作|代表作|名作|名篇|词作|诗作|文集|著作)"
)
_NON_AUTHORING_HINT_RE = re.compile(r"(课文|教材|课本|选文|收录|节选|后人辑录|后世辑录)")
_SELF_AUTHORED_ROLE_HINT_RE = re.compile(
    r"(诗人|词人|作家|文学家|文豪|散文家|小说家|剧作家|诗词家|文人|赋家|乐府诗|歌行体|浪漫主义诗人|诗仙|诗圣)"
)
_GENRE_RULES: Tuple[Tuple[str, str], ...] = (
    (r"(赋)$", "赋"),
    (r"(记)$", "散文"),
    (r"(序)$", "序"),
    (r"(表)$", "表"),
    (r"(铭)$", "铭"),
    (r"(说)$", "说理文"),
    (r"(论)$", "论说文"),
    (r"(书)$", "书信/论说文"),
    (r"(诗|诗集)$", "诗"),
    (r"(词|词集)$", "词"),
    (r"(曲)$", "曲"),
    (r"(传)$", "传记"),
    (r"(志)$", "史志"),
    (r"(注)$", "注疏"),
    (r"(算经)$", "数学著作"),
    (r"(游记)$", "游记"),
    (r"(小说)$", "小说"),
    (r"(交响曲|协奏曲|奏鸣曲|夜曲|圆舞曲)$", "曲"),
    (r"(词)$", "词"),
    (r"(歌)$", "歌曲"),
)
_WORK_QUOTE_FALLBACKS: Dict[str, Tuple[str, ...]] = {
    "典论·论文": (
        "经国之大业，不朽之盛事。",
        "文以气为主。",
        "盖文章，经国之大业，不朽之盛事。",
    ),
    "出师表": (
        "臣本布衣，躬耕于南阳，苟全性命于乱世，不求闻达于诸侯。",
        "当奖率三军，北定中原，庶竭驽钝，攘除奸凶，兴复汉室，还于旧都。",
        "此臣所以报先帝而忠陛下之职分也。",
    ),
    "离骚": (
        "路漫漫其修远兮，吾将上下而求索。",
        "亦余心之所善兮，虽九死其犹未悔。",
        "惟草木之零落兮，恐美人之迟暮。",
    ),
    "别董大": (
        "莫愁前路无知己，天下谁人不识君。",
        "千里黄云白日曛，北风吹雁雪纷纷。",
    ),
    "滕王阁序": (
        "落霞与孤鹜齐飞，秋水共长天一色。",
        "老当益壮，宁移白首之心？穷且益坚，不坠青云之志。",
    ),
    "燕歌行": (
        "战士军前半死生，美人帐下犹歌舞。",
        "君不见沙场征战苦，至今犹忆李将军。",
    ),
    "如意娘": (
        "看朱成碧思纷纷，憔悴支离为忆君。",
    ),
    "六国论": (
        "六国破灭，非兵不利，战不善，弊在赂秦。",
        "为国者无使为积威之所劫哉。",
    ),
    "茶经": (
        "茶者，南方之嘉木也。",
    ),
    "蜂": (
        "采得百花成蜜后，为谁辛苦为谁甜。",
    ),
    "蝉": (
        "居高声自远，非是藉秋风。",
    ),
    "淮中晚泊犊头": (
        "春阴垂野草青青，时有幽花一树明。",
        "晚泊孤舟古祠下，满川风雨看潮生。",
    ),
    "腊日宣诏幸上苑": (
        "明朝游上苑，火急报春知。",
        "花须连夜发，莫待晓风吹。",
    ),
    "兵车行": (
        "车辚辚，马萧萧，行人弓箭各在腰。",
        "君不见，青海头，古来白骨无人收。",
        "生女犹得嫁比邻，生男埋没随百草。",
    ),
    "别范安成": (
        "生平少年日，分手易前期。",
        "及尔同衰暮，非复别离时。",
        "梦中不识路，何以慰相思？",
    ),
    "泷冈阡表": (
        "祭而丰不如养之薄也。",
        "吾不能早用汝教，使汝至于困穷而死。",
    ),
    "静夜思": (
        "床前明月光，疑是地上霜。",
        "举头望明月，低头思故乡。",
    ),
    "望庐山瀑布": (
        "飞流直下三千尺，疑是银河落九天。",
        "日照香炉生紫烟，遥看瀑布挂前川。",
    ),
    "赠汪伦": (
        "桃花潭水深千尺，不及汪伦送我情。",
        "李白乘舟将欲行，忽闻岸上踏歌声。",
    ),
    "黄鹤楼送孟浩然之广陵": (
        "孤帆远影碧空尽，唯见长江天际流。",
        "故人西辞黄鹤楼，烟花三月下扬州。",
    ),
    "行路难": (
        "长风破浪会有时，直挂云帆济沧海。",
        "金樽清酒斗十千，玉盘珍羞直万钱。",
        "欲渡黄河冰塞川，将登太行雪满山。",
    ),
    "将进酒": (
        "天生我材必有用，千金散尽还复来。",
        "君不见黄河之水天上来，奔流到海不复回。",
        "人生得意须尽欢，莫使金樽空对月。",
    ),
    "蜀道难": (
        "蜀道之难，难于上青天。",
        "上有六龙回日之高标，下有冲波逆折之回川。",
        "剑阁峥嵘而崔嵬，一夫当关，万夫莫开。",
    ),
}
_SUMMARY_ONLY_GENRES = {"数学著作", "史志", "注疏"}
_SUMMARY_ONLY_TITLE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(条约|和约|法案|宪章|宣言|提纲|大典|全书|通鉴|本纪|世家|列传)$"),
    re.compile(r"(建筑史|算经|细草|建筑史)$"),
    re.compile(r"(交响曲|协奏曲|奏鸣曲|夜曲|圆舞曲|文集|选集|总目提要|自传|回忆录|日报|星报)$"),
    re.compile(r"(像|胸像|浮雕)$"),
)
_SUMMARY_ONLY_TITLE_EXACT = {
    "中国建筑史",
    "元史",
    "清史",
    "左传",
    "资治通鉴",
    "四库全书",
    "永乐大典",
    "文选",
    "昭明文选",
    "工具论",
    "形而上学",
    "政治学",
    "尼各马可伦理学",
    "创世纪",
    "创造亚当",
    "哀悼基督",
    "大卫",
    "最后的审判",
    "轧铁工厂",
    "腓特烈大帝在无忧宫的长笛演奏会上",
    "人民英雄纪念碑浮雕",
    "蔡元培像",
    "蔡元培胸像",
    "泰戈尔像",
    "基督受洗",
    "职贡图",
    "有阳台的房间",
    "柏林-波茨坦铁路",
    "苗女赶场",
    "二十四史",
    "四库全书总目提要",
    "于湖居士文集",
    "袁隆平论文选集",
    "杨得志回忆录",
    "从文自传",
    "多伦多星报",
    "广西日报",
    "三个故事和十首诗",
    "人口论",
    "在我们的时代里",
    "地质力学概论",
    "复仇",
    "浑河的急流",
    "湖州谢上表",
    "电学实验研究",
    "秋水",
    "记丁玲",
    "遥远的风沙",
    "题长江厅",
    "颜氏家庙碑",
    "风帆",
}
_SUMMARY_ONLY_SUMMARY_RE = re.compile(r"(油画|壁画|雕塑|画作|绘画|雕像|建筑著作|史学著作|工具书|教材课文|战地通讯|报刊|报纸|图像|画像|胸像|浮雕)")
_CURATED_WORK_SUMMARY_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "水调歌头·明月几时有": {
        "genre": "词",
        "one_liner": "苏轼中秋怀子由名作，以明月寄托人生离合之思。",
        "summary": "作于密州中秋之夜，兼具宇宙意识、亲情思念与旷达的人生体悟。",
        "quotes": [
            "明月几时有？把酒问青天。",
            "但愿人长久，千里共婵娟。",
        ],
        "quote_policy": "preferred",
    },
    "江城子·密州出猎": {
        "genre": "词",
        "one_liner": "苏轼在密州出猎后所作，借壮阔猎场抒发报国豪情。",
        "summary": "以出猎场景写雄心壮志，标志其豪放词风的成熟展开。",
        "quotes": [
            "老夫聊发少年狂，左牵黄，右擎苍。",
            "会挽雕弓如满月，西北望，射天狼。",
        ],
        "quote_policy": "preferred",
    },
    "记承天寺夜游": {
        "genre": "散文",
        "one_liner": "黄州夜游小品名篇，以空明月色映照贬谪中的清旷心境。",
        "summary": "借月夜漫步承天寺的所见所感，写景极空灵，也流露出自我排遣后的旷达。",
        "quotes": [
            "庭下如积水空明，水中藻、荇交横，盖竹柏影也。",
            "但少闲人如吾两人者耳。",
        ],
        "quote_policy": "preferred",
    },
    "念奴娇·赤壁怀古": {
        "genre": "词",
        "one_liner": "借古赤壁怀周瑜，融江山之胜、历史兴亡与人生感慨于一体。",
        "summary": "以赤壁壮景起兴，追怀英雄功业，最终回到对自我身世与人生无常的体认。",
        "quotes": [
            "大江东去，浪淘尽，千古风流人物。",
            "人生如梦，一尊还酹江月。",
        ],
        "quote_policy": "preferred",
    },
    "赤壁赋": {
        "genre": "赋",
        "one_liner": "即《前赤壁赋》，借泛舟夜游与主客问答阐发旷达的人生哲理。",
        "summary": "通过赤壁秋夜的江月清风与主客对话，展开对“变”与“不变”的哲思。",
        "quotes": [
            "寄蜉蝣于天地，渺沧海之一粟。",
            "哀吾生之须臾，羡长江之无穷。",
        ],
        "quote_policy": "preferred",
    },
    "前赤壁赋": {
        "genre": "赋",
        "one_liner": "借泛舟夜游与主客问答阐发旷达的人生哲理，是苏轼黄州时期名篇。",
        "summary": "通过赤壁秋夜的江月清风与主客对话，展开对“变”与“不变”的哲思。",
        "quotes": [
            "寄蜉蝣于天地，渺沧海之一粟。",
            "哀吾生之须臾，羡长江之无穷。",
        ],
        "quote_policy": "preferred",
    },
    "寒食帖": {
        "genre": "书法",
        "one_liner": "苏轼黄州时期行书名作，以沉郁跌宕的笔意写寒食心境。",
        "summary": "被后世誉为“天下第三行书”，常被视作其书法艺术与人生遭际交汇的代表作。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "登州海市": {
        "genre": "诗",
        "one_liner": "苏轼任登州知州时见海市蜃楼有感而作，以海上奇景写仕途忧思。",
        "summary": "借登州海市的虚景写人生际遇与朝政浮沉，是其北归途中诗作的代表。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "凤翔八观": {
        "genre": "诗",
        "one_liner": "苏轼任凤翔府签判时游览当地名胜所作组诗。",
        "summary": "组诗八首，以游历凤翔古迹为线索，借景写史、抒怀，是其早期诗歌的成熟之作。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "和陶拟古九首": {
        "genre": "诗",
        "one_liner": "苏轼晚年和陶渊明《拟古》而作的组诗，寄托归隐之志。",
        "summary": "和陶组诗九首，借古淡风格表达对陶渊明的追慕与自身南迁岁月的反思。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "后赤壁赋": {
        "genre": "赋",
        "one_liner": "苏轼再游赤壁所作之赋，意境冷峭，与前作互为映照。",
        "summary": "以再游赤壁的秋冬之景写孤鹤夜啸的奇幻体验，气象与前作截然不同。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "浣溪沙·簌簌衣巾落枣花": {
        "genre": "词",
        "one_liner": "苏轼徐州谢雨途中所作，写北方乡村初夏景象与民生情态。",
        "summary": "以谢雨路上所见的村落生活为画面，被视作宋词中描写北方乡村的代表之作。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "石炭歌": {
        "genre": "诗",
        "one_liner": "苏轼任徐州知州时发现石炭后所作长歌，记录新能源对民生的意义。",
        "summary": "歌咏徐州一带新发现的石炭（煤）资源，是宋代咏物诗中较少见的“能源”题材。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
    "西江月·梅花": {
        "genre": "词",
        "one_liner": "苏轼借岭南梅花咏物寄怀，是其贬谪南方时期的代表词作之一。",
        "summary": "以梅花为引，写南迁岁月的清旷与孤峭，意境与早期豪放之作明显不同。",
        "quotes": [],
        "quote_policy": "summary_only",
    },
}


def _uniq_preserve_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_work_title(title: str) -> str:
    clean_title = str(title or "").replace("**", "").strip()
    clean_title = re.sub(r"^[“\"'‘《]+", "", clean_title)
    clean_title = re.sub(r"[”\"'’》]+$", "", clean_title)
    return clean_title.strip()


def _work_sort_key(title: str) -> tuple[str, str, str]:
    raw = _normalize_work_title(title)
    normalized = normalize_search_text(raw) or raw.casefold()
    pinyin_list = pinyin_variants(raw)
    primary = str(pinyin_list[0] or "").strip() if pinyin_list else normalized
    return primary, normalized, raw


def _strip_outer_quotes(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    quote_pairs = [("“", "”"), ('"', '"'), ("'", "'"), ("‘", "’")]
    for left, right in quote_pairs:
        if cleaned.startswith(left) and cleaned.endswith(right) and len(cleaned) >= len(left) + len(right):
            cleaned = cleaned[len(left) : len(cleaned) - len(right)].strip()
            break
    return cleaned


def _normalize_summary_text(text: str, *, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").replace("**", "")).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^[：:;；，,\-—\s]+", "", cleaned)
    cleaned = _strip_outer_quotes(cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "…"
    return cleaned


def _normalize_quote_text(text: str, *, limit: int = 96) -> str:
    cleaned = _normalize_summary_text(text, limit=limit)
    cleaned = re.sub(r"^(?:《[^》]+》)?\s*[：:]\s*", "", cleaned)
    cleaned = re.sub(r"^(?:名篇名句|代表作品(?:与思想)?|代表作品|代表作(?:品)?(?:与思想)?|作品简介|内容简介|写作背景|意义|相关回忆|历史评价|课文|课文/词作)\s*[：:]\s*", "", cleaned)
    cleaned = re.sub(r"^[“\"「]", "", cleaned)
    cleaned = re.sub(r"[”\"」]$", "", cleaned)
    return cleaned.strip()


def _pick_intro_line(md: str) -> str:
    parsed_doc = parser_utils.parse_story_document(md)
    intro = str(parsed_doc.overview or "").strip()
    if not intro:
        return ""
    for segment in re.split(r"[。！？\n]", intro):
        cleaned = _normalize_summary_text(segment, limit=100)
        if cleaned:
            return cleaned
    return ""


def _merge_intro_fields_into_info(info: Dict[str, str], md: str) -> Dict[str, str]:
    merged = dict(info or {})
    fields = profile_builder.extract_intro_fields(md)
    if not any(fields.values()):
        return merged
    if fields.get("朝代"):
        merged.setdefault("时代", str(fields.get("朝代") or "").strip())
    if fields.get("身份"):
        merged.setdefault("主要身份", str(fields.get("身份") or "").strip())
    if fields.get("历史地位"):
        merged.setdefault("历史地位", str(fields.get("历史地位") or "").strip())
    if fields.get("主要事件"):
        merged.setdefault("主要成就", str(fields.get("主要事件") or "").strip())
    return merged


def _pick_basic_field(md: str, label: str) -> str:
    patterns = [
        rf"\*\*{re.escape(label)}\*\*[:：]\s*([^\n]+)",
        rf"{re.escape(label)}[:：]\s*([^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, md)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _infer_genre(title: str, summary: str) -> str:
    clean_title = _normalize_work_title(title)
    for pattern, label in _GENRE_RULES:
        if re.search(pattern, clean_title):
            return label
    pool = f"{clean_title} {summary}"
    if re.search(r"(长诗|史诗)", pool):
        return "长诗/史诗"
    if re.search(r"(散文|小品文)", pool):
        return "散文"
    return ""


def _find_title_lines(md: str, title: str) -> List[str]:
    if not md or not title:
        return []
    clean_title = _normalize_work_title(title)
    target = f"《{clean_title}》"
    lines: List[str] = []
    for raw_line in md.splitlines():
        line = str(raw_line or "").strip()
        if target in line:
            lines.append(line)
    return lines


def _infer_authors(person: str, title: str, md: str) -> List[str]:
    authors: List[str] = []
    title_lines = _find_title_lines(md, title)
    for line in title_lines:
        if _NON_AUTHORING_HINT_RE.search(line):
            continue
        if _AUTHORING_HINT_RE.search(line):
            authors.append(person)
            break
    if authors:
        return _uniq_preserve_order(authors)
    curriculum_line = next((line for line in title_lines if "课文/词作" in line or "教材" in line), "")
    if curriculum_line and _SELF_AUTHORED_ROLE_HINT_RE.search(md):
        authors.append(person)
    return _uniq_preserve_order(authors)


def _pick_best_work_text(title: str, work_texts: Dict[str, str]) -> str:
    for alias in profile_builder._work_title_aliases(_normalize_work_title(title)):
        text = _normalize_summary_text(str(work_texts.get(alias) or ""), limit=160)
        if text:
            return text
    return ""


def _extract_quotes(text: str, *, limit: int = 3) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    quoted = _uniq_preserve_order(
        [
            _normalize_quote_text(item, limit=96)
            for item in re.findall(r"[“\"「](.+?)[”\"」]", raw)
            if _normalize_quote_text(item, limit=96)
        ]
    )
    if quoted:
        ordered = sorted(quoted, key=lambda item: (-len(str(item or "")), str(item or "")))
        return ordered[:limit]
    if "“" in raw or '"' in raw:
        fallback = _normalize_quote_text(raw, limit=96)
        return [fallback] if fallback else []
    return []


def _collect_quotes_from_md(title: str, md: str, *, limit: int = 3) -> List[str]:
    quotes: List[str] = []
    for line in _find_title_lines(md, title):
        quotes.extend(_extract_quotes(line, limit=limit))
    return _uniq_preserve_order(quotes)[:limit]


def _strip_quote_lead_in(text: str, title: str = "") -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(?:名篇名句|代表作品(?:与思想)?|代表作品|代表作(?:品)?(?:与思想)?|作品简介|内容简介|写作背景|意义|相关回忆|历史评价|课文|课文/词作)\s*[：:]\s*", "", cleaned)
    if title:
        title_pattern = re.escape(_normalize_work_title(title))
        cleaned = re.sub(rf"^(?:《\*?\*?{title_pattern}\*?\*?》|\*?\*?{title_pattern}\*?\*)\s*(?:（[^）]+）|\([^)]*\))?\s*[：:]\s*", "", cleaned)
    cleaned = re.sub(r"^《[^》]+》\s*(?:（[^）]+）|\([^)]*\))?\s*[：:]\s*", "", cleaned)
    return cleaned.strip()


def _extract_quote_candidates(text: str, *, title: str = "", limit: int = 3) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    for chunk in re.split(r"[\n\r]+|(?<=[。！？!?；;])", raw):
        candidate = _normalize_quote_text(_strip_quote_lead_in(chunk, title=title), limit=96)
        if not candidate:
            continue
        if len(candidate) < 8 or len(candidate) > 96:
            continue
        if _quote_dedupe_key(candidate) in seen:
            continue
        if re.search(r"^(主要成就|代表作|名作|名篇|作品简介|内容简介|作者简介|写作背景|课文|教材)\s*[：:]", candidate):
            continue
        if re.search(r"^《[^》]+》\s*(是|为|属于)", candidate):
            continue
        if re.search(r"(开创性作品|代表作|名篇|教材课文)", candidate):
            continue
        if re.fullmatch(r"(?:《[^》]+》[、，,\s]*){2,}[。！？!?]?", candidate):
            continue
        if not re.search(r"[，。！？!?；;、]", candidate):
            continue
        seen.add(_quote_dedupe_key(candidate))
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def _collect_quote_candidates_from_md(title: str, md: str, *, limit: int = 3) -> List[str]:
    quotes: List[str] = []
    for line in _find_title_lines(md, title):
        quotes.extend(_extract_quote_candidates(line, title=title, limit=limit))
    return _uniq_preserve_order(quotes)[:limit]


def _fallback_quotes_for_title(title: str, *, limit: int = 3) -> List[str]:
    merged: List[str] = []
    for alias in profile_builder._work_title_aliases(_normalize_work_title(title)):
        for item in _WORK_QUOTE_FALLBACKS.get(alias, ()):
            normalized = _normalize_quote_text(item, limit=96)
            if normalized:
                merged.append(normalized)
    return _uniq_preserve_order(merged)[:limit]


def _quote_dedupe_key(text: str) -> str:
    return re.sub(r"[。！？!?；;、\s]+$", "", str(text or "").strip())


def _rank_quotes_for_title(title: str, quotes: List[str], *, limit: int = 3) -> List[str]:
    clean_title = str(title or "").strip()
    normalized = _uniq_preserve_order([_normalize_quote_text(item, limit=96) for item in quotes if _normalize_quote_text(item, limit=96)])
    preferred = _fallback_quotes_for_title(clean_title, limit=max(limit, len(normalized) or 0))
    normalized_by_key = {_quote_dedupe_key(item): item for item in normalized}
    ranked: List[str] = []
    used_keys = set()
    for item in preferred:
        key = _quote_dedupe_key(item)
        if not key or key not in normalized_by_key or key in used_keys:
            continue
        ranked.append(item)
        used_keys.add(key)
    extras = sorted(
        [item for item in normalized if _quote_dedupe_key(item) not in used_keys],
        key=lambda item: (-len(str(item or "")), str(item or "")),
    )
    for item in extras:
        key = _quote_dedupe_key(item)
        if not key or key in used_keys:
            continue
        ranked.append(item)
        used_keys.add(key)
    return ranked[:limit]


def _pick_primary_quote(quotes: List[str]) -> str:
    return str((quotes or [""])[0] or "").strip()


def _resolve_quote_policy(title: str, genre: str, authors: List[str], summary: str) -> str:
    clean_title = _normalize_work_title(title)
    clean_genre = str(genre or "").strip()
    clean_summary = str(summary or "").strip()
    if not _uniq_preserve_order([str(x).strip() for x in authors or []]):
        return "summary_only"
    if clean_genre in _SUMMARY_ONLY_GENRES:
        return "summary_only"
    if clean_title in _SUMMARY_ONLY_TITLE_EXACT:
        return "summary_only"
    if any(pattern.search(clean_title) for pattern in _SUMMARY_ONLY_TITLE_PATTERNS):
        return "summary_only"
    if _SUMMARY_ONLY_SUMMARY_RE.search(clean_summary):
        return "summary_only"
    return "preferred"


def _apply_curated_work_summary_override(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry or {})
    clean_title = _normalize_work_title(str(out.get("title") or ""))
    override = _CURATED_WORK_SUMMARY_OVERRIDES.get(clean_title)
    if not override:
        return out
    for key in ("genre", "one_liner", "summary"):
        value = str(override.get(key) or "").strip()
        if value:
            out[key] = value
    override_quotes = [
        _normalize_quote_text(item, limit=96)
        for item in override.get("quotes") or []
        if _normalize_quote_text(item, limit=96)
    ]
    if override_quotes:
        out["quotes"] = _uniq_preserve_order(override_quotes)[:3]
        out["quote"] = _pick_primary_quote(out["quotes"])
    quote_policy = str(override.get("quote_policy") or "").strip()
    if quote_policy:
        out["quote_policy"] = quote_policy
    else:
        out["quote_policy"] = _resolve_quote_policy(
            clean_title,
            str(out.get("genre") or ""),
            [str(x).strip() for x in out.get("authors") or [] if str(x).strip()],
            str(out.get("summary") or out.get("one_liner") or ""),
        )
    if out.get("quote_policy") == "summary_only":
        out["quotes"] = []
        out["quote"] = ""
    return out


def _entry_quality_score(item: Dict[str, Any]) -> int:
    authors = len(_uniq_preserve_order([str(x).strip() for x in item.get("authors") or []]))
    quotes = len(_uniq_preserve_order([str(x).strip() for x in item.get("quotes") or []]))
    related_people = len(_uniq_preserve_order([str(x).strip() for x in item.get("related_people") or []]))
    score = 0
    score += authors * 200
    score += quotes * 80
    score += related_people * 10
    score += min(len(str(item.get("summary") or "").strip()), 120)
    score += min(len(str(item.get("one_liner") or "").strip()), 80)
    if str(item.get("quote") or "").strip():
        score += 25
    return score


def _summarize_work_entry(
    *,
    title: str,
    person: str,
    dynasty: str,
    intro_line: str,
    work_text: str,
    md: str,
) -> Dict[str, Any]:
    clean_title = _normalize_work_title(title)
    authors = _infer_authors(person, clean_title, md)
    one_liner = _normalize_summary_text(work_text or intro_line, limit=110)
    summary = _normalize_summary_text(work_text or intro_line, limit=160)
    genre = _infer_genre(clean_title, summary)
    quotes = _uniq_preserve_order(
        _extract_quotes(work_text, limit=3)
        + _extract_quote_candidates(work_text, title=clean_title, limit=3)
        + _collect_quotes_from_md(clean_title, md, limit=3)
        + _collect_quote_candidates_from_md(clean_title, md, limit=3)
        + (_fallback_quotes_for_title(clean_title, limit=3) if authors else [])
    )
    quote_policy = _resolve_quote_policy(clean_title, genre, authors, summary)
    if quote_policy == "summary_only":
        quotes = []
    quotes = _rank_quotes_for_title(clean_title, quotes, limit=3)
    quote = _pick_primary_quote(quotes)
    return {
        "title": clean_title,
        "aliases": [alias for alias in profile_builder._work_title_aliases(clean_title) if alias != clean_title],
        "authors": authors,
        "related_people": [person] if person else [],
        "source_pages": [person] if person else [],
        "era": dynasty if authors and dynasty else "",
        "genre": genre,
        "one_liner": one_liner,
        "summary": summary,
        "quote": quote,
        "quotes": quotes,
        "quote_policy": quote_policy,
    }


def _merge_work_entry(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base or {})
    for key in ("aliases", "authors", "related_people", "source_pages"):
        merged = _uniq_preserve_order(
            [str(item or "").strip() for item in out.get(key, [])]
            + [str(item or "").strip() for item in incoming.get(key, [])]
        )
        out[key] = merged
    merged_quotes = _uniq_preserve_order(
        [_normalize_quote_text(x, limit=96) for x in out.get("quotes") or [] if _normalize_quote_text(x, limit=96)]
        + [_normalize_quote_text(x, limit=96) for x in incoming.get("quotes") or [] if _normalize_quote_text(x, limit=96)]
    )
    merged_quotes = _rank_quotes_for_title(str(out.get("title") or incoming.get("title") or ""), merged_quotes, limit=3)
    out["quotes"] = merged_quotes
    out["quote"] = _pick_primary_quote(merged_quotes)
    base_score = _entry_quality_score(out)
    incoming_score = _entry_quality_score(incoming)
    for key in ("one_liner", "summary"):
        current = _normalize_summary_text(str(out.get(key) or ""), limit=180)
        candidate = _normalize_summary_text(str(incoming.get(key) or ""), limit=180)
        if candidate and (incoming_score > base_score or not current or (incoming_score == base_score and len(candidate) > len(current))):
            out[key] = candidate
        else:
            out[key] = current
    if not str(out.get("genre") or "").strip() and str(incoming.get("genre") or "").strip():
        out["genre"] = str(incoming.get("genre") or "").strip()
    if not str(out.get("era") or "").strip() and str(incoming.get("era") or "").strip():
        out["era"] = str(incoming.get("era") or "").strip()
    out["title"] = str(out.get("title") or incoming.get("title") or "").strip()
    out["quote_policy"] = _resolve_quote_policy(
        str(out.get("title") or ""),
        str(out.get("genre") or ""),
        [str(x).strip() for x in out.get("authors") or [] if str(x).strip()],
        str(out.get("summary") or out.get("one_liner") or ""),
    )
    if out["quote_policy"] == "summary_only":
        out["quotes"] = []
        out["quote"] = ""
    return out


def main() -> int:
    file_path = Path(__file__).resolve()
    repo_root = file_path.parents[2] if file_path.parent.name == "build" else file_path.parents[1]
    story_dir = repo_root / "storymap" / "examples" / "story"
    items: Dict[str, Dict[str, Any]] = {}
    for person in sorted(story_person_names(story_dir), key=lambda name: _work_sort_key(name)):
        path = story_dir / f"{person}.md"
        if not path.is_file():
            continue
        md = path.read_text(encoding="utf-8", errors="ignore")
        parsed_doc = parser_utils.parse_story_document(md)
        normalized_md = parsed_doc.normalized_markdown
        info = _merge_intro_fields_into_info(dict(parsed_doc.basic_info_map), normalized_md)
        dynasty = str(info.get("时代") or info.get("朝代") or _pick_basic_field(normalized_md, "时代") or "").strip()
        intro_line = _pick_intro_line(normalized_md)
        work_texts = profile_builder.extract_work_texts(normalized_md)
        works = _uniq_preserve_order(profile_builder.extract_works(normalized_md))
        for title in works:
            clean_title = _normalize_work_title(title)
            if not clean_title:
                continue
            entry = _summarize_work_entry(
                title=clean_title,
                person=person,
                dynasty=dynasty,
                intro_line=intro_line,
                work_text=_pick_best_work_text(clean_title, work_texts),
                md=normalized_md,
            )
            existing = items.get(clean_title)
            merged = _merge_work_entry(existing or {}, entry) if existing else entry
            items[clean_title] = _apply_curated_work_summary_override(merged)

    ordered_items = {
        title: _apply_curated_work_summary_override(items[title])
        for title in sorted(items.keys(), key=_work_sort_key)
    }
    payload = {"items": ordered_items, "meta": {"count": len(ordered_items)}}
    path = data_corpus_output_path(SUMMARY_INDEX_FILENAME, project_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

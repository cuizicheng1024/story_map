import importlib
import json
import sys


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_main_builds_work_summary_index_with_author_and_non_author_cases(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text(
        "\n".join(
            [
                "# 苏轼",
                "",
                "### 生平概述",
                "苏轼是北宋文学家。",
                "",
                "### 基本信息",
                "- **时代**：北宋",
                "- **主要成就**：创作《赤壁赋》。",
                "",
                "### 历史评价",
                "- 苏轼创作《赤壁赋》，写下“寄蜉蝣于天地，渺沧海之一粟。”",
            ]
        ),
        encoding="utf-8",
    )
    (story_dir / "李春.md").write_text(
        "\n".join(
            [
                "# 李春",
                "",
                "### 生平概述",
                "李春是隋代工匠。",
                "",
                "### 基本信息",
                "- **时代**：隋",
                "",
                "### 历史评价",
                "- 课文《中国石拱桥》写道：“桥的设计完全合乎科学原理，施工技术更是巧妙绝伦。”",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    (story_dir / "曹丕.md").write_text(
        "\n".join(
            [
                "# 曹丕",
                "",
                "### 生平概述",
                "曹丕是建安文学代表人物。",
                "",
                "### 基本信息",
                "- **时代**：三国（魏）",
                "- **主要成就**：其《典论·论文》是文学批评史上的开创性作品。",
                "",
                "### 人教版教材知识点",
                "- **《典论·论文》** 提出“文以气为主”。",
                "- **重点**：**《典论·论文》** 首次将文学提升到“经国之大业，不朽之盛事”的高度。",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "story_person_names", lambda path: ["苏轼", "李春", "曹丕"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert payload["items"]["赤壁赋"]["authors"] == ["苏轼"]
    assert payload["items"]["赤壁赋"]["era"] == "北宋"
    assert "寄蜉蝣于天地" in payload["items"]["赤壁赋"]["quote"]
    assert payload["items"]["中国石拱桥"]["authors"] == []
    assert payload["items"]["中国石拱桥"]["related_people"] == ["李春"]
    assert payload["items"]["中国石拱桥"]["quote_policy"] == "summary_only"
    assert payload["items"]["典论·论文"]["quote"] == "经国之大业，不朽之盛事。"
    assert payload["items"]["典论·论文"]["quotes"] == [
        "经国之大业，不朽之盛事。",
        "文以气为主。",
        "盖文章，经国之大业，不朽之盛事。",
    ]
    assert payload["items"]["典论·论文"]["quote_policy"] == "preferred"


def test_main_prefers_author_page_quotes_and_injects_fallback_multi_quotes(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "屈原.md").write_text(
        "\n".join(
            [
                "# 屈原",
                "",
                "### 生平概述",
                "屈原是战国楚辞作家。",
                "",
                "### 基本信息",
                "- **时代**：战国",
                "- **主要成就**：创作《离骚》。",
                "",
                "### 历史评价",
                "- 屈原创作《离骚》，写下“路漫漫其修远兮，吾将上下而求索。”与“亦余心之所善兮，虽九死其犹未悔。”",
                "- 《离骚》还常见“惟草木之零落兮，恐美人之迟暮。”",
            ]
        ),
        encoding="utf-8",
    )
    (story_dir / "司马迁.md").write_text(
        "\n".join(
            [
                "# 司马迁",
                "",
                "### 生平概述",
                "司马迁是西汉史学家。",
                "",
                "### 史学评论",
                "- 司马迁评屈原：屈平疾王听之不聪也，故忧愁幽思而作《离骚》。",
            ]
        ),
        encoding="utf-8",
    )
    (story_dir / "诸葛亮.md").write_text(
        "\n".join(
            [
                "# 诸葛亮",
                "",
                "### 生平概述",
                "诸葛亮是蜀汉丞相。",
                "",
                "### 基本信息",
                "- **时代**：三国（蜀汉）",
                "- **主要成就**：写作《出师表》。",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["屈原", "司马迁", "诸葛亮"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert payload["items"]["离骚"]["authors"] == ["屈原"]
    assert payload["items"]["离骚"]["quotes"] == [
        "路漫漫其修远兮，吾将上下而求索。",
        "亦余心之所善兮，虽九死其犹未悔。",
        "惟草木之零落兮，恐美人之迟暮。",
    ]
    assert payload["items"]["出师表"]["authors"] == ["诸葛亮"]
    assert payload["items"]["出师表"]["quotes"] == [
        "臣本布衣，躬耕于南阳，苟全性命于乱世，不求闻达于诸侯。",
        "当奖率三军，北定中原，庶竭驽钝，攘除奸凶，兴复汉室，还于旧都。",
        "此臣所以报先帝而忠陛下之职分也。",
    ]


def test_main_marks_summary_only_works_and_injects_literary_fallback_quotes(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "高适.md").write_text(
        "\n".join(
            [
                "# 高适",
                "",
                "### 生平概述",
                "高适是盛唐边塞诗人。",
                "",
                "### 基本信息",
                "- **时代**：唐",
                "- **主要成就**：写作《别董大》。",
                "",
                "### 历史评价",
                "- **《别董大》** 是送别名篇。",
            ]
        ),
        encoding="utf-8",
    )
    (story_dir / "米开朗琪罗.md").write_text(
        "\n".join(
            [
                "# 米开朗琪罗",
                "",
                "### 生平概述",
                "米开朗琪罗是文艺复兴艺术家。",
                "",
                "### 基本信息",
                "- **主要成就**：创作《大卫》。",
                "",
                "### 历史评价",
                "- **《大卫》** 是文艺复兴雕塑杰作。",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["高适", "米开朗琪罗"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert payload["items"]["别董大"]["quote_policy"] == "preferred"
    assert payload["items"]["别董大"]["quotes"][0] == "莫愁前路无知己，天下谁人不识君。"
    assert payload["items"]["大卫"]["quote_policy"] == "summary_only"
    assert payload["items"]["大卫"]["quotes"] == []
    assert payload["items"]["大卫"]["quote"] == ""


def test_main_normalizes_markdown_wrapped_titles_and_extracts_prefixed_quotes(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "聂耳.md").write_text(
        "\n".join(
            [
                "# 聂耳",
                "",
                "### 生平概述",
                "聂耳是中国革命音乐家。",
                "",
                "### 基本信息",
                "- **主要成就**：创作《**卖报歌**》《**毕业歌**》。",
                "",
                "### 历史评价",
                "- **名篇名句**：《毕业歌》：同学们，大家起来，担负起天下的兴亡！",
                "- **名篇名句**：《卖报歌》：啦啦啦！啦啦啦！我是卖报的小行家！",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["聂耳"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert "卖报歌" in payload["items"]
    assert "**卖报歌**" not in payload["items"]
    assert any("我是卖报的小行家" in item for item in payload["items"]["卖报歌"]["quotes"])
    assert payload["items"]["毕业歌"]["quotes"][0] == "同学们，大家起来，担负起天下的兴亡！"


def test_main_marks_non_quoteable_collections_and_research_as_summary_only(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "海明威.md").write_text(
        "\n".join(
            [
                "# 海明威",
                "",
                "### 生平概述",
                "海明威是美国作家。",
                "",
                "### 重要经历",
                "- 出版《三个故事和十首诗》《在我们的时代里》。",
            ]
        ),
        encoding="utf-8",
    )
    (story_dir / "颜真卿.md").write_text(
        "\n".join(
            [
                "# 颜真卿",
                "",
                "### 生平概述",
                "颜真卿是唐代书法家。",
                "",
                "### 大事年表",
                "| 777年 | | | 书《颜氏家庙碑》，为其晚年楷书代表作。 |",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["海明威", "颜真卿"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert payload["items"]["三个故事和十首诗"]["quote_policy"] == "summary_only"
    assert payload["items"]["在我们的时代里"]["quote_policy"] == "summary_only"
    assert payload["items"]["颜氏家庙碑"]["quote_policy"] == "summary_only"
    assert payload["items"]["颜氏家庙碑"]["quotes"] == []


def test_main_prefers_self_authored_curriculum_works_for_literary_figures(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "李白.md").write_text(
        "\n".join(
            [
                "# 李白",
                "",
                "### 基本信息",
                "- **主要身份**：诗人",
                "- **历史地位**：伟大的浪漫主义诗人",
                "",
                "### 生平概述",
                "李白是盛唐诗人。",
                "",
                "### 人教版教材知识点",
                "### 语文（课文/词作）",
                "- 课文/词作：**《静夜思》**、**《将进酒》**、**《蜀道难》**。",
                "- 核心要点：",
                "    - **重点**：诗歌充满浪漫主义色彩，如“飞流直下三千尺”。",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["李白"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    assert payload["items"]["静夜思"]["authors"] == ["李白"]
    assert payload["items"]["静夜思"]["quote_policy"] == "preferred"
    assert payload["items"]["静夜思"]["quotes"] == [
        "床前明月光，疑是地上霜。",
        "举头望明月，低头思故乡。",
    ]
    assert payload["items"]["将进酒"]["authors"] == ["李白"]
    assert payload["items"]["蜀道难"]["quote_policy"] == "preferred"


def test_main_applies_curated_overrides_for_su_shi_work_tooltips(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "苏轼.md").write_text(
        "\n".join(
            [
                "# 苏轼",
                "",
                "### 生平概述",
                "苏轼生于四川眉山，历经仕途起伏。",
                "",
                "### 黄州时期",
                "- 在此写下《赤壁赋》《前赤壁赋》《念奴娇·赤壁怀古》，书法名作《寒食帖》亦成于此期。",
                "- 《江城子·密州出猎》：会挽雕弓如满月，西北望，射天狼。",
                "- 《水调歌头·明月几时有》（写于密州，但作于弟弟子由共度中秋时思念京华）",
                "- 7. 《记承天寺夜游》的体裁是小品文，表达微妙心境。",
                "",
                "### 人教版教材知识点",
                "- 《记承天寺夜游》：庭下如积水空明，水中藻、荇交横，盖竹柏影也。",
                "",
                "### 基本信息",
                "- **时代**：北宋",
                "- **主要成就**：创作《赤壁赋》《念奴娇·赤壁怀古》《水调歌头·明月几时有》。",
                "",
                "### 历史评价",
                "- 《念奴娇·赤壁怀古》：大江东去，浪淘尽，千古风流人物。",
                "- 《赤壁赋》：寄蜉蝣于天地，渺沧海之一粟。",
                "- 《前赤壁赋》：哀吾生之须臾，羡长江之无穷。",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["苏轼"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    items = payload["items"]
    assert items["水调歌头·明月几时有"]["genre"] == "词"
    assert items["水调歌头·明月几时有"]["quotes"] == [
        "明月几时有？把酒问青天。",
        "但愿人长久，千里共婵娟。",
    ]
    assert items["江城子·密州出猎"]["quotes"] == [
        "老夫聊发少年狂，左牵黄，右擎苍。",
        "会挽雕弓如满月，西北望，射天狼。",
    ]
    assert items["记承天寺夜游"]["one_liner"] == "黄州夜游小品名篇，以空明月色映照贬谪中的清旷心境。"
    assert items["记承天寺夜游"]["quotes"] == [
        "庭下如积水空明，水中藻、荇交横，盖竹柏影也。",
        "但少闲人如吾两人者耳。",
    ]
    assert items["念奴娇·赤壁怀古"]["quotes"] == [
        "大江东去，浪淘尽，千古风流人物。",
        "人生如梦，一尊还酹江月。",
    ]
    assert items["赤壁赋"]["summary"] == "通过赤壁秋夜的江月清风与主客对话，展开对“变”与“不变”的哲思。"
    assert items["前赤壁赋"]["quotes"] == [
        "寄蜉蝣于天地，渺沧海之一粟。",
        "哀吾生之须臾，羡长江之无穷。",
    ]
    assert items["寒食帖"]["quote_policy"] == "summary_only"
    assert items["寒食帖"]["quotes"] == []


def test_main_backfills_curated_su_dongpo_works_and_normalizes_huangzhou_hanshi_title(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_work_summary_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)

    (story_dir / "苏东坡.md").write_text(
        "\n".join(
            [
                "# 苏东坡",
                "",
                "### 生平概述",
                "苏东坡生于四川眉山，黄州时期进入文学与书法高峰。",
                "",
                "### 黄州时期",
                "- **名篇名句**：《念奴娇·赤壁怀古》：大江东去，浪淘尽，千古风流人物；《前赤壁赋》《后赤壁赋》；《黄州寒食诗帖》（天下第三行书）",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_work_summary_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["苏东坡"])

    module.main()

    payload = json.loads((data_dir / "work_summary_index.json").read_text(encoding="utf-8"))
    items = payload["items"]
    assert "记承天寺夜游" in items
    assert items["记承天寺夜游"]["one_liner"] == "黄州夜游小品名篇，以空明月色映照贬谪中的清旷心境。"
    assert "寒食帖" in items
    assert "黄州寒食诗帖" not in items
    assert items["寒食帖"]["quote_policy"] == "summary_only"

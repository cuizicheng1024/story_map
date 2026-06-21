import importlib
import json
import sys


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_main_filters_non_authentic_story_markdown(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_pep_people_spotlight")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text(
        "# 李白\n\n### 生平概述\n李白，唐代诗人。\n\n### 历史评价\n- 短评：浪漫主义诗歌高峰。\n",
        encoding="utf-8",
    )
    (story_dir / "嫦娥.md").write_text(
        "# 嫦娥 神话人物\n\n### 生平概述\n神话人物。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_pep_people_spotlight.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["李白"])

    module.main()

    payload = json.loads((data_dir / "people_summary_index.json").read_text(encoding="utf-8"))
    assert list(payload["items"].keys()) == ["李白"]
    assert payload["items"]["李白"]["review"] == "浪漫主义诗歌高峰。"
    assert payload["items"]["李白"]["short_review"] == "浪漫主义诗歌高峰。"
    assert payload["items"]["李白"]["title"] == ""


def test_summarize_deduplicates_quotes_and_strips_outer_quotes():
    module = importlib.import_module("tools.build_pep_people_spotlight")

    summary = module._summarize(
        "海厄特",
        "\n".join(
            [
                "# 海厄特",
                "",
                "### 生平概述",
                "海厄特出生于美国。",
                "",
                "### 基本信息",
                "- **历史地位**：被誉为“塑料工业之父”，开启了新材料时代。",
                "",
                "### 历史评价",
                "- 被誉为“塑料工业之父”，开启了新材料时代。",
                "- 评价其发明“不仅是一项成功的商业创新，更是一场材料革命的开端”。",
                "",
                "他被誉为“塑料工业之父”。",
                "后来又被称为“塑料工业之父”。",
            ]
        )
    )

    assert summary["spotlight"] == "塑料工业之父"
    assert summary["quotes"] == [
        "塑料工业之父",
        "不仅是一项成功的商业创新，更是一场材料革命的开端",
    ]
    assert summary["short_review"] == "塑料工业之父"
    assert summary["title"] == "塑料工业之父"
    assert summary["honor"] == "塑料工业之父"
    assert summary["reviews"][0] == "被誉为“塑料工业之父”，开启了新材料时代。"


def test_main_orders_people_by_pinyin(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_pep_people_spotlight")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    for name in ("李白", "杜甫", "苏轼"):
        (story_dir / f"{name}.md").write_text(f"# {name}\n\n### 生平概述\n{name}简介。\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_pep_people_spotlight.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["苏轼", "李白", "杜甫"])
    monkeypatch.setattr(
        module,
        "pinyin_variants",
        lambda text: {"杜甫": ["dufu"], "李白": ["libai"], "苏轼": ["sushi"]}.get(text, []),
    )

    module.main()

    payload = json.loads((data_dir / "people_summary_index.json").read_text(encoding="utf-8"))
    assert list(payload["items"].keys()) == ["杜甫", "李白", "苏轼"]

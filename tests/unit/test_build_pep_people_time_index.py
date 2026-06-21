import importlib
import sys
import json


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_parse_story_md_uses_repo_relative_source_path(tmp_path):
    module = importlib.import_module("tools.build_pep_people_time_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    story_path = story_dir / "于谦.md"
    story_path.write_text(
        "# 于谦\n\n### 基本信息\n- **时代**：明朝\n- **出生**：1398年\n- **去世**：1457年\n",
        encoding="utf-8",
    )

    item = module._parse_story_md(story_path, repo_root=repo_root)

    assert item["source"] == "storymap/examples/story/于谦.md"


def test_main_filters_non_authentic_story_markdown(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_pep_people_time_index")
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    tools_dir = repo_root / "tools"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    (story_dir / "霍去病.md").write_text(
        "# 霍去病\n\n### 基本信息\n- **时代**：西汉\n- **出生**：前140年\n- **去世**：前117年\n",
        encoding="utf-8",
    )
    (story_dir / "嫦娥.md").write_text(
        "# 嫦娥 神话人物\n\n### 基本信息\n- **时代**：上古\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(tools_dir / "build_pep_people_time_index.py"))
    monkeypatch.setattr(module, "story_person_names", lambda path: ["霍去病"])

    module.main()

    payload = json.loads((data_dir / "pep_people_time_index.json").read_text(encoding="utf-8"))
    assert [item["name"] for item in payload["items"]] == ["霍去病"]

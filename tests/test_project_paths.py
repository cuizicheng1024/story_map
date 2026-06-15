import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import project_paths


def test_classify_story_person_authenticity_uses_known_registry_when_story_missing(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    monkeypatch.setattr(project_paths, "project_root_path", lambda: repo_root)

    assert project_paths.classify_story_person_authenticity("苏轼", story_dir) == (True, "")
    assert project_paths.classify_story_person_authenticity("苏东坡", story_dir) == (True, "")
    assert project_paths.classify_story_person_authenticity("辛弃疾", story_dir) == (True, "")
    assert project_paths.classify_story_person_authenticity("辛弃疾", story_dir, allow_unknown=False) == (
        False,
        "unknown_person",
    )


def test_classify_story_person_authenticity_does_not_trust_raw_people_json_lists(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (data_dir / "pep_people_merged.json").write_text('["苏轼","嫦娥"]', encoding="utf-8")
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    monkeypatch.setattr(project_paths, "project_root_path", lambda: repo_root)

    assert project_paths.classify_story_person_authenticity("苏轼", story_dir) == (True, "")
    assert project_paths.classify_story_person_authenticity("苏东坡", story_dir) == (True, "")
    assert project_paths.classify_story_person_authenticity("嫦娥", story_dir)[0] is False


def test_story_person_names_filters_virtual_example_story(tmp_path):
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "小凡.md").write_text(
        "# 小凡（虚构示例）\n\n"
        "**⚠️ 警告：此人物为格式示例或虚构角色，并非已知历史或文学人物。所有信息均无可靠来源，仅供参考格式。**\n",
        encoding="utf-8",
    )
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    assert project_paths.story_person_names(story_dir) == ["苏轼"]


def test_authentic_biography_is_not_rejected_by_late_fiction_reference(tmp_path):
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "董卓.md").write_text(
        "# 董卓\n\n"
        "## 人物档案\n\n"
        "- **姓名**：董卓\n"
        "- **时代**：东汉末年\n\n"
        "## 人教版教材知识点\n"
        "- 与吕布、貂蝉（文学虚构人物）的连环计故事常被后世提及。\n",
        encoding="utf-8",
    )

    assert project_paths.classify_story_person_authenticity("董卓", story_dir) == (True, "")
    assert project_paths.story_person_names(story_dir) == ["董卓"]


def test_known_authentic_person_names_ignores_derived_people_master_outputs(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    story_dir = repo_root / "storymap" / "examples" / "story"
    data_dir = repo_root / "data"
    story_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (data_dir / "people_master.json").write_text('{"people":[{"person":"海绵宝宝"}]}', encoding="utf-8")

    monkeypatch.setattr(project_paths, "project_root_path", lambda: repo_root)

    names = project_paths.known_authentic_person_names(story_dir=story_dir)
    assert "苏轼" in names
    assert "苏东坡" in names
    assert "海绵宝宝" not in names

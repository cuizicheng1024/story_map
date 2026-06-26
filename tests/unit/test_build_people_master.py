import importlib
import json
import sys


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_collect_people_filters_placeholder_story_names(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_people_master")
    data_dir = tmp_path / "data"
    story_dir = tmp_path / "story"
    data_dir.mkdir(parents=True)
    story_dir.mkdir(parents=True)
    (data_dir / "pep_people_merged.json").write_text(json.dumps(["李白", "人物 生平传记与足迹"], ensure_ascii=False), encoding="utf-8")
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")
    (story_dir / "人物 生平传记与足迹.md").write_text("# 占位\n", encoding="utf-8")

    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)

    people = module._collect_people()

    assert people == ["李白"]


def test_collect_people_filters_non_authentic_story_names(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_people_master")
    data_dir = tmp_path / "data"
    story_dir = tmp_path / "story"
    data_dir.mkdir(parents=True)
    story_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)

    people = module._collect_people()

    assert people == ["苏轼"]


def test_main_marks_non_authentic_story_as_unpublished(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_people_master")
    repo_root = tmp_path / "repo"
    data_dir = repo_root / "data"
    story_dir = repo_root / "storymap" / "examples" / "story"
    out_path = data_dir / "people_master.json"
    data_dir.mkdir(parents=True)
    story_dir.mkdir(parents=True)
    (data_dir / "pep_people_merged.json").write_text(json.dumps(["苏轼", "嫦娥"], ensure_ascii=False), encoding="utf-8")
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(sys, "argv", ["build_people_master.py", "--out", str(out_path), "--scope", "pep"])

    assert module.main() == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    people = {item["person"]: item for item in payload["people"]}
    assert people["苏轼"]["has_story"] is True
    assert people["苏轼"]["story_md"] == "storymap/examples/story/苏轼.md"
    assert people["嫦娥"]["has_story"] is False
    assert people["嫦娥"]["story_md"] == ""


def test_ensure_story_md_skips_non_authentic_targets_from_raw_people_lists(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_people_master")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "story_person_names", lambda _dir: ["苏轼"])

    result = module._ensure_story_md(["苏轼", "苏东坡", "嫦娥"], True, 0, True, 2)

    assert result == {"attempted": 0, "created": 0, "failures": []}


def test_pick_years_keeps_bce_years_negative():
    module = importlib.import_module("tools.build_people_master")
    md = (
        "# 释迦牟尼\n\n"
        "- **出生**：约公元前563年，蓝毗尼\n"
        "- **去世**：约公元前483年，拘尸那迦\n"
    )

    birth, death = module._pick_years(md)

    assert birth == -563
    assert death == -483


def test_pick_years_normalizes_bce_order():
    module = importlib.import_module("tools.build_people_master")
    md = "- **生卒年**：前139年—前128年"

    birth, death = module._pick_years(md)

    assert birth == -139
    assert death == -128


def test_pick_birthplace_strips_bce_prefix():
    module = importlib.import_module("tools.build_people_master")
    md = "- **出生**：约前234年，匈奴"

    raw, ancient, modern = module._pick_birthplace(md)

    assert raw == "匈奴"
    assert ancient == "匈奴"
    assert modern == ""


def test_pick_birthplace_strips_bce_ambiguous_year_prefix():
    module = importlib.import_module("tools.build_people_master")
    md = "- **出生**：约公元前428/427年（存疑），雅典（今希腊雅典）或埃伊纳岛（今希腊埃伊纳岛）（说法不一）"

    raw, ancient, modern = module._pick_birthplace(md)

    assert "428" not in raw
    assert raw.startswith("雅典")
    assert ancient == "雅典"
    assert modern == "希腊雅典"

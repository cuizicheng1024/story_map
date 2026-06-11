import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
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

    payload = json.loads((data_dir / "pep_people_spotlight.json").read_text(encoding="utf-8"))
    assert list(payload["items"].keys()) == ["李白"]
    assert payload["items"]["李白"]["review"] == "浪漫主义诗歌高峰。"

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
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

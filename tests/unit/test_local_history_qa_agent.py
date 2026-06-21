import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from history_qa_agent import LocalHistoryQAAgent


def test_local_history_qa_agent_answers_locations_from_local_story():
    agent = LocalHistoryQAAgent(project_root=lambda: str(REPO_ROOT))

    result = agent.answer(
        {
            "messages": [{"role": "user", "content": "他去过哪里？"}],
            "context": {"personName": "苏轼"},
        }
    )

    assert result.handled is True
    assert result.person_name == "苏轼"
    assert "根据本地人物档案" in result.content
    assert ("足迹" in result.content) or ("时间线" in result.content)


def test_local_history_qa_agent_filters_non_authentic_people_from_known_list(tmp_path):
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    agent = LocalHistoryQAAgent(project_root=lambda: str(tmp_path))

    assert agent._list_known_people() == ["苏轼"]


def test_local_history_qa_agent_blocks_non_authentic_person_even_when_context_passes_name(tmp_path):
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    agent = LocalHistoryQAAgent(project_root=lambda: str(tmp_path))
    result = agent.answer(
        {
            "messages": [{"role": "user", "content": "她是谁？"}],
            "context": {"personName": "嫦娥"},
        }
    )

    assert result.handled is False
    assert result.person_name == "嫦娥"
    assert result.reason == "story_not_found"


def test_local_history_qa_agent_loads_canonical_markdown_for_alias_name(tmp_path):
    story_dir = tmp_path / "storymap" / "examples" / "story"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n\n## 一、人物简介\n- **主要身份**：文学家\n", encoding="utf-8")
    (data_dir / "people_master.json").write_text('{"people":[{"person":"苏轼"}]}', encoding="utf-8")

    agent = LocalHistoryQAAgent(project_root=lambda: str(tmp_path))
    result = agent.answer(
        {
            "messages": [{"role": "user", "content": "他是谁？"}],
            "context": {"personName": "苏东坡"},
        }
    )

    assert result.handled is True
    assert result.person_name == "苏东坡"
    assert "苏东坡" in result.content

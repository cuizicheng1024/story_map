import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
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

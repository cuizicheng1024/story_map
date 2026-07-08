import subprocess
import sys

from tests_support import REPO_ROOT

def test_legacy_story_map_script_entrypoint_supports_help():
    script_path = REPO_ROOT / "storymap" / "script" / "story_map.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--serve" in result.stdout

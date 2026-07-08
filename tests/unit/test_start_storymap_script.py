from __future__ import annotations

from tests_support import REPO_ROOT

def test_start_script_defaults_to_non_strict_startup_only_for_local_dev():
    content = (REPO_ROOT / "scripts" / "start_storymap.sh").read_text(encoding="utf-8")

    assert 'if [[ -z "${STORY_MAP_STRICT_STARTUP:-}" && -z "${MAP_STORY_STRICT_STARTUP:-}" ]]; then' in content
    assert 'if [[ "${STORY_MAP_LOCAL_DEV:-}" == "1" || "$(uname -s)" == "Darwin" ]]; then' in content
    assert 'export STORY_MAP_STRICT_STARTUP=0' in content
    assert 'defaulting to 0 for local development' in content

def test_start_script_still_uses_story_map_entrypoint():
    content = (REPO_ROOT / "scripts" / "start_storymap.sh").read_text(encoding="utf-8")

    assert 'export STORY_AGENT_SILENT="${STORY_AGENT_SILENT:-1}"' in content
    assert '"${PYTHON_BIN}" tools/build/sync_song_minister_game.py >/dev/null' in content
    assert 'exec "${PYTHON_BIN}" storymap/script/story_map.py --serve --port "${PORT}"' in content

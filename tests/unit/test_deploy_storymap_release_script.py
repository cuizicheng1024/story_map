from __future__ import annotations

import subprocess

from tests_support import REPO_ROOT

SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy_storymap_release.sh"

def test_deploy_script_refuses_builtin_default_target():
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--skip-upload", "--skip-remote", "--skip-verify"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "refusing to deploy to built-in default target" in result.stderr

def test_deploy_script_allows_explicit_target_when_upload_and_remote_are_skipped(tmp_path):
    identity = tmp_path / "storymap-key.pem"
    identity.write_text("dummy-key", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--host",
            "1.2.3.4",
            "--user",
            "deploy",
            "--identity",
            str(identity),
            "--skip-upload",
            "--skip-remote",
            "--skip-verify",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "[deploy] done" in result.stdout

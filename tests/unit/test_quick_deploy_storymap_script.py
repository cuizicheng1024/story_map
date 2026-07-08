from __future__ import annotations

import subprocess

from tests_support import REPO_ROOT

SCRIPT_PATH = REPO_ROOT / "scripts" / "quick_deploy_storymap.sh"

def test_quick_deploy_script_refuses_builtin_default_target_for_volc():
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--target", "volc", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "refusing to deploy to built-in default target" in result.stderr

def test_quick_deploy_script_allows_explicit_target_for_volc(tmp_path):
    identity = tmp_path / "storymap-key.pem"
    identity.write_text("dummy-key", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--target",
            "volc",
            "--host",
            "1.2.3.4",
            "--user",
            "deploy",
            "--identity",
            str(identity),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "[quick-deploy] done" in result.stdout

def test_quick_deploy_script_supports_opendeploy_dry_run():
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--target", "opendeploy", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "upload source to OpenDeploy" in result.stdout
    assert "[quick-deploy] done" in result.stdout

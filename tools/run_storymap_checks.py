#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = [
    "tests/test_env_aliases.py",
    "tests/test_output_paths.py",
    "tests/test_artifacts.py",
    "tests/test_static_service.py",
    "tests/test_parsers.py",
    "tests/test_offline_profile_locations.py",
    "tests/test_generation_flow.py",
    "tests/test_fastapi_app.py",
    "tests/test_task_service.py",
    "tests/test_profile_page_template.py",
    "tests/test_validate_story_markdown.py",
]
DEFAULT_RUFF_TARGETS = [
    "storymap/script/story_map.py",
    "storymap/script/app_factory.py",
    "storymap/script/artifacts.py",
    "storymap/script/static.py",
    "storymap/script/task.py",
    "storymap/script/runtime_support.py",
    "storymap/script/export_builders.py",
    "tests/test_artifacts.py",
    "tests/test_fastapi_app.py",
    "tests/test_static_service.py",
    "tests/test_task_service.py",
    "tools/run_storymap_checks.py",
]


def _run(command: list[str]) -> int:
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT)
    return completed.returncode


def _has_module(python_bin: str, module_name: str) -> bool:
    completed = subprocess.run(
        [python_bin, "-c", f"import {module_name}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _python_bin() -> str:
    active_venv = (os.getenv("VIRTUAL_ENV") or "").strip()
    candidates = [
        str(Path(active_venv) / "bin" / "python") if active_venv else "",
        sys.executable,
        str(REPO_ROOT / ".venv311" / "bin" / "python"),
        str(REPO_ROOT / ".venv" / "bin" / "python"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists() and _has_module(candidate, "pytest"):
            return candidate
    return sys.executable


def _ruff_command(python_bin: str) -> list[str] | None:
    if _has_module(python_bin, "ruff"):
        return [python_bin, "-m", "ruff"]

    sibling_ruff = Path(python_bin).with_name("ruff")
    if sibling_ruff.exists():
        return [str(sibling_ruff)]

    current_env_ruff = shutil.which("ruff")
    if current_env_ruff:
        return [current_env_ruff]

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 StoryMap 的本地自检流程")
    parser.add_argument("--skip-ruff", action="store_true", help="跳过 Ruff 检查")
    parser.add_argument("--all-tests", action="store_true", help="运行整个 tests 目录")
    args = parser.parse_args()

    python_bin = _python_bin()

    if not args.skip_ruff:
        ruff_command = _ruff_command(python_bin)
        if ruff_command:
            rc = _run([*ruff_command, "check", "--select", "F", *DEFAULT_RUFF_TARGETS])
            if rc != 0:
                return rc
        else:
            print("! 未找到 ruff，已跳过静态检查")

    test_targets = ["tests"] if args.all_tests else DEFAULT_TESTS
    return _run([python_bin, "-m", "pytest", *test_targets])


if __name__ == "__main__":
    raise SystemExit(main())

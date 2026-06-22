from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


_REPO_ROOT = Path(__file__).resolve().parents[3]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_head(root: Path | None = None) -> str:
    repo_root = Path(root or _REPO_ROOT).resolve()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def build_artifact_meta(*, component: str, version: str = "", build_at: str = "") -> Dict[str, object]:
    run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    run_attempt = str(os.getenv("GITHUB_RUN_ATTEMPT") or "").strip()
    built_at = str(build_at or os.getenv("STORYMAP_BUILD_AT") or now_utc_iso()).strip() or now_utc_iso()
    source_commit = str(os.getenv("GITHUB_SHA") or "").strip() or git_head()
    normalized_component = str(component or "").strip() or "unknown"
    normalized_version = str(version or "").strip() or str(os.getenv("STORYMAP_BUILD_VERSION") or "").strip()
    if not normalized_version:
        normalized_version = str(source_commit or "").strip()[:12]
    if not normalized_version:
        normalized_version = built_at.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    return {
        "artifact_component": normalized_component,
        "artifact_version": normalized_version,
        "build_version": normalized_version,
        "build_at": built_at,
        "generated_at": built_at,
        "source_commit": source_commit,
        "pages_run_id": int(run_id) if run_id.isdigit() else run_id,
        "pages_run_attempt": int(run_attempt) if run_attempt.isdigit() else run_attempt,
    }


__all__ = ["build_artifact_meta", "git_head", "now_utc_iso"]

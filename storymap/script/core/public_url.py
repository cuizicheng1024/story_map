from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from .project_paths import project_root_path, story_artifacts_dir_path


def public_base_url() -> str:
    raw = str(os.getenv("STORYMAP_PUBLIC_BASE_URL", "") or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw.rstrip("/") + "/"


def _public_path_from_local_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return text
    if text.startswith("./"):
        text = text[2:]
    if text.startswith("/"):
        return text
    try:
        path = Path(text).expanduser()
        if path.is_absolute():
            artifact_root = story_artifacts_dir_path().resolve()
            try:
                return "/" + quote(path.resolve().relative_to(artifact_root).as_posix(), safe="/%")
            except Exception:
                try:
                    return "/" + quote(path.resolve().relative_to(project_root_path().resolve()).as_posix(), safe="/%")
                except Exception:
                    return "/" + quote(path.name, safe="/%")
    except Exception:
        pass
    artifact_prefix = "artifacts/story_map/"
    normalized = text.replace("\\", "/")
    if normalized.startswith(artifact_prefix):
        normalized = normalized[len(artifact_prefix):]
    return "/" + quote(normalized.lstrip("/"), safe="/%")


def public_url(value: str) -> str:
    base = public_base_url()
    if not base:
        return ""
    path = _public_path_from_local_path(value)
    if not path:
        return ""
    parsed = urlparse(path)
    if parsed.scheme in {"http", "https"}:
        return path
    return urljoin(base, path.lstrip("/"))

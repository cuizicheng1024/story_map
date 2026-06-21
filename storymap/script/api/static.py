import os
import re
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import unquote

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse


class StaticService:
    def __init__(
        self,
        *,
        active_story_map_dir: Callable[[], str],
        public_story_map_dirs: Callable[[], list[str]],
        project_root: Callable[[], str],
        fetch_vendor_bytes: Callable[[str], Tuple[str, bytes]],
        vendor_cache: Dict[str, Tuple[str, bytes]],
        vendor_lock: object,
    ) -> None:
        self._active_story_map_dir = active_story_map_dir
        self._public_story_map_dirs = public_story_map_dirs
        self._project_root = project_root
        self._fetch_vendor_bytes = fetch_vendor_bytes
        self._vendor_cache = vendor_cache
        self._vendor_lock = vendor_lock

    def _local_vendor_roots(self) -> list[Path]:
        roots: list[Path] = []
        seen: set[Path] = set()
        for base in [*self._public_story_map_dirs(), str(Path(self._project_root()) / "vendor")]:
            root = Path(base).resolve()
            if root in seen:
                continue
            seen.add(root)
            roots.append(root)
        return roots

    def _local_vendor_target(self, safe_name: str) -> Optional[Path]:
        # Generated pages reference "./vendor/*.js", so check each served static root
        # before falling back to remote fetch. This keeps local/offline pages usable.
        for root in self._local_vendor_roots():
            vendor_root = root if root.name == "vendor" else (root / "vendor")
            target = (vendor_root / safe_name).resolve()
            try:
                target.relative_to(vendor_root.resolve())
            except Exception:
                continue
            if target.exists() and target.is_file():
                return target
        return None

    def guess_content_type(self, path: str) -> str:
        lower = str(path or "").lower()
        if lower.endswith(".html"):
            return "text/html; charset=utf-8"
        if lower.endswith(".geojson"):
            return "application/geo+json; charset=utf-8"
        if lower.endswith(".json"):
            return "application/json; charset=utf-8"
        if lower.endswith(".csv"):
            return "text/csv; charset=utf-8"
        if lower.endswith(".css"):
            return "text/css; charset=utf-8"
        if lower.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".svg"):
            return "image/svg+xml"
        return "application/octet-stream"

    def _resolve_target_in_root(self, static_root: Path, rel: str) -> Optional[Path]:
        target = (static_root / rel).resolve()
        try:
            target.relative_to(static_root)
        except Exception:
            return None
        if not target.exists() or not target.is_file():
            return None
        return target

    def static_target_path(self, parsed_path: str) -> Optional[Path]:
        rel = unquote((parsed_path or "").lstrip("/"))
        if rel.startswith("artifacts/story_map/"):
            rel = rel.split("artifacts/story_map/", 1)[-1]
        if parsed_path == "/" or rel == "":
            rel = "index.html"
        if not re.search(r"\.(html|geojson|json|csv|css|js|png|jpg|jpeg|svg)$", rel, flags=re.IGNORECASE):
            return None
        roots = list(self._public_story_map_dirs())
        if rel != "index.html" and len(roots) > 1:
            # Generated artifact pages should win over legacy duplicates in older roots.
            roots = roots[1:] + roots[:1]
        for root in roots:
            target = self._resolve_target_in_root(Path(root).resolve(), rel)
            if target is not None:
                return target
        return None

    def vendor_response(self, name: str) -> Response:
        safe_name = unquote(str(name or "")).strip().lstrip("/")
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.(js|css)", safe_name):
            raise HTTPException(status_code=404, detail="not found")
        local_target = self._local_vendor_target(safe_name)
        if local_target is not None:
            return FileResponse(path=local_target, media_type=self.guess_content_type(local_target.name))
        with self._vendor_lock:
            cached = self._vendor_cache.get(safe_name)
        if cached:
            content_type, body = cached
            return Response(content=body, media_type=content_type)
        try:
            content_type, body = self._fetch_vendor_bytes(safe_name)
        except Exception:
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "vendor fetch failed", "name": safe_name},
            )
        with self._vendor_lock:
            self._vendor_cache[safe_name] = (content_type, body)
        return Response(content=body, media_type=content_type)

    def static_response(self, parsed_path: str) -> Response:
        target = self.static_target_path(parsed_path)
        if target is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path=target, media_type=self.guess_content_type(target.name))

    def debug_static_payload(self) -> Dict[str, object]:
        static_dir = self._active_story_map_dir()
        index_path = os.path.join(static_dir, "index.html")
        return {
            "ok": True,
            "static_dir": static_dir,
            "static_dirs": self._public_story_map_dirs(),
            "static_exists": os.path.exists(static_dir),
            "index_exists": os.path.exists(index_path),
            "cwd": os.getcwd(),
            "project_root": self._project_root(),
        }

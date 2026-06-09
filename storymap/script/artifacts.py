import json
import os
import re
import subprocess
import sys
import threading
from typing import Callable, Dict, List, Optional, Tuple

try:
    from .project_paths import (
        project_root_path,
        story_artifacts_dir_path,
        story_md_dir_path,
    )
except ImportError:
    from project_paths import (
        project_root_path,
        story_artifacts_dir_path,
        story_md_dir_path,
    )


def _project_root() -> str:
    return str(project_root_path())


def _story_md_dir() -> str:
    return str(story_md_dir_path())


def _story_artifacts_dir() -> str:
    return str(story_artifacts_dir_path())


def _story_map_index_path(directory: str) -> str:
    return os.path.join(directory, "index.html")


def _homepage_story_map_dir() -> str:
    return _story_artifacts_dir()


def _public_story_map_dirs() -> List[str]:
    return [os.path.abspath(_story_artifacts_dir())]


def _active_story_map_dir() -> str:
    return _homepage_story_map_dir()


def _safe_name(text: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|]', "_", text).strip()
    return safe or "map"


def save_html(person: str, content: str) -> str:
    base = _story_artifacts_dir()
    os.makedirs(base, exist_ok=True)
    safe = _safe_name(person)
    path = os.path.join(base, f"{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 交互式地图已保存: {path}")
    return path


def save_geojson(person: str, geojson: Dict) -> str:
    base = _story_artifacts_dir()
    os.makedirs(base, exist_ok=True)
    safe = _safe_name(person)
    path = os.path.join(base, f"{safe}.geojson")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    print(f"✅ GeoJSON 已保存: {path}")
    return path


def save_csv(person: str, csv_text: str) -> str:
    base = _story_artifacts_dir()
    os.makedirs(base, exist_ok=True)
    safe = _safe_name(person)
    path = os.path.join(base, f"{safe}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(csv_text)
    print(f"✅ CSV 已保存: {path}")
    return path


def _story_paths(person: str) -> Tuple[str, str]:
    safe = _safe_name(person)
    md_path = os.path.join(_story_md_dir(), f"{safe}.md")
    html_path = os.path.join(_story_artifacts_dir(), f"{safe}.html")
    return md_path, html_path


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _write_text(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _extract_export_data_from_html(html_text: str) -> Optional[Dict[str, object]]:
    if not isinstance(html_text, str) or not html_text.strip():
        return None
    idx = html_text.find("window.__EXPORT_DATA__")
    if idx < 0:
        return None
    prefix = html_text.rfind("const data", 0, idx)
    if prefix < 0:
        return None
    eq = html_text.find("=", prefix, idx)
    if eq < 0:
        return None
    brace = html_text.find("{", eq, idx)
    if brace < 0:
        return None
    semi = html_text.rfind(";", brace, idx)
    if semi < 0:
        return None
    raw = html_text[brace:semi].strip()
    if not raw.startswith("{") or not raw.endswith("}"):
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _relative_path(path: str) -> str:
    root = _project_root()
    if not path:
        return ""
    try:
        return os.path.relpath(path, root)
    except Exception:
        return path


def _update_home_coords(
    data: object,
    home_coords_lock: threading.Lock,
) -> Tuple[int, Dict[str, object]]:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict) or not items:
        return 400, {"ok": False, "error": "items required"}
    home_path = os.path.join(_story_artifacts_dir(), "stellar_home_data.json")
    updated = 0
    total = 0
    with home_coords_lock:
        try:
            with open(home_path, "r", encoding="utf-8") as f:
                home = json.load(f)
        except Exception:
            home = {}
        if not isinstance(home, dict):
            home = {}
        nodes = home.get("nodes") if isinstance(home.get("nodes"), list) else []
        if not isinstance(nodes, list):
            nodes = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            person = str(n.get("person") or "").strip()
            if not person:
                continue
            value = items.get(person)
            if not (isinstance(value, list) and len(value) >= 2):
                continue
            try:
                lat = float(value[0])
                lng = float(value[1])
            except Exception:
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            before_ok = isinstance(n.get("birth_lat"), (int, float)) and isinstance(
                n.get("birth_lng"), (int, float)
            )
            n["birth_lat"] = lat
            n["birth_lng"] = lng
            if not before_ok:
                updated += 1
        total = len([n for n in nodes if isinstance(n, dict)])
        home["nodes"] = nodes
        try:
            with open(home_path, "w", encoding="utf-8") as f:
                json.dump(home, f, ensure_ascii=False)
        except Exception as exc:
            return 500, {"ok": False, "error": str(exc)}
    return 200, {"ok": True, "updated": updated, "total": total}


def refresh_stellar_homepage(person: str = "") -> Dict[str, object]:
    command = [
        sys.executable,
        "tools/build_stellar_homepage.py",
        "--story-map-dir",
        _story_artifacts_dir(),
        "--story-md-dir",
        _story_md_dir(),
    ]
    completed = subprocess.run(
        command,
        cwd=_project_root(),
        capture_output=True,
        text=True,
    )
    output = "\n".join(
        part.strip()
        for part in (completed.stdout or "", completed.stderr or "")
        if part and part.strip()
    ).strip()
    return {
        "ok": completed.returncode == 0,
        "person": person,
        "index_path": os.path.join(_story_artifacts_dir(), "index.html"),
        "data_path": os.path.join(_story_artifacts_dir(), "stellar_home_data.json"),
        "returncode": completed.returncode,
        "output": output,
    }


class ArtifactExportService:
    def __init__(
        self,
        *,
        build_geojson_for_profile: Callable[[Dict[str, object]], Dict[str, object]],
        build_csv_for_profile: Callable[[Dict[str, object]], str],
        build_geojson_for_multi: Callable[[List[Dict[str, object]]], Dict[str, object]],
        build_csv_for_multi: Callable[[List[Dict[str, object]]], str],
    ) -> None:
        self._build_geojson_for_profile = build_geojson_for_profile
        self._build_csv_for_profile = build_csv_for_profile
        self._build_geojson_for_multi = build_geojson_for_multi
        self._build_csv_for_multi = build_csv_for_multi

    def ensure_profile_exports(
        self,
        profile: Dict[str, object],
        base_name: str,
        allow_cache: bool = True,
    ) -> Dict[str, str]:
        safe = _safe_name(base_name)
        output_dir = _story_artifacts_dir()
        geo_path = os.path.join(output_dir, f"{safe}.geojson")
        csv_path = os.path.join(output_dir, f"{safe}.csv")
        if not (allow_cache and os.path.exists(geo_path)):
            geo = self._build_geojson_for_profile(profile)
            _write_text(geo_path, json.dumps(geo, ensure_ascii=False, indent=2))
        if not (allow_cache and os.path.exists(csv_path)):
            csv_text = self._build_csv_for_profile(profile)
            _write_text(csv_path, csv_text)
        return {"geojson": geo_path, "csv": csv_path}

    def ensure_multi_exports(
        self,
        people: List[Dict[str, object]],
        base_name: str,
        allow_cache: bool = True,
    ) -> Dict[str, str]:
        safe = _safe_name(base_name)
        output_dir = _story_artifacts_dir()
        geo_path = os.path.join(output_dir, f"{safe}.geojson")
        csv_path = os.path.join(output_dir, f"{safe}.csv")
        if not (allow_cache and os.path.exists(geo_path)):
            geo = self._build_geojson_for_multi(people)
            _write_text(geo_path, json.dumps(geo, ensure_ascii=False, indent=2))
        if not (allow_cache and os.path.exists(csv_path)):
            csv_text = self._build_csv_for_multi(people)
            _write_text(csv_path, csv_text)
        return {"geojson": geo_path, "csv": csv_path}

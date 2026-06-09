import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from static import StaticService


def _build_service(homepage_dir: Path, artifact_dir: Path) -> StaticService:
    return StaticService(
        active_story_map_dir=lambda: str(homepage_dir),
        public_story_map_dirs=lambda: [str(homepage_dir), str(artifact_dir)],
        project_root=lambda: str(REPO_ROOT),
        fetch_vendor_bytes=lambda _name: ("application/javascript; charset=utf-8", b""),
        vendor_cache={},
        vendor_lock=__import__("threading").Lock(),
    )


def test_static_service_prefers_homepage_index_but_can_find_generated_artifact(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (artifact_dir / "霍去病.html").write_text("<html>artifact</html>", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/") == homepage_dir / "index.html"
    assert service.static_target_path("/artifacts/story_map/霍去病.html") == artifact_dir / "霍去病.html"


def test_static_service_prefers_artifact_pages_over_legacy_duplicates(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (homepage_dir / "霍去病.html").write_text("<html>legacy</html>", encoding="utf-8")
    (artifact_dir / "霍去病.html").write_text("<html>artifact</html>", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/霍去病.html") == artifact_dir / "霍去病.html"


def test_static_service_serves_export_files(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (artifact_dir / "苏轼.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    (artifact_dir / "苏轼.csv").write_text("name,lat,lng\n苏轼,30,120\n", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/苏轼.geojson") == artifact_dir / "苏轼.geojson"
    assert service.static_target_path("/苏轼.csv") == artifact_dir / "苏轼.csv"
    assert service.guess_content_type("苏轼.geojson") == "application/geo+json; charset=utf-8"
    assert service.guess_content_type("苏轼.csv") == "text/csv; charset=utf-8"


def test_static_service_prefers_local_vendor_files_over_remote_fetch(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    vendor_dir = artifact_dir / "vendor"
    homepage_dir.mkdir(parents=True)
    vendor_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    local_vendor = vendor_dir / "react.production.min.js"
    local_vendor.write_text("window.React = {};", encoding="utf-8")

    service = StaticService(
        active_story_map_dir=lambda: str(homepage_dir),
        public_story_map_dirs=lambda: [str(homepage_dir), str(artifact_dir)],
        project_root=lambda: str(REPO_ROOT),
        fetch_vendor_bytes=lambda _name: (_ for _ in ()).throw(AssertionError("should not fetch remote vendor")),
        vendor_cache={},
        vendor_lock=__import__("threading").Lock(),
    )

    response = service.vendor_response("react.production.min.js")

    assert isinstance(response, FileResponse)
    assert Path(response.path) == local_vendor


def test_static_service_rejects_unsafe_paths(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/../../secret.txt") is None
    try:
        service.static_response("/../../secret.txt")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("static_response should reject unsafe paths")

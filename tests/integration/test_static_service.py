from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from tests_support import REPO_ROOT

from storymap.script.api.static import StaticService

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
    (homepage_dir / "landing.html").write_text("<html>landing</html>", encoding="utf-8")
    (artifact_dir / "霍去病.html").write_text("<html>artifact</html>", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/") == homepage_dir / "landing.html"
    assert service.static_target_path("/index.html") == homepage_dir / "index.html"
    assert service.static_target_path("/artifacts/story_map/霍去病.html") == artifact_dir / "霍去病.html"

def test_static_service_disables_cache_for_html_pages(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (artifact_dir / "苏轼.html").write_text("<html>sushi</html>", encoding="utf-8")

    service = _build_service(homepage_dir, artifact_dir)

    response = service.static_response("/苏轼.html")

    assert isinstance(response, FileResponse)
    assert response.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"

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

def test_static_service_serves_zip_downloads(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (artifact_dir / "song-minister-game.zip").write_bytes(b"PK\x03\x04demo")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/song-minister-game.zip") == artifact_dir / "song-minister-game.zip"
    assert service.guess_content_type("song-minister-game.zip") == "application/zip"

def test_static_service_serves_mp3_assets(tmp_path):
    homepage_dir = tmp_path / "storymap" / "examples" / "story_map"
    artifact_dir = tmp_path / "artifacts" / "story_map"
    homepage_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (homepage_dir / "index.html").write_text("<html>home</html>", encoding="utf-8")
    (artifact_dir / "bgm.mp3").write_bytes(b"ID3demo")

    service = _build_service(homepage_dir, artifact_dir)

    assert service.static_target_path("/bgm.mp3") == artifact_dir / "bgm.mp3"
    assert service.guess_content_type("bgm.mp3") == "audio/mpeg"

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

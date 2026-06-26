from __future__ import annotations

import zipfile

import tools.build.sync_song_minister_game as module


def test_sync_song_minister_game_extracts_index_and_assets(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    zip_path = repo_root / "song-minister-game.zip"
    artifact_root = repo_root / "artifacts" / "story_map"
    artifact_root.mkdir(parents=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("song-minister-game/index.html", "<html>game</html>")
        archive.writestr("song-minister-game/game.js", "console.log('game')")
        archive.writestr("song-minister-game/assets/court.png", b"png")

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "ZIP_PATH", zip_path)
    monkeypatch.setattr(module, "TARGET_DIR", artifact_root / "song-minister-game")

    target = module.sync_song_minister_game()

    assert target == artifact_root / "song-minister-game"
    assert (target / "index.html").read_text(encoding="utf-8") == "<html>game</html>"
    assert (target / "game.js").read_text(encoding="utf-8") == "console.log('game')"
    assert (target / "assets" / "court.png").read_bytes() == b"png"
